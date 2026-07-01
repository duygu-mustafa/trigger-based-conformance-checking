"""Explicit finite automata for MP-Declare constraint evaluation.

Each MP-Declare constraint is evaluated by replaying the episode trace over a
finite-state automaton that tracks obligation lifecycle (inactive → pending →
fulfilled/violated).  Data and temporal conditions are implemented as
transition guards; the LAST extension modifies target-selection policy within
the automaton for measurement-heavy rules.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import NamedTuple

import pandas as pd

from conformance.results import ConformanceOutcome, ConstraintResult
from conformance.types import DeclareConstraint, DeclareTemplate


# ─── Core data structures ──────────────────────────────────────────────────────

class AutomatonState(Enum):
    INITIAL = 'initial'
    ACTIVE = 'active'      # at least one pending obligation
    VIOLATED = 'violated'
    TERMINAL = 'terminal'  # all obligations settled, ≥1 fulfilled


class Event(NamedTuple):
    case_id: str
    activity: str
    timestamp: pd.Timestamp
    row_index: int  # DataFrame label index (.name / .loc key)


@dataclass
class Obligation:
    activation_index: int
    activation_ts: pd.Timestamp
    activation_context: dict = field(default_factory=dict)
    last_candidate_index: int | None = None  # LAST target-selection bookkeeping
    is_fulfilled: bool = False
    is_violated: bool = False


# ─── Abstract base ─────────────────────────────────────────────────────────────

class ConstraintAutomaton(ABC):
    """Base class for all MP-Declare constraint automata."""

    def __init__(self, constraint: DeclareConstraint, obs_window: float | None = None) -> None:
        self.constraint = constraint
        self._obs_window = obs_window
        self.state = AutomatonState.INITIAL
        self.num_activations = 0
        self.num_fulfilled = 0
        self.num_violated = 0
        self._first_activation_ts: str | None = None
        self._first_match_target_ts: str | None = None
        self._first_violation_ts: str | None = None
        self._first_corr_error: str | None = None
        self._activation_eval_error: str | None = None
        self._violation_deltas: dict = {}
        self._satisfaction_deltas: dict = {}
        self._delay_seconds: list[float] = []

    @abstractmethod
    def process_event(self, event: Event, trace_df: pd.DataFrame) -> None:
        """Update automaton state for one trace event."""

    @abstractmethod
    def close_trace(self, trace_df: pd.DataFrame) -> None:
        """Settle any open obligations once the trace ends."""

    def _update_state(self) -> None:
        if self.num_violated > 0:
            self.state = AutomatonState.VIOLATED
        elif self.num_activations > 0 and self.num_fulfilled == 0 and self.num_violated == 0:
            self.state = AutomatonState.ACTIVE
        elif self.num_fulfilled > 0:
            self.state = AutomatonState.TERMINAL
        else:
            self.state = AutomatonState.INITIAL

    def _eval_activation_cond(self, event: Event, trace_df: pd.DataFrame) -> bool:
        from conformance.checker import _evaluate_data_condition_status
        if self.constraint.activation_cond is None:
            return True
        row = trace_df.loc[event.row_index]
        ok, is_vac, err, _ = _evaluate_data_condition_status(
            trace_df, row,
            self.constraint.activation_cond.expression,
            activation_ts=event.timestamp,
            observation_window_hours=self._obs_window,
        )
        if err and not self._activation_eval_error:
            self._activation_eval_error = err
        return ok and not is_vac

    def _eval_correlation(
        self,
        trace_df: pd.DataFrame,
        target_row_index: int,
        target_ts: pd.Timestamp,
        activation_ts: pd.Timestamp,
    ) -> tuple[bool, dict]:
        from conformance.checker import _evaluate_data_condition_status
        if self.constraint.correlation_cond is None:
            return True, {}
        row = trace_df.loc[target_row_index]
        ok, is_vac, err, vals = _evaluate_data_condition_status(
            trace_df, row,
            self.constraint.correlation_cond.expression,
            activation_ts=activation_ts,
            target_ts=target_ts,
        )
        if err and not self._first_corr_error:
            self._first_corr_error = err
        return (ok and not is_vac), vals

    def to_result(self, case_id: str, cid: str) -> ConstraintResult:
        if self.num_activations == 0 and self.num_fulfilled == 0:
            outcome = ConformanceOutcome.VACUOUS
        elif self.num_violated > 0:
            outcome = ConformanceOutcome.VIOLATED
        else:
            outcome = ConformanceOutcome.SATISFIED

        error = self._activation_eval_error or self._first_corr_error
        delay = max(self._delay_seconds) if self._delay_seconds else None

        return ConstraintResult(
            case_id=case_id,
            constraint_id=cid,
            outcome=outcome,
            num_activations=self.num_activations,
            num_fulfilled=self.num_fulfilled,
            num_violated=self.num_violated,
            activation_ts=self._first_activation_ts,
            target_ts=self._first_match_target_ts,
            violation_deltas=self._violation_deltas if outcome == ConformanceOutcome.VIOLATED else {},
            satisfaction_deltas=self._satisfaction_deltas if outcome == ConformanceOutcome.SATISFIED else {},
            delay_seconds=delay,
            violation_reason=self._violation_reason(outcome) if error is None else error,
        )

    def _violation_reason(self, outcome: ConformanceOutcome) -> str | None:
        return None if outcome != ConformanceOutcome.VIOLATED else "Constraint violated"


# ─── Unary automaton (EXISTENCE, ABSENCE, AT_MOST_ONE, INIT, END) ─────────────

class UnaryAutomaton(ConstraintAutomaton):
    def __init__(self, constraint: DeclareConstraint, obs_window: float | None = None) -> None:
        super().__init__(constraint, obs_window)
        self._first_event: Event | None = None
        self._last_event: Event | None = None
        self._saw_vacuous = False

    def process_event(self, event: Event, trace_df: pd.DataFrame) -> None:
        from conformance.checker import _evaluate_data_condition_status

        if self._first_event is None:
            self._first_event = event
        self._last_event = event

        tmpl = self.constraint.template

        if tmpl in {DeclareTemplate.INIT, DeclareTemplate.END}:
            return  # handled entirely in close_trace

        if event.activity != self.constraint.activation:
            return

        self.num_activations += 1
        if not self._first_activation_ts:
            self._first_activation_ts = str(event.timestamp)

        if tmpl == DeclareTemplate.EXISTENCE:
            if self.constraint.activation_cond is not None:
                row = trace_df.loc[event.row_index]
                cond_true, is_vac, err, vals = _evaluate_data_condition_status(
                    trace_df, row,
                    self.constraint.activation_cond.expression,
                    observation_window_hours=self._obs_window,
                )
                if err and not self._activation_eval_error:
                    self._activation_eval_error = err
                if is_vac:
                    self._saw_vacuous = True
                    self.num_activations -= 1  # uncounted until close
                    return
                if cond_true:
                    self.num_violated += 1
                    self._violation_deltas = vals
                    if not self._first_violation_ts:
                        self._first_violation_ts = str(event.timestamp)
                else:
                    self.num_fulfilled += 1
                    self._satisfaction_deltas = vals
            else:
                self.num_fulfilled += 1

        elif tmpl == DeclareTemplate.ABSENCE:
            if self.constraint.activation_cond is not None:
                row = trace_df.loc[event.row_index]
                ok, _, err, _ = _evaluate_data_condition_status(
                    trace_df, row, self.constraint.activation_cond.expression,
                    observation_window_hours=self._obs_window,
                )
                if err and not self._activation_eval_error:
                    self._activation_eval_error = err
                if not ok:
                    self.num_activations -= 1
                    return
            self.num_violated += 1
            if not self._first_violation_ts:
                self._first_violation_ts = str(event.timestamp)

        elif tmpl == DeclareTemplate.AT_MOST_ONE:
            pass  # counts handled in close_trace

    def close_trace(self, trace_df: pd.DataFrame) -> None:
        from conformance.checker import _evaluate_data_condition

        tmpl = self.constraint.template

        if tmpl == DeclareTemplate.EXISTENCE:
            # All counting done in process_event; handle vacuous edge case
            if self.num_activations == 0 and self._saw_vacuous:
                # All activation rows were vacuous
                self.num_activations = 0  # stays 0 → VACUOUS via to_result
            elif self.num_violated == 0 and self.num_activations > 0:
                pass  # already counted as fulfilled
            self._update_state()

        elif tmpl == DeclareTemplate.ABSENCE:
            ok = self.num_violated == 0
            self.num_fulfilled = 1 if ok else 0
            self._update_state()

        elif tmpl == DeclareTemplate.AT_MOST_ONE:
            count = self.num_activations
            ok = count <= 1
            self.num_fulfilled = 1 if ok else 0
            self.num_violated = 0 if ok else count - 1
            self._update_state()

        elif tmpl == DeclareTemplate.INIT:
            if self._first_event is None:
                return  # empty trace → VACUOUS
            self.num_activations = 1
            self._first_activation_ts = str(self._first_event.timestamp)
            ok = self._first_event.activity == self.constraint.activation
            if ok and self.constraint.activation_cond is not None:
                row = trace_df.loc[self._first_event.row_index]
                ok, err, vals = _evaluate_data_condition(
                    trace_df, row, self.constraint.activation_cond.expression,
                    observation_window_hours=self._obs_window,
                )
                if err:
                    self._activation_eval_error = err
                if not ok:
                    self._violation_deltas = vals
                else:
                    self._satisfaction_deltas = vals
            self.num_fulfilled = 1 if ok else 0
            self.num_violated = 0 if ok else 1
            self._update_state()

        elif tmpl == DeclareTemplate.END:
            if self._last_event is None:
                return
            self.num_activations = 1
            self._first_activation_ts = str(self._last_event.timestamp)
            ok = self._last_event.activity == self.constraint.activation
            if ok and self.constraint.activation_cond is not None:
                row = trace_df.loc[self._last_event.row_index]
                ok, err, vals = _evaluate_data_condition(
                    trace_df, row, self.constraint.activation_cond.expression,
                    observation_window_hours=self._obs_window,
                )
                if err:
                    self._activation_eval_error = err
                if not ok:
                    self._violation_deltas = vals
                else:
                    self._satisfaction_deltas = vals
            self.num_fulfilled = 1 if ok else 0
            self.num_violated = 0 if ok else 1
            self._update_state()

    def _violation_reason(self, outcome: ConformanceOutcome) -> str | None:
        if outcome != ConformanceOutcome.VIOLATED:
            return None
        tmpl = self.constraint.template
        if tmpl == DeclareTemplate.EXISTENCE:
            return "Activation condition evaluated to true for one or more events"
        if tmpl == DeclareTemplate.ABSENCE:
            return "Forbidden activity occurred"
        if tmpl == DeclareTemplate.AT_MOST_ONE:
            return "Activity must occur at most once"
        if tmpl == DeclareTemplate.INIT:
            return "First event does not satisfy INIT"
        if tmpl == DeclareTemplate.END:
            return "Last event does not satisfy END"
        return "Constraint violated"

    def to_result(self, case_id: str, cid: str) -> ConstraintResult:
        # EXISTENCE vacuous edge case: all rows vacuous
        if self.constraint.template == DeclareTemplate.EXISTENCE and self.num_activations == 0 and self._saw_vacuous:
            return ConstraintResult(
                case_id=case_id, constraint_id=cid,
                outcome=ConformanceOutcome.VACUOUS,
                num_activations=0, num_fulfilled=0, num_violated=0,
                activation_ts=self._first_activation_ts,
                violation_reason=self._activation_eval_error or "No data in observation window",
            )
        return super().to_result(case_id, cid)


# ─── Response automaton ────────────────────────────────────────────────────────

_RESPONSE_TEMPLATES = {
    DeclareTemplate.RESPONSE,
    DeclareTemplate.ALTERNATE_RESPONSE,
    DeclareTemplate.CHAIN_RESPONSE,
    DeclareTemplate.NOT_RESPONSE,
    DeclareTemplate.NOT_CHAIN_RESPONSE,
    DeclareTemplate.NOT_SUCCESSION,
}

_NEGATIVE_RESPONSE = {
    DeclareTemplate.NOT_RESPONSE,
    DeclareTemplate.NOT_CHAIN_RESPONSE,
    DeclareTemplate.NOT_SUCCESSION,
}


class ResponseAutomaton(ConstraintAutomaton):
    """Handles RESPONSE, ALTERNATE_RESPONSE, CHAIN_RESPONSE and their negatives."""

    def __init__(self, constraint: DeclareConstraint, obs_window: float | None = None) -> None:
        super().__init__(constraint, obs_window)
        self._is_chain = constraint.template in {
            DeclareTemplate.CHAIN_RESPONSE, DeclareTemplate.NOT_CHAIN_RESPONSE
        }
        self._is_alternate = constraint.template == DeclareTemplate.ALTERNATE_RESPONSE
        self._is_negative = constraint.template in _NEGATIVE_RESPONSE
        self._obligations: list[Obligation] = []
        self._chain_pending_obl: Obligation | None = None  # open chain obligation
        self._last_delay: float | None = None

    def process_event(self, event: Event, trace_df: pd.DataFrame) -> None:
        from conformance.checker import _within_time_window

        # ── CHAIN variant ────────────────────────────────────────────────────
        if self._is_chain:
            if self._chain_pending_obl is not None:
                obl = self._chain_pending_obl
                delta = (event.timestamp - obl.activation_ts).total_seconds()
                matches = (
                    event.activity == self.constraint.target
                    and delta > 0
                    and _within_time_window(delta, self.constraint)
                )
                if matches and self.constraint.correlation_cond:
                    corr_ok, corr_vals = self._eval_correlation(
                        trace_df, event.row_index, event.timestamp, obl.activation_ts
                    )
                    matches = corr_ok
                    if matches:
                        self._last_delay = delta
                        self._satisfaction_deltas = corr_vals
                elif matches:
                    self._last_delay = delta

                if matches and not self._is_negative:
                    obl.is_fulfilled = True
                    self.num_fulfilled += 1
                    if self._last_delay is not None:
                        self._delay_seconds.append(self._last_delay)
                    if not self._first_match_target_ts:
                        self._first_match_target_ts = str(event.timestamp)
                elif not matches and self._is_negative:
                    obl.is_fulfilled = True
                    self.num_fulfilled += 1
                elif matches and self._is_negative:
                    obl.is_violated = True
                    self.num_violated += 1
                    if not self._first_violation_ts:
                        self._first_violation_ts = str(obl.activation_ts)
                    if self._last_delay is not None:
                        self._delay_seconds.append(self._last_delay)
                else:  # not matches and not negative
                    obl.is_violated = True
                    self.num_violated += 1
                    if not self._first_violation_ts:
                        self._first_violation_ts = str(obl.activation_ts)
                self._chain_pending_obl = None

            if event.activity == self.constraint.activation:
                if self._eval_activation_cond(event, trace_df):
                    obl = Obligation(activation_index=event.row_index, activation_ts=event.timestamp)
                    self._obligations.append(obl)
                    self._chain_pending_obl = obl
                    self.num_activations += 1
                    if not self._first_activation_ts:
                        self._first_activation_ts = str(event.timestamp)
            self._update_state()
            return

        # ── Non-chain: process target ─────────────────────────────────────────
        if event.activity == self.constraint.target:
            from conformance.checker import _within_time_window
            for obl in self._obligations:
                if obl.is_fulfilled or obl.is_violated:
                    continue
                delta = (event.timestamp - obl.activation_ts).total_seconds()
                if delta <= 0:
                    continue
                if not _within_time_window(delta, self.constraint):
                    continue
                corr_ok, corr_vals = self._eval_correlation(
                    trace_df, event.row_index, event.timestamp, obl.activation_ts
                )
                if not corr_ok:
                    continue

                if self.constraint.target_selection == 'last':
                    obl.last_candidate_index = event.row_index
                    continue  # defer to close_trace

                if not self._is_negative:
                    obl.is_fulfilled = True
                    self.num_fulfilled += 1
                    self._delay_seconds.append(delta)
                    if not self._first_match_target_ts:
                        self._first_match_target_ts = str(event.timestamp)
                    self._satisfaction_deltas = corr_vals
                else:
                    obl.is_violated = True
                    self.num_violated += 1
                    if not self._first_violation_ts:
                        self._first_violation_ts = str(obl.activation_ts)
                    self._violation_deltas = corr_vals
                    self._delay_seconds.append(delta)
                break  # stop at first matching target per obligation

        # ── Non-chain: process activation ─────────────────────────────────────
        if event.activity == self.constraint.activation:
            if self._is_alternate:
                # New A before B: violate any open obligations (for positive)
                for obl in self._obligations:
                    if not obl.is_fulfilled and not obl.is_violated:
                        if not self._is_negative:
                            obl.is_violated = True
                            self.num_violated += 1
                            if not self._first_violation_ts:
                                self._first_violation_ts = str(obl.activation_ts)
                        else:
                            obl.is_fulfilled = True
                            self.num_fulfilled += 1

            if self._eval_activation_cond(event, trace_df):
                obl = Obligation(activation_index=event.row_index, activation_ts=event.timestamp)
                self._obligations.append(obl)
                self.num_activations += 1
                if not self._first_activation_ts:
                    self._first_activation_ts = str(event.timestamp)

        self._update_state()

    def close_trace(self, trace_df: pd.DataFrame) -> None:
        from conformance.checker import _within_time_window, _evaluate_data_condition_status

        # Settle remaining chain obligation (last event was an activation)
        if self._is_chain and self._chain_pending_obl is not None:
            obl = self._chain_pending_obl
            if not obl.is_fulfilled and not obl.is_violated:
                if not self._is_negative:
                    obl.is_violated = True
                    self.num_violated += 1
                    if not self._first_violation_ts:
                        self._first_violation_ts = str(obl.activation_ts)
                else:
                    obl.is_fulfilled = True
                    self.num_fulfilled += 1
            self._chain_pending_obl = None

        for obl in self._obligations:
            if obl.is_fulfilled or obl.is_violated:
                continue

            if self.constraint.target_selection == 'last':
                if obl.last_candidate_index is None:
                    if not self._is_negative:
                        obl.is_violated = True
                        self.num_violated += 1
                        if not self._first_violation_ts:
                            self._first_violation_ts = str(obl.activation_ts)
                    else:
                        obl.is_fulfilled = True
                        self.num_fulfilled += 1
                    continue

                row = trace_df.loc[obl.last_candidate_index]
                delta = (row['timestamp'] - obl.activation_ts).total_seconds()
                if delta <= 0 or not _within_time_window(delta, self.constraint):
                    if not self._is_negative:
                        obl.is_violated = True
                        self.num_violated += 1
                        if not self._first_violation_ts:
                            self._first_violation_ts = str(obl.activation_ts)
                    else:
                        obl.is_fulfilled = True
                        self.num_fulfilled += 1
                    continue

                corr_ok, corr_vals = self._eval_correlation(
                    trace_df, obl.last_candidate_index, row['timestamp'], obl.activation_ts
                )
                if corr_ok and not self._is_negative:
                    obl.is_fulfilled = True
                    self.num_fulfilled += 1
                    self._delay_seconds.append(delta)
                    if not self._first_match_target_ts:
                        self._first_match_target_ts = str(row['timestamp'])
                    self._satisfaction_deltas = corr_vals
                elif not corr_ok and self._is_negative:
                    obl.is_fulfilled = True
                    self.num_fulfilled += 1
                elif corr_ok and self._is_negative:
                    obl.is_violated = True
                    self.num_violated += 1
                    if not self._first_violation_ts:
                        self._first_violation_ts = str(obl.activation_ts)
                    self._violation_deltas = corr_vals
                    self._delay_seconds.append(delta)
                else:
                    obl.is_violated = True
                    self.num_violated += 1
                    if not self._first_violation_ts:
                        self._first_violation_ts = str(obl.activation_ts)
            else:
                # ANY target selection: unfulfilled at end
                if not self._is_negative:
                    obl.is_violated = True
                    self.num_violated += 1
                    if not self._first_violation_ts:
                        self._first_violation_ts = str(obl.activation_ts)
                else:
                    obl.is_fulfilled = True
                    self.num_fulfilled += 1

        self._update_state()

    def _violation_reason(self, outcome: ConformanceOutcome) -> str | None:
        if outcome != ConformanceOutcome.VIOLATED:
            return None
        if self.constraint.template in {
            DeclareTemplate.RESPONSE,
            DeclareTemplate.ALTERNATE_RESPONSE,
            DeclareTemplate.CHAIN_RESPONSE,
        }:
            return "One or more activations violate response ordering"
        return "Forbidden response pattern detected"

    def to_result(self, case_id: str, cid: str) -> ConstraintResult:
        r = super().to_result(case_id, cid)
        # Override activation_ts: prefer first_activation_ts, fallback to first_violation_ts
        r.activation_ts = self._first_activation_ts or self._first_violation_ts
        return r


# ─── Precedence automaton ──────────────────────────────────────────────────────

_PRECEDENCE_TEMPLATES = {
    DeclareTemplate.PRECEDENCE,
    DeclareTemplate.ALTERNATE_PRECEDENCE,
    DeclareTemplate.CHAIN_PRECEDENCE,
    DeclareTemplate.NOT_PRECEDENCE,
    DeclareTemplate.NOT_CHAIN_PRECEDENCE,
}

_NEGATIVE_PRECEDENCE = {
    DeclareTemplate.NOT_PRECEDENCE,
    DeclareTemplate.NOT_CHAIN_PRECEDENCE,
}


class PrecedenceAutomaton(ConstraintAutomaton):
    """Handles PRECEDENCE, ALTERNATE_PRECEDENCE, CHAIN_PRECEDENCE and their negatives.

    constraint.activation = B (the triggered activity that requires a precondition)
    constraint.target     = A (the precondition activity that must have occurred before B)
    """

    def __init__(self, constraint: DeclareConstraint, obs_window: float | None = None) -> None:
        super().__init__(constraint, obs_window)
        self._is_chain = constraint.template in {
            DeclareTemplate.CHAIN_PRECEDENCE, DeclareTemplate.NOT_CHAIN_PRECEDENCE
        }
        self._is_alternate = constraint.template == DeclareTemplate.ALTERNATE_PRECEDENCE
        self._is_negative = constraint.template in _NEGATIVE_PRECEDENCE
        self._seen_targets: list[Event] = []   # accumulates A events seen so far
        self._prev_event: Event | None = None
        self._last_b_ts: pd.Timestamp | None = None  # for ALTERNATE: last B timestamp
        self._first_match_activation_ts: str | None = None

    def process_event(self, event: Event, trace_df: pd.DataFrame) -> None:
        from conformance.checker import _within_time_window

        # Track all target (A) events seen so far
        if event.activity == self.constraint.target:
            self._seen_targets.append(event)

        # Process activation (B) events
        if event.activity == self.constraint.activation:
            if not self._eval_activation_cond(event, trace_df):
                self._prev_event = event
                return

            self.num_activations += 1
            if not self._first_activation_ts:
                self._first_activation_ts = str(event.timestamp)

            candidates: list[Event]
            if self._is_chain:
                # Immediately preceding event must be A
                if (self._prev_event is not None
                        and self._prev_event.activity == self.constraint.target):
                    candidates = [self._prev_event]
                else:
                    candidates = []
            elif self._is_alternate:
                # A must be between previous B and current B
                after_ts = self._last_b_ts
                candidates = [
                    t for t in self._seen_targets
                    if t.timestamp < event.timestamp
                    and (after_ts is None or t.timestamp > after_ts)
                ]
            else:
                candidates = [t for t in self._seen_targets if t.timestamp < event.timestamp]

            # target_selection='last': only evaluate the latest candidate
            if getattr(self.constraint, 'target_selection', None) == 'last' and candidates:
                candidates = [max(candidates, key=lambda e: e.timestamp)]

            matched = False
            match_vals: dict = {}
            match_delta: float | None = None
            for cand in candidates:
                # delta = target_ts - activation_ts (negative for Precedence, as in original)
                delta = (cand.timestamp - event.timestamp).total_seconds()
                if not _within_time_window(delta, self.constraint):
                    continue
                corr_ok, corr_vals = self._eval_correlation(
                    trace_df, cand.row_index, cand.timestamp, event.timestamp
                )
                if corr_ok:
                    matched = True
                    match_vals = corr_vals
                    match_delta = delta
                    if not self._first_match_activation_ts:
                        self._first_match_activation_ts = str(event.timestamp)
                    if not self._first_match_target_ts:
                        self._first_match_target_ts = str(cand.timestamp)
                    break

            if (matched and not self._is_negative) or (not matched and self._is_negative):
                self.num_fulfilled += 1
                if matched:
                    self._satisfaction_deltas = match_vals
            else:
                self.num_violated += 1
                if not self._first_violation_ts:
                    self._first_violation_ts = str(event.timestamp)
                if matched and self._is_negative:
                    self._violation_deltas = match_vals
                    if match_delta is not None:
                        self._delay_seconds.append(abs(match_delta))

            if self._is_alternate:
                self._last_b_ts = event.timestamp

        self._prev_event = event
        self._update_state()

    def close_trace(self, trace_df: pd.DataFrame) -> None:
        self._update_state()

    def _violation_reason(self, outcome: ConformanceOutcome) -> str | None:
        if outcome != ConformanceOutcome.VIOLATED:
            return None
        if self.constraint.template in {
            DeclareTemplate.PRECEDENCE,
            DeclareTemplate.ALTERNATE_PRECEDENCE,
            DeclareTemplate.CHAIN_PRECEDENCE,
        }:
            return "Precedence relation violated"
        return "Forbidden precedence relation detected"

    def to_result(self, case_id: str, cid: str) -> ConstraintResult:
        r = super().to_result(case_id, cid)
        # Precedence reports activation_ts as first matched B, target_ts as first matched A or first violation
        r.activation_ts = self._first_match_activation_ts
        r.target_ts = self._first_match_target_ts or self._first_violation_ts
        return r


# ─── Responded-existence automaton ────────────────────────────────────────────

class RespondedExistenceAutomaton(ConstraintAutomaton):
    """Handles RESPONDED_EXISTENCE and NOT_RESPONDED_EXISTENCE.

    B can appear anywhere (before or after A); no time-window constraint.
    """

    def __init__(self, constraint: DeclareConstraint, obs_window: float | None = None) -> None:
        super().__init__(constraint, obs_window)
        self._is_negative = constraint.template == DeclareTemplate.NOT_RESPONDED_EXISTENCE
        self._obligations: list[Obligation] = []
        self._seen_targets: list[Event] = []

    def process_event(self, event: Event, trace_df: pd.DataFrame) -> None:
        if event.activity == self.constraint.target:
            self._seen_targets.append(event)

        if event.activity == self.constraint.activation:
            if self._eval_activation_cond(event, trace_df):
                obl = Obligation(activation_index=event.row_index, activation_ts=event.timestamp)
                self._obligations.append(obl)
                self.num_activations += 1
                if not self._first_activation_ts:
                    self._first_activation_ts = str(event.timestamp)

    def close_trace(self, trace_df: pd.DataFrame) -> None:
        from conformance.checker import _within_time_window

        for obl in self._obligations:
            matched = False
            match_vals: dict = {}
            for tgt in self._seen_targets:
                # No directional or time-window requirement for responded existence
                corr_ok, corr_vals = self._eval_correlation(
                    trace_df, tgt.row_index, tgt.timestamp, obl.activation_ts
                )
                if corr_ok:
                    matched = True
                    match_vals = corr_vals
                    if not self._first_match_target_ts:
                        self._first_match_target_ts = str(tgt.timestamp)
                    break

            if (matched and not self._is_negative) or (not matched and self._is_negative):
                obl.is_fulfilled = True
                self.num_fulfilled += 1
                if matched:
                    self._satisfaction_deltas = match_vals
            else:
                obl.is_violated = True
                self.num_violated += 1
                if not self._first_violation_ts:
                    self._first_violation_ts = str(obl.activation_ts)
                if matched and self._is_negative:
                    self._violation_deltas = match_vals

        self._update_state()

    def _violation_reason(self, outcome: ConformanceOutcome) -> str | None:
        if outcome != ConformanceOutcome.VIOLATED:
            return None
        if not self._is_negative:
            return "Target activity missing for responded existence"
        return "Forbidden co-occurrence found for not responded existence"

    def to_result(self, case_id: str, cid: str) -> ConstraintResult:
        r = super().to_result(case_id, cid)
        r.activation_ts = self._first_activation_ts or self._first_violation_ts
        return r


# ─── Co-existence automaton ────────────────────────────────────────────────────

class CoExistenceAutomaton(ConstraintAutomaton):
    """Handles CO_EXISTENCE and NOT_CO_EXISTENCE."""

    def __init__(self, constraint: DeclareConstraint, obs_window: float | None = None) -> None:
        super().__init__(constraint, obs_window)
        self._is_negative = constraint.template == DeclareTemplate.NOT_CO_EXISTENCE
        self._saw_activation = False
        self._saw_target = False
        self._activation_ts_str: str | None = None
        self._target_ts_str: str | None = None
        self._last_corr_vals: dict = {}

    def process_event(self, event: Event, trace_df: pd.DataFrame) -> None:
        if event.activity == self.constraint.activation:
            if self._eval_activation_cond(event, trace_df):
                self._saw_activation = True
                if not self._activation_ts_str:
                    self._activation_ts_str = str(event.timestamp)

        if event.activity == self.constraint.target:
            if self.constraint.correlation_cond:
                corr_ok, corr_vals = self._eval_correlation(
                    trace_df, event.row_index, event.timestamp, event.timestamp
                )
                if corr_ok:
                    self._saw_target = True
                    self._last_corr_vals = corr_vals
                    if not self._target_ts_str:
                        self._target_ts_str = str(event.timestamp)
            else:
                self._saw_target = True
                if not self._target_ts_str:
                    self._target_ts_str = str(event.timestamp)

    def close_trace(self, trace_df: pd.DataFrame) -> None:
        if self.constraint.template == DeclareTemplate.CO_EXISTENCE:
            both = self._saw_activation and self._saw_target
            neither = not self._saw_activation and not self._saw_target
            ok = both or neither
            self.num_activations = 1 if self._saw_activation else 0
            self.num_fulfilled = 1 if ok else 0
            self.num_violated = 0 if ok else 1
            if not ok and self._saw_activation:
                self._first_violation_ts = self._activation_ts_str
        else:  # NOT_CO_EXISTENCE
            violated = self._saw_activation and self._saw_target
            self.num_activations = 1 if self._saw_activation else 0
            self.num_fulfilled = 0 if violated else self.num_activations
            self.num_violated = self.num_activations if violated else 0
            if violated:
                self._first_violation_ts = self._activation_ts_str
                self._violation_deltas = self._last_corr_vals
        self._update_state()

    def _violation_reason(self, outcome: ConformanceOutcome) -> str | None:
        if outcome != ConformanceOutcome.VIOLATED:
            return None
        if self.constraint.template == DeclareTemplate.CO_EXISTENCE:
            return "Co-existence requires both activities or neither"
        return "Both activities co-exist in trace"

    def to_result(self, case_id: str, cid: str) -> ConstraintResult:
        r = super().to_result(case_id, cid)
        r.activation_ts = self._activation_ts_str
        r.target_ts = self._target_ts_str
        return r


# ─── Succession automaton ──────────────────────────────────────────────────────

_SUCCESSION_MAP = {
    DeclareTemplate.SUCCESSION: (DeclareTemplate.RESPONSE, DeclareTemplate.PRECEDENCE),
    DeclareTemplate.ALTERNATE_SUCCESSION: (
        DeclareTemplate.ALTERNATE_RESPONSE, DeclareTemplate.ALTERNATE_PRECEDENCE
    ),
    DeclareTemplate.CHAIN_SUCCESSION: (
        DeclareTemplate.CHAIN_RESPONSE, DeclareTemplate.CHAIN_PRECEDENCE
    ),
    DeclareTemplate.NOT_CHAIN_SUCCESSION: (
        DeclareTemplate.NOT_CHAIN_RESPONSE, DeclareTemplate.NOT_CHAIN_PRECEDENCE
    ),
}


class SuccessionAutomaton(ConstraintAutomaton):
    """Composes a ResponseAutomaton and a PrecedenceAutomaton."""

    def __init__(self, constraint: DeclareConstraint, obs_window: float | None = None) -> None:
        super().__init__(constraint, obs_window)
        resp_t, prec_t = _SUCCESSION_MAP[constraint.template]
        from dataclasses import replace as _dc_replace

        def _sub(tmpl: DeclareTemplate) -> DeclareConstraint:
            return DeclareConstraint(
                template=tmpl,
                activation=constraint.activation,
                target=constraint.target,
                activation_cond=constraint.activation_cond,
                correlation_cond=constraint.correlation_cond,
                time_condition=constraint.time_condition,
                label=f"{constraint.label}::{tmpl.value}",
            )

        self._resp = ResponseAutomaton(_sub(resp_t), obs_window)
        self._prec = PrecedenceAutomaton(_sub(prec_t), obs_window)

    def process_event(self, event: Event, trace_df: pd.DataFrame) -> None:
        self._resp.process_event(event, trace_df)
        self._prec.process_event(event, trace_df)

    def close_trace(self, trace_df: pd.DataFrame) -> None:
        self._resp.close_trace(trace_df)
        self._prec.close_trace(trace_df)
        # Merge counters
        self.num_activations = max(self._resp.num_activations, self._prec.num_activations)
        self.num_fulfilled = min(self._resp.num_fulfilled, self._prec.num_fulfilled)
        self.num_violated = self._resp.num_violated + self._prec.num_violated
        self._update_state()

    def _violation_reason(self, outcome: ConformanceOutcome) -> str | None:
        if outcome != ConformanceOutcome.VIOLATED:
            return None
        return (
            self._resp._violation_reason(outcome)
            or self._prec._violation_reason(outcome)
            or "Succession relation violated"
        )

    def to_result(self, case_id: str, cid: str) -> ConstraintResult:
        r_r = self._resp.to_result(case_id, cid)
        r_p = self._prec.to_result(case_id, cid)

        if (r_r.outcome == ConformanceOutcome.VACUOUS
                and r_p.outcome == ConformanceOutcome.VACUOUS):
            outcome = ConformanceOutcome.VACUOUS
        elif (r_r.outcome == ConformanceOutcome.VIOLATED
              or r_p.outcome == ConformanceOutcome.VIOLATED):
            outcome = ConformanceOutcome.VIOLATED
        else:
            outcome = ConformanceOutcome.SATISFIED

        error = r_r.violation_reason if r_r.outcome == ConformanceOutcome.VIOLATED else None
        if error is None and r_p.outcome == ConformanceOutcome.VIOLATED:
            error = r_p.violation_reason
        if error is None and outcome == ConformanceOutcome.VIOLATED:
            error = "Succession relation violated"

        return ConstraintResult(
            case_id=case_id,
            constraint_id=cid,
            outcome=outcome,
            num_activations=max(r_r.num_activations, r_p.num_activations),
            num_fulfilled=min(r_r.num_fulfilled, r_p.num_fulfilled),
            num_violated=r_r.num_violated + r_p.num_violated,
            activation_ts=r_r.activation_ts or r_p.activation_ts,
            target_ts=r_r.target_ts or r_p.target_ts,
            violation_deltas=(r_r.violation_deltas or r_p.violation_deltas)
            if outcome == ConformanceOutcome.VIOLATED else {},
            delay_seconds=(r_r.delay_seconds or r_p.delay_seconds)
            if outcome == ConformanceOutcome.VIOLATED else None,
            violation_reason=error if outcome == ConformanceOutcome.VIOLATED else None,
        )


# ─── Factory ───────────────────────────────────────────────────────────────────

def build_automaton_for_constraint(
    constraint: DeclareConstraint,
    obs_window: float | None = None,
) -> ConstraintAutomaton:
    """Return the appropriate automaton instance for the given constraint."""
    tmpl = constraint.template

    if tmpl in {
        DeclareTemplate.EXISTENCE, DeclareTemplate.ABSENCE,
        DeclareTemplate.AT_MOST_ONE, DeclareTemplate.INIT, DeclareTemplate.END,
    }:
        return UnaryAutomaton(constraint, obs_window)

    if tmpl in _RESPONSE_TEMPLATES:
        return ResponseAutomaton(constraint, obs_window)

    if tmpl in _PRECEDENCE_TEMPLATES:
        return PrecedenceAutomaton(constraint, obs_window)

    if tmpl in {DeclareTemplate.RESPONDED_EXISTENCE, DeclareTemplate.NOT_RESPONDED_EXISTENCE}:
        return RespondedExistenceAutomaton(constraint, obs_window)

    if tmpl in {DeclareTemplate.CO_EXISTENCE, DeclareTemplate.NOT_CO_EXISTENCE}:
        return CoExistenceAutomaton(constraint, obs_window)

    if tmpl in _SUCCESSION_MAP:
        return SuccessionAutomaton(constraint, obs_window)

    raise ValueError(f"No automaton defined for template: {tmpl.value}")
