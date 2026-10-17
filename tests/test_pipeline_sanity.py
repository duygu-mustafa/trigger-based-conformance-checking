"""Fast sanity harness for pipeline fixes (pipeline_fixes_plan.md).

Plain-assert, no pytest dependency. Run directly:
    python tests/test_pipeline_sanity.py

Rerun after every phase in the plan; extend the relevant check in-place
rather than adding a parallel one. Each assertion below is tagged with the
phase that is expected to make it pass.
"""

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from derive.pipeline import raw_to_event_log
from conformance.checker import evaluate_constraint
from conformance.results import ConformanceOutcome
from conformance.rules import build_readiness_assessment_model
from derive.death_outcomes import DEATH_FAILURE_LABEL, apply_death_rule


def _row(stay_id, event_time, source_table, itemid, value_text=None, value_num=None):
    return {
        "stay_id": stay_id,
        "event_time": pd.Timestamp(event_time),
        "source_table": source_table,
        "itemid": itemid,
        "value_text": value_text,
        "value_num": value_num,
    }


def build_synthetic_raw_df() -> pd.DataFrame:
    t0 = pd.Timestamp("2026-01-01 00:00:00")
    rows = [
        # Ventilator mode: Full Support -> SBT -> Full Support (re-vent/failure).
        _row(1, t0, "ventilator_setting", "ventilator_mode", value_text="CMV"),
        _row(1, t0 + pd.Timedelta(hours=1), "ventilator_setting", "ventilator_mode", value_text="SIMV/PSV"),
        _row(1, t0 + pd.Timedelta(hours=3), "ventilator_setting", "ventilator_mode", value_text="CMV"),
        # Diuretic administration (furosemide).
        _row(1, t0 + pd.Timedelta(hours=2), "inputevents", 221794, value_num=20.0),
        # Mental status: RASS 'Yes' (criterion not met; unrelated to activities under test here).
        _row(1, t0 + pd.Timedelta(minutes=30), "chartevents", 228302, value_text="Yes"),
        # Cuff leak test via cuff pressure.
        _row(1, t0 + pd.Timedelta(hours=2, minutes=30), "chartevents", 224417, value_num=25.0),
    ]
    return pd.DataFrame(rows)


def test_raw_to_event_log_activities():
    raw_df = build_synthetic_raw_df()
    event_log = raw_to_event_log(raw_df)
    activities = set(event_log["activity"])

    assert "Diuretic_Admin" in activities, (
        "Phase 1: furosemide_admin measurement row never mapped to Diuretic_Admin activity"
    )

    assert "CuffLeakTest_Performed" in activities, (
        "Phase 2: cuff pressure (224417) never mapped to CuffLeakTest_Performed"
    )

    end_events = event_log[event_log["activity"].str.contains("InvasiveVentilationEnded", na=False)]
    assert len(end_events) == 1, (
        f"Phase 8: expected exactly one InvasiveVentilationEnded-flavoured event, got {len(end_events)}"
    )

    assert not any(str(a).strip().lower() == "nan" for a in activities), (
        "Phase 8: literal 'nan' activity name leaked into event log"
    )

    sbt_started = event_log[event_log["activity"] == "SBTStarted"].sort_values("timestamp")
    sbt_failed = event_log[event_log["activity"] == "SBTFailed"].sort_values("timestamp")
    assert not sbt_started.empty and not sbt_failed.empty, "expected one SBTStarted and one SBTFailed event"
    start_ts = sbt_started.iloc[0]["timestamp"]
    failed_ts = sbt_failed.iloc[0]["timestamp"]
    assert start_ts < failed_ts <= start_ts + pd.Timedelta(hours=48), (
        f"Phase 3: SBTFailed ({failed_ts}) must fall strictly inside its own episode window "
        f"(start={start_ts})"
    )

    # Phase 3: episode-boundary containment. The synthetic trace has two
    # InvasiveVentilationStarted triggers (initial CMV at t0, re-vent CMV at
    # t0+3h) forming episodes [t0, t0+3h) and [t0+3h, end). SBTStarted sits in
    # the first episode; SBTFailed's re-vent trigger equals the second
    # episode's own start_ts, so a naive [start, end) slice would misfile
    # SBTFailed into episode 2. The -1s shift must keep it in episode 1.
    vent_triggers = (
        event_log[event_log["activity"] == "InvasiveVentilationStarted"]
        .sort_values("timestamp")["timestamp"]
        .tolist()
    )
    assert len(vent_triggers) == 2, (
        f"Phase 3 harness precondition: expected 2 InvasiveVentilationStarted triggers, got {len(vent_triggers)}"
    )
    episode1_start, episode2_start = vent_triggers
    assert episode1_start <= start_ts < episode2_start, (
        "Phase 3 harness precondition: SBTStarted must fall in episode 1"
    )
    assert episode1_start <= failed_ts < episode2_start, (
        f"Phase 3: SBTFailed ({failed_ts}) must land in the same episode slice as its SBTStarted "
        f"[{episode1_start}, {episode2_start}), not be pushed into the next episode by the "
        f"re-ventilation boundary collision"
    )

    print("PASS: test_raw_to_event_log_activities")


def test_rc_dp_06_mental_status_rass_or_sas():
    # RC-DP-06's mental_status_ok checks RASS LOC ('No') OR SAS (in [3, 4]).
    # MentalStatusMeasured is emitted for every RASS LOC and every SAS reading,
    # since RASS is documented in only a small fraction of stays in this cohort
    # and SAS is the far more common fallback instrument.
    t0 = pd.Timestamp("2026-01-01 00:00:00")
    raw_df = pd.DataFrame([
        _row(1, t0, "ventilator_setting", "ventilator_mode", value_text="CMV"),
        _row(1, t0 + pd.Timedelta(hours=1), "chartevents", 228302, value_text="No"),
        _row(1, t0 + pd.Timedelta(hours=2), "ventilator_setting", "ventilator_mode", value_text="SIMV/PSV"),
    ])
    event_log = raw_to_event_log(raw_df)

    model = build_readiness_assessment_model()
    constraint = next(c for c in model.constraints if getattr(c, "id", None) == "RC-DP-06")
    result = evaluate_constraint(case_id="1", trace_df=event_log, constraint=constraint)
    assert result.outcome == ConformanceOutcome.SATISFIED, (
        f"RASS 'No' mental status must satisfy RC-DP-06 (got {result.outcome}, "
        f"reason={result.violation_reason})"
    )

    raw_df_sas = pd.DataFrame([
        _row(2, t0, "ventilator_setting", "ventilator_mode", value_text="CMV"),
        _row(2, t0 + pd.Timedelta(hours=1), "chartevents", 223753, value_num=4, value_text="Calm/Cooperative"),
        _row(2, t0 + pd.Timedelta(hours=2), "ventilator_setting", "ventilator_mode", value_text="SIMV/PSV"),
    ])
    event_log_sas = raw_to_event_log(raw_df_sas)
    result_sas = evaluate_constraint(case_id="2", trace_df=event_log_sas, constraint=constraint)
    assert result_sas.outcome == ConformanceOutcome.SATISFIED, (
        f"SAS=4 mental status must satisfy RC-DP-06 (got {result_sas.outcome}, "
        f"reason={result_sas.violation_reason})"
    )

    print("PASS: test_rc_dp_06_mental_status_rass_or_sas")


def test_rc_dp_01_oxygenation_unconditional_emission():
    t0 = pd.Timestamp("2026-01-01 00:00:00")
    raw_df = pd.DataFrame([
        # Below threshold (< 150): must still emit OxygenationMeasured now that
        # emitter no longer gates on the criterion (checker's oxygenation_ok
        # correlation_condition is sole authority).
        _row(1, t0, "gas", "pao2fio2ratio", value_num=90.0),
    ])
    event_log = raw_to_event_log(raw_df)
    oxy_events = event_log[event_log["activity"] == "OxygenationMeasured"]
    assert len(oxy_events) == 1, (
        "Phase 4 (DP-01): OxygenationMeasured must fire for every PaO2/FiO2 reading "
        f"regardless of threshold, got {len(oxy_events)} events"
    )

    print("PASS: test_rc_dp_01_oxygenation_unconditional_emission")


def test_rc_dp_02_24h_lookback_across_episode_start():
    # pH measured 2h before InvasiveVentilationStarted; SBT starts 4h after.
    # episode_df (>= episode_start) cannot see the pH event; context_df
    # (>= episode_start - 24h) can (Phase 5).
    episode_start = pd.Timestamp("2026-01-01 00:00:00")
    episode_end = pd.Timestamp("2026-01-05 00:00:00")

    def event(activity, ts, itemid=None, value_num=None):
        return {
            "case_id": "case1",
            "activity": activity,
            "timestamp": ts,
            "itemid": itemid,
            "value_raw": None,
            "value_num": value_num,
            "unit": None,
            "attrs": {},
            "patient_id": "p1",
            "stay_id": 1,
        }

    event_log = pd.DataFrame([
        event("pHMeasured", episode_start - pd.Timedelta(hours=2), itemid="ph_bg", value_num=7.35),
        event("InvasiveVentilationStarted", episode_start),
        event("SBTStarted", episode_start + pd.Timedelta(hours=4)),
    ])

    episode_df = event_log[
        (event_log["timestamp"] >= episode_start) & (event_log["timestamp"] < episode_end)
    ]
    context_df = event_log[
        (event_log["timestamp"] >= episode_start - pd.Timedelta(hours=24))
        & (event_log["timestamp"] < episode_end)
    ]

    model = build_readiness_assessment_model()
    constraint = next(c for c in model.constraints if getattr(c, "id", None) == "RC-DP-02")

    result_episode = evaluate_constraint(case_id="case1", trace_df=episode_df, constraint=constraint)
    assert result_episode.outcome == ConformanceOutcome.VIOLATED, (
        "Phase 5 baseline: without look-back, pre-episode pH is invisible "
        f"(got {result_episode.outcome})"
    )

    result_context = evaluate_constraint(case_id="case1", trace_df=context_df, constraint=constraint)
    assert result_context.outcome == ConformanceOutcome.SATISFIED, (
        "Phase 5: 24h pre-episode look-back must surface pH measured before "
        f"InvasiveVentilationStarted (got {result_context.outcome}, reason={result_context.violation_reason})"
    )

    print("PASS: test_rc_dp_02_24h_lookback_across_episode_start")


def test_rc_dp_no_leak_from_prior_episode():
    # Episode 1 has its own SBTStarted near its end. Episode 2 starts 16h
    # later (inside RC-DP-02's 24h pre-window) and has no SBT of its own.
    # The pre-window must supply pH lookback evidence only, not a borrowed
    # activation: episode 2 should be VACUOUS, not SATISFIED/VIOLATED.
    episode1_start = pd.Timestamp("2026-01-01 00:00:00")
    episode1_end = pd.Timestamp("2026-01-01 20:00:00")
    episode2_start = episode1_end
    episode2_end = pd.Timestamp("2026-01-05 00:00:00")

    def event(activity, ts, itemid=None, value_num=None):
        return {
            "case_id": "case1",
            "activity": activity,
            "timestamp": ts,
            "itemid": itemid,
            "value_raw": None,
            "value_num": value_num,
            "unit": None,
            "attrs": {},
            "patient_id": "p1",
            "stay_id": 1,
        }

    event_log = pd.DataFrame([
        event("InvasiveVentilationStarted", episode1_start),
        event("pHMeasured", episode1_start + pd.Timedelta(hours=1), itemid="ph_bg", value_num=7.35),
        event("SBTStarted", episode1_start + pd.Timedelta(hours=2)),
        # episode 2 has no SBTStarted of its own.
    ])

    model = build_readiness_assessment_model()
    constraint = next(c for c in model.constraints if getattr(c, "id", None) == "RC-DP-02")

    unfixed_pre_window_df = event_log[
        (event_log["timestamp"] >= episode2_start - pd.Timedelta(hours=24))
        & (event_log["timestamp"] < episode2_end)
    ]
    result_unfixed = evaluate_constraint(case_id="case1", trace_df=unfixed_pre_window_df, constraint=constraint)
    assert result_unfixed.outcome != ConformanceOutcome.VACUOUS, (
        "sanity check: an unfiltered pre-window must reproduce the leak "
        f"(borrowing episode 1's SBTStarted), got {result_unfixed.outcome}"
    )

    fixed_pre_window_df = unfixed_pre_window_df[
        ~(
            (unfixed_pre_window_df["activity"] == constraint.activation)
            & (unfixed_pre_window_df["timestamp"] < episode2_start)
        )
    ]
    result_fixed = evaluate_constraint(case_id="case1", trace_df=fixed_pre_window_df, constraint=constraint)
    assert result_fixed.outcome == ConformanceOutcome.VACUOUS, (
        "episode 2 has no SBT of its own, so RC-DP-02 must be vacuous once "
        f"episode 1's activation is stripped from the pre-window (got {result_fixed.outcome})"
    )

    print("PASS: test_rc_dp_no_leak_from_prior_episode")


def test_sbt_outcome_single_source_of_truth():
    # Phase 8: two SBT attempts, first fails via re-ventilation. The derived
    # outcome event for attempt 1 (SBTFailed) must precede SBTStarted of
    # attempt 2, and its value_raw must carry the outcome label.
    from derive.activity_emitter import _derive_activities

    t0 = pd.Timestamp("2026-01-01 00:00:00")

    def event(activity, ts):
        return {
            "case_id": "1", "activity": activity, "timestamp": ts,
            "itemid": None, "value_raw": None, "value_num": None, "unit": None,
            "patient_id": "1", "stay_id": 1,
        }

    activity_df = pd.DataFrame([
        event("SBTStarted", t0),
        event("InvasiveVentilationStarted", t0 + pd.Timedelta(hours=2)),  # attempt 1 fails
        event("SBTStarted", t0 + pd.Timedelta(hours=4)),  # attempt 2, no revent
    ])

    derived = pd.concat(_derive_activities(activity_df), ignore_index=True)
    outcomes = derived[derived["activity"].isin(["SBTFailed", "SBTSucceeded"])].sort_values("timestamp")
    assert len(outcomes) == 2, f"expected one outcome per attempt, got {len(outcomes)}"

    attempt1, attempt2 = outcomes.iloc[0], outcomes.iloc[1]
    assert attempt1["activity"] == "SBTFailed" and attempt2["activity"] == "SBTSucceeded", (
        f"expected [SBTFailed, SBTSucceeded], got [{attempt1['activity']}, {attempt2['activity']}]"
    )
    assert attempt1["timestamp"] < (t0 + pd.Timedelta(hours=4)), (
        "Phase 8: attempt 1's outcome event must precede attempt 2's SBTStarted"
    )
    assert attempt1["value_raw"] == "Failure (Reventilated <48h)", (
        f"Phase 8: SBTFailed value_raw must carry the outcome label, got {attempt1['value_raw']!r}"
    )

    print("PASS: test_sbt_outcome_single_source_of_truth")


def test_other_ventilator_rows_do_not_fragment_episode():
    # Phase 7 fix: a peep-only row (classifies "Other", no mode) sandwiched
    # between two Full-Support mode rows must not close/reopen the vent
    # episode. Bug: "Other" rows counted as non-full-support in the
    # start/end transition scan, fragmenting one continuous episode into two.
    from derive.pipeline import _full_support_start_times_from_settings

    t0 = pd.Timestamp("2026-01-01 00:00:00")
    raw_df = pd.DataFrame([
        _row(1, t0, "ventilator_setting", "ventilator_mode", value_text="CMV"),  # Full Support
        _row(1, t0 + pd.Timedelta(hours=1), "ventilator_setting", "peep_vent", value_num=5.0),  # Other
        _row(1, t0 + pd.Timedelta(hours=2), "ventilator_setting", "ventilator_mode", value_text="CMV"),  # Full Support
    ])

    episodes = _full_support_start_times_from_settings(raw_df)
    starts = episodes.get("1", [])
    assert len(starts) == 1, (
        f"Phase 7: peep-only 'Other' row must not fragment one continuous "
        f"Full-Support run into multiple episodes, got {len(starts)}: {starts}"
    )

    print("PASS: test_other_ventilator_rows_do_not_fragment_episode")


def test_int_response_post_episode_lookahead():
    # Bug 3 fix: SBTFailed sits at the episode's last second (revent_ts - 1s),
    # so correcting interventions charted after reintubation land in the next
    # episode. INT-* response rules must see the rule's target activity in a
    # post-episode look-ahead window; the episode-only slice cannot.
    from conformance.rules import build_failure_correction_model

    episode_start = pd.Timestamp("2026-01-01 00:00:00")
    episode_end = pd.Timestamp("2026-01-02 00:00:00")  # reintubation → next episode

    def event(activity, ts):
        return {
            "case_id": "case1",
            "activity": activity,
            "timestamp": ts,
            "itemid": None,
            "value_raw": "Failure" if activity == "SBTFailed" else None,
            "value_num": None,
            "unit": None,
            "attrs": {},
            "patient_id": "p1",
            "stay_id": 1,
        }

    event_log = pd.DataFrame([
        event("InvasiveVentilationStarted", episode_start),
        event("SBTFailed", episode_end - pd.Timedelta(seconds=1)),
        # Charted 2h after reintubation, i.e. in the next episode's slice.
        event("Diuretic_Admin", episode_end + pd.Timedelta(hours=2)),
    ])

    model = build_failure_correction_model()
    constraint = next(c for c in model.constraints if getattr(c, "id", None) == "INT-TR-02")

    episode_df = event_log[
        (event_log["timestamp"] >= episode_start) & (event_log["timestamp"] < episode_end)
    ]
    # Mirrors the look-ahead built in main_per_sbt.py: episode events plus the
    # rule's target activity within 48h after episode_end.
    lookahead = event_log[
        (event_log["timestamp"] >= episode_end)
        & (event_log["timestamp"] < episode_end + pd.Timedelta(hours=48))
        & (event_log["activity"] == constraint.target)
    ]
    lookahead_df = pd.concat([episode_df, lookahead]).sort_values("timestamp")

    result_episode = evaluate_constraint(case_id="case1", trace_df=episode_df, constraint=constraint)
    assert result_episode.outcome == ConformanceOutcome.VIOLATED, (
        "Bug 3 baseline: episode-only slice cannot see post-reintubation "
        f"diuretic (got {result_episode.outcome})"
    )

    result_lookahead = evaluate_constraint(case_id="case1", trace_df=lookahead_df, constraint=constraint)
    assert result_lookahead.outcome == ConformanceOutcome.SATISFIED, (
        "Bug 3 fix: post-episode look-ahead must surface the diuretic given "
        f"after reintubation (got {result_lookahead.outcome}, reason={result_lookahead.violation_reason})"
    )

    print("PASS: test_int_response_post_episode_lookahead")


def test_death_within_48h_turns_success_into_failure():
    """Death <=48h after SBTStarted relabels a success; re-vent failures untouched."""
    start = "2150-01-01 08:00:00"
    censored = "Success (Right-Censored: Stay Ended)"
    revent = "Failure (Reventilated <48h)"

    assert apply_death_rule(censored, start, pd.Timestamp("2150-01-01 20:00")) == DEATH_FAILURE_LABEL
    assert apply_death_rule("Success", start, pd.Timestamp("2150-01-03 08:00")) == DEATH_FAILURE_LABEL  # exactly 48h
    assert apply_death_rule("Success", start, pd.Timestamp("2150-01-03 08:01")) == "Success"  # past window
    assert apply_death_rule("Success", start, None) == "Success"  # survived
    assert apply_death_rule(revent, start, pd.Timestamp("2150-01-01 20:00")) == revent
    assert apply_death_rule("No SBT Attempt", "", pd.Timestamp("2150-01-01 20:00")) == "No SBT Attempt"

    print("PASS: test_death_within_48h_turns_success_into_failure")


def main():
    failures = []
    for test_fn in (
        test_raw_to_event_log_activities,
        test_rc_dp_06_mental_status_rass_or_sas,
        test_rc_dp_01_oxygenation_unconditional_emission,
        test_rc_dp_02_24h_lookback_across_episode_start,
        test_rc_dp_no_leak_from_prior_episode,
        test_sbt_outcome_single_source_of_truth,
        test_other_ventilator_rows_do_not_fragment_episode,
        test_int_response_post_episode_lookahead,
        test_death_within_48h_turns_success_into_failure,
    ):
        try:
            test_fn()
        except AssertionError as exc:
            failures.append((test_fn.__name__, exc))
            print(f"FAIL: {test_fn.__name__}: {exc}")

    if failures:
        print(f"\n{len(failures)} check(s) failed.")
        sys.exit(1)
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
