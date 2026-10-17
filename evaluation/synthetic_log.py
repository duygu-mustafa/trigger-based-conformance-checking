"""Synthetic event logs with planted ground truth.

The RTFM log and MIMIC-IV both answer the question "does the pipeline run and
produce interpretable output". Neither can answer "is the output *correct*",
because neither carries a recorded truth against which a verdict could be
checked, and neither exercises the multi-episode case (RTFM's ``Create Fine``
occurs exactly once per case). This module generates logs where both are known
by construction:

* :data:`CORRECTNESS_CASES` — hand-written micro-traces, one per template and
  variant, each paired with the verdict that
  :cref:`def:fulfillment_violation` prescribes. Feeds SE1.
* :func:`generate_log` — a stochastic multi-episode log whose per-episode
  verdicts *and* per-episode outcomes are planted, the latter at prescribed
  risk ratios. Feeds SE2 (episode-scoped vs. case-scoped checking) and SE3
  (recovery of a known association).

The activity alphabet is deliberately abstract (``T``, ``A``, ``B``, ...): a
ground truth is only as trustworthy as it is easy to read off the trace, and
domain labels would invite the reader to reason about process semantics that
the generator does not claim to model.

Verdict semantics follow the activation-based definition of the thesis: an
activation instance is an event matching the activation label whose payload
satisfies the activation condition; the trace satisfies a constraint iff no
activation instance is a violation, and satisfies it *vacuously* iff it
contains no activation instance at all.

Logs use the wide schema the checker's XES path expects — ``case_id``,
``activity``, ``timestamp`` plus per-event attribute columns, and no ``itemid``
column, so a data condition reads the attributes of the event it is evaluated
on.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from conformance.results import ConformanceOutcome  # noqa: E402
from conformance.types import (  # noqa: E402
    DataCondition,
    DeclareConstraint,
    DeclareModel,
    DeclareTemplate,
    TimeCondition,
)

BASE_TS = pd.Timestamp("2024-01-01 00:00:00")
MINUTE = pd.Timedelta(minutes=1)
HOUR = pd.Timedelta(hours=1)
DAY = pd.Timedelta(days=1)

TRIGGER = "T"


# ---------------------------------------------------------------------------
# Trace construction
# ---------------------------------------------------------------------------

def make_trace(
    events: list[tuple],
    case_id: str = "c1",
    base_ts: pd.Timestamp = BASE_TS,
) -> pd.DataFrame:
    """Build a wide-schema trace from ``(activity, offset_minutes[, attrs])`` tuples.

    ``attrs`` is an optional dict of per-event attribute values; the union of
    all attribute keys becomes the log's attribute columns, absent values NaN.
    """
    rows = []
    for event in events:
        activity, offset = event[0], event[1]
        attrs = event[2] if len(event) > 2 else {}
        row = {
            "case_id": case_id,
            "activity": activity,
            "timestamp": base_ts + offset * MINUTE,
        }
        row.update(attrs)
        rows.append(row)
    return pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)


# ---------------------------------------------------------------------------
# SE1: per-template correctness catalogue
# ---------------------------------------------------------------------------

@dataclass
class CorrectnessCase:
    """One micro-trace with the verdict the semantics prescribe.

    ``note`` is set where the expectation is contested rather than obvious —
    those cases are reported apart from the plain ones, since a mismatch there
    is a semantic choice to document, not necessarily a defect to fix.
    """

    case_id: str
    constraint: DeclareConstraint
    events: list[tuple]
    expected: ConformanceOutcome
    note: str | None = None

    @property
    def template(self) -> str:
        return self.constraint.template.value

    def trace(self) -> pd.DataFrame:
        return make_trace(self.events, case_id=self.case_id)


def _c(template: DeclareTemplate, activation: str, target: str | None = None, **kwargs) -> DeclareConstraint:
    return DeclareConstraint(template=template, activation=activation, target=target, **kwargs)


SAT = ConformanceOutcome.SATISFIED
VIO = ConformanceOutcome.VIOLATED
VAC = ConformanceOutcome.VACUOUS

_NON_ACTIVATION_NOTE = (
    "Non-activation of a negative or counting template: the definition calls this "
    "vacuous, an implementation may defensibly call it satisfied"
)


def _build_correctness_cases() -> list[CorrectnessCase]:
    cases: list[CorrectnessCase] = []

    def add(cid, constraint, events, expected, note=None):
        cases.append(CorrectnessCase(cid, constraint, events, expected, note))

    # --- unary templates ---------------------------------------------------
    ex = _c(DeclareTemplate.EXISTENCE, "A")
    add("EXI-sat", ex, [("X", 0), ("A", 1)], SAT)
    add("EXI-vio", ex, [("X", 0), ("B", 1)], VIO)  # activated by the trace start

    ab = _c(DeclareTemplate.ABSENCE, "A")
    add("ABS-vio", ab, [("X", 0), ("A", 1)], VIO)
    add("ABS-vac", ab, [("X", 0), ("B", 1)], VAC, _NON_ACTIVATION_NOTE)

    amo = _c(DeclareTemplate.AT_MOST_ONE, "A")
    add("AMO-sat", amo, [("A", 0), ("X", 1)], SAT)
    add("AMO-vio", amo, [("A", 0), ("X", 1), ("A", 2)], VIO)
    add("AMO-vac", amo, [("X", 0), ("B", 1)], VAC, _NON_ACTIVATION_NOTE)

    ini = _c(DeclareTemplate.INIT, "A")
    add("INI-sat", ini, [("A", 0), ("B", 1)], SAT)
    add("INI-vio", ini, [("B", 0), ("A", 1)], VIO)

    end = _c(DeclareTemplate.END, "A")
    add("END-sat", end, [("B", 0), ("A", 1)], SAT)
    add("END-vio", end, [("A", 0), ("B", 1)], VIO)

    # --- response family ---------------------------------------------------
    resp = _c(DeclareTemplate.RESPONSE, "A", "B")
    add("RES-sat", resp, [("A", 0), ("B", 1)], SAT)
    add("RES-vio", resp, [("A", 0), ("X", 1)], VIO)
    add("RES-vac", resp, [("X", 0), ("B", 1)], VAC)
    add("RES-order", resp, [("B", 0), ("A", 1)], VIO)  # target must follow, not precede
    add("RES-multi-mixed", resp, [("A", 0), ("B", 1), ("A", 2), ("X", 3)], VIO)  # one of two activations fails
    add("RES-multi-ok", resp, [("A", 0), ("B", 1), ("A", 2), ("B", 3)], SAT)

    altres = _c(DeclareTemplate.ALTERNATE_RESPONSE, "A", "B")
    add("ALTRES-sat", altres, [("A", 0), ("B", 1), ("A", 2), ("B", 3)], SAT)
    add("ALTRES-vio", altres, [("A", 0), ("A", 1), ("B", 2)], VIO)  # second A before B answers the first

    chres = _c(DeclareTemplate.CHAIN_RESPONSE, "A", "B")
    add("CHRES-sat", chres, [("A", 0), ("B", 1)], SAT)
    add("CHRES-vio", chres, [("A", 0), ("X", 1), ("B", 2)], VIO)  # B follows, but not immediately

    # --- responded existence ----------------------------------------------
    rexi = _c(DeclareTemplate.RESPONDED_EXISTENCE, "A", "B")
    add("REXI-sat-after", rexi, [("A", 0), ("B", 1)], SAT)
    add("REXI-sat-before", rexi, [("B", 0), ("A", 1)], SAT)  # order irrelevant
    add("REXI-vio", rexi, [("A", 0), ("X", 1)], VIO)

    # --- precedence family -------------------------------------------------
    prec = _c(DeclareTemplate.PRECEDENCE, "B", "A")  # B may occur only after A
    add("PRE-sat", prec, [("A", 0), ("B", 1)], SAT)
    add("PRE-vio", prec, [("X", 0), ("B", 1)], VIO)
    add("PRE-vac", prec, [("A", 0), ("X", 1)], VAC)
    add("PRE-order", prec, [("B", 0), ("A", 1)], VIO)  # A after B does not license B

    altprec = _c(DeclareTemplate.ALTERNATE_PRECEDENCE, "B", "A")
    add("ALTPRE-sat", altprec, [("A", 0), ("B", 1), ("A", 2), ("B", 3)], SAT)
    add("ALTPRE-vio", altprec, [("A", 0), ("B", 1), ("B", 2)], VIO)  # second B has no fresh A

    chprec = _c(DeclareTemplate.CHAIN_PRECEDENCE, "B", "A")
    add("CHPRE-sat", chprec, [("A", 0), ("B", 1)], SAT)
    add("CHPRE-vio", chprec, [("A", 0), ("X", 1), ("B", 2)], VIO)

    # --- co-existence ------------------------------------------------------
    coex = _c(DeclareTemplate.CO_EXISTENCE, "A", "B")
    add("COEX-sat-both", coex, [("A", 0), ("B", 1)], SAT)
    add("COEX-vio", coex, [("A", 0), ("X", 1)], VIO)
    add("COEX-vac", coex, [("X", 0), ("Y", 1)], VAC)

    ncoex = _c(DeclareTemplate.NOT_CO_EXISTENCE, "A", "B")
    add("NCOEX-vio", ncoex, [("A", 0), ("B", 1)], VIO)
    add("NCOEX-sat", ncoex, [("A", 0), ("X", 1)], SAT)
    add("NCOEX-vac", ncoex, [("X", 0), ("Y", 1)], VAC)
    add("NCOEX-vac-target", ncoex, [("B", 0), ("Y", 1)], VAC)  # target alone does not activate

    # --- succession family -------------------------------------------------
    # Succession(A, B) = Response(A, B) AND Precedence(A, B): every A is followed
    # by a B and every B is preceded by an A, so both A and B activate.
    succ = _c(DeclareTemplate.SUCCESSION, "A", "B")
    add("SUC-sat", succ, [("A", 0), ("B", 1)], SAT)
    add("SUC-vio-resp", succ, [("A", 0), ("X", 1)], VIO)  # A never followed
    add("SUC-vio-prec", succ, [("B", 0), ("A", 1), ("B", 2)], VIO)  # first B not preceded
    add("SUC-vio-target-only", succ, [("X", 0), ("B", 1)], VIO)  # B activates on its own
    add("SUC-vac", succ, [("X", 0), ("Y", 1)], VAC)
    add("SUC-multi", succ, [("A", 0), ("A", 1), ("B", 2), ("B", 3)], SAT)

    altsucc = _c(DeclareTemplate.ALTERNATE_SUCCESSION, "A", "B")
    add("ALTSUC-sat", altsucc, [("A", 0), ("B", 1), ("A", 2), ("B", 3)], SAT)
    add("ALTSUC-vio-resp", altsucc, [("A", 0), ("A", 1), ("B", 2)], VIO)
    add("ALTSUC-vio-prec", altsucc, [("A", 0), ("B", 1), ("B", 2)], VIO)

    chsucc = _c(DeclareTemplate.CHAIN_SUCCESSION, "A", "B")
    add("CHSUC-sat", chsucc, [("A", 0), ("B", 1), ("X", 2)], SAT)
    add("CHSUC-vio-resp", chsucc, [("A", 0), ("X", 1), ("B", 2)], VIO)
    add("CHSUC-vio-prec", chsucc, [("X", 0), ("B", 1)], VIO)

    # --- negative binary ---------------------------------------------------
    nresp = _c(DeclareTemplate.NOT_RESPONSE, "A", "B")
    add("NRES-sat", nresp, [("A", 0), ("X", 1)], SAT)
    add("NRES-vio", nresp, [("A", 0), ("B", 1)], VIO)
    add("NRES-sat-before", nresp, [("B", 0), ("A", 1)], SAT)  # B before A is not a response

    nchres = _c(DeclareTemplate.NOT_CHAIN_RESPONSE, "A", "B")
    add("NCHRES-vio", nchres, [("A", 0), ("B", 1)], VIO)
    add("NCHRES-sat", nchres, [("A", 0), ("X", 1), ("B", 2)], SAT)  # not *immediately* followed

    nrexi = _c(DeclareTemplate.NOT_RESPONDED_EXISTENCE, "A", "B")
    add("NREXI-sat", nrexi, [("A", 0), ("X", 1)], SAT)
    add("NREXI-vio", nrexi, [("A", 0), ("B", 1)], VIO)

    nprec = _c(DeclareTemplate.NOT_PRECEDENCE, "B", "A")
    add("NPRE-vio", nprec, [("A", 0), ("B", 1)], VIO)
    add("NPRE-sat", nprec, [("X", 0), ("B", 1)], SAT)

    nchprec = _c(DeclareTemplate.NOT_CHAIN_PRECEDENCE, "B", "A")
    add("NCHPRE-vio", nchprec, [("A", 0), ("B", 1)], VIO)
    add("NCHPRE-sat", nchprec, [("A", 0), ("X", 1), ("B", 2)], SAT)

    nsucc = _c(DeclareTemplate.NOT_SUCCESSION, "A", "B")
    add("NSUC-vio", nsucc, [("A", 0), ("B", 1)], VIO)
    add("NSUC-sat", nsucc, [("A", 0), ("X", 1)], SAT)
    add("NSUC-sat-reverse", nsucc, [("B", 0), ("A", 1)], SAT)  # B before A is allowed
    add("NSUC-sat-target-only", nsucc, [("X", 0), ("B", 1)], SAT)  # B activates, no earlier A

    nchsucc = _c(DeclareTemplate.NOT_CHAIN_SUCCESSION, "A", "B")
    add("NCHSUC-vio", nchsucc, [("A", 0), ("B", 1)], VIO)
    add("NCHSUC-sat", nchsucc, [("A", 0), ("X", 1), ("B", 2)], SAT)
    add("NCHSUC-sat-reverse", nchsucc, [("B", 0), ("A", 1)], SAT)  # pair <B, A> is allowed

    # --- time conditions ---------------------------------------------------
    win = _c(DeclareTemplate.RESPONSE, "A", "B", time_condition=TimeCondition(max_seconds=3600))
    add("TIME-inside", win, [("A", 0), ("B", 30)], SAT)
    add("TIME-outside", win, [("A", 0), ("B", 120)], VIO)
    add("TIME-boundary", win, [("A", 0), ("B", 60)], SAT)  # max_seconds is inclusive
    add("TIME-first-late-second-early", win, [("A", 0), ("B", 120), ("B", 45)], SAT)

    minwin = _c(
        DeclareTemplate.RESPONSE, "A", "B",
        time_condition=TimeCondition(min_seconds=3600, max_seconds=7200),
    )
    add("TIME-too-early", minwin, [("A", 0), ("B", 30)], VIO)
    add("TIME-in-band", minwin, [("A", 0), ("B", 90)], SAT)

    # --- activation conditions (data-aware) --------------------------------
    actcond = _c(
        DeclareTemplate.RESPONSE, "A", "B",
        activation_cond=DataCondition("items['amount'] > 50"),
    )
    add("ACT-true-sat", actcond, [("A", 0, {"amount": 100}), ("B", 1)], SAT)
    add("ACT-true-vio", actcond, [("A", 0, {"amount": 100}), ("X", 1)], VIO)
    add("ACT-false-vac", actcond, [("A", 0, {"amount": 10}), ("X", 1)], VAC)
    add(
        "ACT-mixed",
        actcond,
        [("A", 0, {"amount": 10}), ("X", 1), ("A", 2, {"amount": 100}), ("Y", 3)],
        VIO,
    )  # only the qualifying activation counts, and it fails
    add("ACT-missing-attr-vac", actcond, [("A", 0), ("X", 1)], VAC,
        "Attribute absent: the comparison is false, so the event does not activate")

    # A precedence window is expressed backwards, since the target precedes the
    # activation: the readiness constraints of the clinical model use
    # [-24 h, 0] to mean "within the 24 hours before".
    backwin = _c(
        DeclareTemplate.PRECEDENCE, "B", "A",
        time_condition=TimeCondition(min_seconds=-3600, max_seconds=0),
    )
    add("TIME-prec-inside", backwin, [("A", 0), ("B", 30)], SAT)
    add("TIME-prec-outside", backwin, [("A", 0), ("B", 120)], VIO)

    # --- Existence with an activation condition ----------------------------
    # The condition restricts which occurrences of A count towards AtLeastOne.
    exi_cond = _c(
        DeclareTemplate.EXISTENCE, "A",
        activation_cond=DataCondition("items['amount'] > 50"),
    )
    add("EXICOND-sat", exi_cond, [("A", 0, {"amount": 100})], SAT)
    add("EXICOND-vio", exi_cond, [("A", 0, {"amount": 10})], VIO)
    add("EXICOND-vio-absent", exi_cond, [("X", 0)], VIO)

    # --- correlation conditions -------------------------------------------
    corrcond = _c(
        DeclareTemplate.RESPONSE, "A", "B",
        correlation_cond=DataCondition("items['amount'] > 50"),
    )
    add("COR-sat", corrcond, [("A", 0), ("B", 1, {"amount": 100})], SAT)
    add("COR-vio", corrcond, [("A", 0), ("B", 1, {"amount": 10})], VIO)
    add("COR-second-target-qualifies", corrcond,
        [("A", 0), ("B", 1, {"amount": 10}), ("B", 2, {"amount": 100})], SAT)

    # --- combined data + time ---------------------------------------------
    both = _c(
        DeclareTemplate.RESPONSE, "A", "B",
        activation_cond=DataCondition("items['amount'] > 50"),
        correlation_cond=DataCondition("items['grade'] == 'ok'"),
        time_condition=TimeCondition(max_seconds=3600),
    )
    add("BOTH-sat", both, [("A", 0, {"amount": 100}), ("B", 30, {"grade": "ok"})], SAT)
    add("BOTH-vio-corr", both, [("A", 0, {"amount": 100}), ("B", 30, {"grade": "bad"})], VIO)
    add("BOTH-vio-time", both, [("A", 0, {"amount": 100}), ("B", 120, {"grade": "ok"})], VIO)
    add("BOTH-vac", both, [("A", 0, {"amount": 10}), ("B", 30, {"grade": "ok"})], VAC)

    # --- target selection (framework extension, method.tex def:final_value) -
    latest = _c(
        DeclareTemplate.PRECEDENCE, "B", "A",
        correlation_cond=DataCondition("items['amount'] > 50"),
        target_selection="latest",
    )
    add("SEL-latest-vio", latest,
        [("A", 0, {"amount": 100}), ("A", 1, {"amount": 10}), ("B", 2)], VIO,
        "final-value semantics: the terminal candidate decides, earlier ones are history")
    add("SEL-latest-sat", latest,
        [("A", 0, {"amount": 10}), ("A", 1, {"amount": 100}), ("B", 2)], SAT)
    any_sel = _c(
        DeclareTemplate.PRECEDENCE, "B", "A",
        correlation_cond=DataCondition("items['amount'] > 50"),
    )
    add("SEL-any-sat", any_sel,
        [("A", 0, {"amount": 100}), ("A", 1, {"amount": 10}), ("B", 2)], SAT,
        "existential baseline: any qualifying candidate fulfils the activation")

    return cases


CORRECTNESS_CASES: list[CorrectnessCase] = _build_correctness_cases()


# ---------------------------------------------------------------------------
# SE2/SE3: multi-episode generator
# ---------------------------------------------------------------------------

@dataclass
class SyntheticRule:
    """A generator rule: a constraint plus how to realise each verdict.

    ``planted_rr`` is the risk ratio of the favourable outcome under violation,
    which the outcome model below reproduces exactly in expectation.
    """

    rule_id: str
    constraint: DeclareConstraint
    p_violate: float
    p_vacuous: float
    planted_rr: float
    masking: str  # expected behaviour under case-scoped checking, for the SE2 narrative


EPISODE_GAP = 10 * 24 * 60  # minutes between episodes; wide enough to separate them in time


def _rule_model() -> list[SyntheticRule]:
    """Six rules spanning the failure modes case-scoped checking can exhibit.

    ``masking`` records what the *case-scoped* reading is expected to do to the
    rule once a case carries several episodes, which is the mechanism SE2
    measures:

    * ``mask`` — an unwindowed ordering constraint can satisfy an activation in
      one episode with a target from another, hiding a real violation;
    * ``false-alarm`` — a counting constraint sees occurrences pooled across
      episodes and reports a violation where every episode complies;
    * ``none`` — a time window or a self-contained activation confines the
      constraint to its own episode, so scoping does not change the verdict.
    """
    return [
        SyntheticRule(
            "SYN-R1",
            _c(DeclareTemplate.RESPONSE, "A1", "B1"),
            p_violate=0.30, p_vacuous=0.15, planted_rr=2.0, masking="mask",
        ),
        SyntheticRule(
            "SYN-R2",
            _c(DeclareTemplate.RESPONSE, "A2", "B2", time_condition=TimeCondition(max_seconds=3600)),
            p_violate=0.30, p_vacuous=0.15, planted_rr=0.5, masking="none",
        ),
        SyntheticRule(
            "SYN-R3",
            _c(DeclareTemplate.PRECEDENCE, "C3", "A3"),
            p_violate=0.30, p_vacuous=0.15, planted_rr=3.0, masking="mask",
        ),
        SyntheticRule(
            "SYN-R4",
            _c(DeclareTemplate.AT_MOST_ONE, "D4"),
            p_violate=0.25, p_vacuous=0.0, planted_rr=0.25, masking="false-alarm",
        ),
        SyntheticRule(
            "SYN-R5",
            _c(
                DeclareTemplate.RESPONSE, "X5", "Z5",
                activation_cond=DataCondition("items['amount'] > 50"),
            ),
            p_violate=0.30, p_vacuous=0.20, planted_rr=1.5, masking="mask",
        ),
        SyntheticRule(
            "SYN-R6",
            _c(DeclareTemplate.RESPONSE, "P6", "Q6"),
            p_violate=0.30, p_vacuous=0.15, planted_rr=1.0, masking="mask",
        ),
    ]


RULES: list[SyntheticRule] = _rule_model()


def rule_model() -> DeclareModel:
    """The generator's rules as a :class:`DeclareModel` for the checker."""
    model = DeclareModel(name="synthetic")
    for rule in RULES:
        constraint = rule.constraint
        # The checker keys results on ``id`` when present, else on the label.
        constraint.label = rule.rule_id
        model.add(constraint)
    return model


@dataclass
class SyntheticLogConfig:
    """Generator settings.

    ``p0_success`` must be small enough that the product of the planted risk
    ratios never drives a success probability above one. Clipping it would
    break the very property the outcome model exists to guarantee: an episode
    whose probability is clipped contributes less than its planted risk ratio
    prescribes, which biases every constraint's marginal ratio toward the null
    and would make the recovery experiment measure the clipping rather than the
    estimator. :func:`generate_log` therefore checks the bound rather than
    enforcing it silently.
    """

    n_cases: int = 4000
    p_more_episodes: float = 0.45  # geometric continuation probability
    max_episodes: int = 4
    p0_success: float = 0.10  # baseline success probability, no rule violated
    rules: list[SyntheticRule] = field(default_factory=lambda: RULES)

    def max_success_probability(self) -> float:
        """Success probability of an episode violating every amplifying rule."""
        product = 1.0
        for rule in self.rules:
            if rule.planted_rr > 1:
                product *= rule.planted_rr
        return self.p0_success * product


def _episode_events(
    rule: SyntheticRule,
    verdict: str,
    rng: np.random.Generator,
) -> list[tuple]:
    """Events realising ``verdict`` for ``rule`` inside one episode.

    Offsets are minutes from the episode start and stay well inside the
    episode, so that timestamps never cross an episode boundary.
    """
    rid = rule.rule_id
    if rid == "SYN-R1":  # Response(A1, B1), no window
        if verdict == "vacuous":
            return [("N1", 5)]
        if verdict == "satisfied":
            return [("A1", 5), ("B1", 25)]
        return [("A1", 5), ("N1", 25)]
    if rid == "SYN-R2":  # Response(A2, B2) within 1 h
        if verdict == "vacuous":
            return [("N2", 6)]
        if verdict == "satisfied":
            return [("A2", 6), ("B2", 26)]
        return [("A2", 6), ("B2", 300)]  # answered, but five hours late
    if rid == "SYN-R3":  # Precedence(C3, A3): C3 requires an earlier A3
        if verdict == "vacuous":
            return [("A3", 7)]  # target present, activation absent
        if verdict == "satisfied":
            return [("A3", 7), ("C3", 27)]
        return [("C3", 27)]
    if rid == "SYN-R4":  # AtMostOne(D4)
        if verdict == "satisfied":
            return [("D4", 8)]
        return [("D4", 8), ("D4", 40)]
    if rid == "SYN-R5":  # data-aware Response(X5, Z5), activation amount > 50
        if verdict == "vacuous":
            return [("X5", 9, {"amount": float(rng.integers(5, 50))})]
        amount = float(rng.integers(60, 500))
        if verdict == "satisfied":
            return [("X5", 9, {"amount": amount}), ("Z5", 29)]
        return [("X5", 9, {"amount": amount}), ("N5", 29)]
    if rid == "SYN-R6":  # null rule, Response(P6, Q6)
        if verdict == "vacuous":
            return [("N6", 10)]
        if verdict == "satisfied":
            return [("P6", 10), ("Q6", 30)]
        return [("P6", 10), ("N6", 30)]
    raise ValueError(f"unknown rule {rid}")


def _draw_verdict(rule: SyntheticRule, rng: np.random.Generator) -> str:
    u = rng.random()
    if u < rule.p_vacuous:
        return "vacuous"
    if u < rule.p_vacuous + rule.p_violate:
        return "violated"
    return "satisfied"


def generate_log(
    cfg: SyntheticLogConfig | None = None,
    seed: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Generate a multi-episode log and its ground truth.

    Returns ``(log, truth)``. ``log`` is a wide-schema event log; ``truth`` has
    one row per episode with columns ``case_id``, ``episode_index``,
    ``outcome`` (1 = Success), ``p_success`` (the probability it was drawn
    from), and one column per rule holding the planted verdict.

    The outcome model multiplies the baseline success probability by each
    violated rule's planted risk ratio. Because violations are drawn
    independently across rules, the marginal risk ratio of every rule equals
    its planted value in expectation, which is what SE3 checks the estimator
    against.
    """
    cfg = cfg or SyntheticLogConfig()
    if cfg.max_success_probability() > 1.0:
        raise ValueError(
            "the planted risk ratios can drive the success probability to "
            f"{cfg.max_success_probability():.2f}; lower p0_success to at most "
            f"{cfg.p0_success / cfg.max_success_probability():.3f} so that no episode "
            "needs clipping, which would bias every marginal risk ratio toward the null"
        )
    rng = np.random.default_rng(seed)

    event_rows: list[dict] = []
    truth_rows: list[dict] = []

    for case_i in range(cfg.n_cases):
        case_id = f"S{case_i:06d}"
        n_episodes = 1
        while n_episodes < cfg.max_episodes and rng.random() < cfg.p_more_episodes:
            n_episodes += 1

        case_start = BASE_TS + int(rng.integers(0, 365)) * DAY
        for ep_idx in range(n_episodes):
            ep_start = case_start + ep_idx * EPISODE_GAP * MINUTE
            events: list[tuple] = [(TRIGGER, 0)]
            verdicts: dict[str, str] = {}
            p_success = cfg.p0_success
            for rule in cfg.rules:
                verdict = _draw_verdict(rule, rng)
                verdicts[rule.rule_id] = verdict
                events.extend(_episode_events(rule, verdict, rng))
                if verdict == "violated":
                    p_success *= rule.planted_rr
            outcome = int(rng.random() < p_success)

            for event in events:
                activity, offset = event[0], event[1]
                attrs = event[2] if len(event) > 2 else {}
                row = {
                    "case_id": case_id,
                    "activity": activity,
                    "timestamp": ep_start + offset * MINUTE,
                }
                row.update(attrs)
                event_rows.append(row)

            truth_rows.append(
                {
                    "case_id": case_id,
                    "episode_index": ep_idx,
                    "n_episodes": n_episodes,
                    "outcome": outcome,
                    "p_success": p_success,
                    **verdicts,
                }
            )

    log = pd.DataFrame(event_rows).sort_values(["case_id", "timestamp"]).reset_index(drop=True)
    truth = pd.DataFrame(truth_rows)
    return log, truth


def aggregate_case_truth(truth: pd.DataFrame) -> pd.DataFrame:
    """Case-level ground truth: what a case-scoped verdict should report.

    A case is violated for a rule iff any of its episodes is, vacuous iff all
    of its episodes are, and satisfied otherwise. This is the fairest target
    for the case-scoped checker: it is not asked to recover per-episode detail
    it structurally cannot see, only to get the case-level aggregate right.

    The case outcome is the outcome of the final episode, the reading available
    to an analyst without an episode notion, who sees only how the case ended.
    """
    rule_ids = [r.rule_id for r in RULES]
    rows = []
    for case_id, grp in truth.groupby("case_id", sort=False):
        grp = grp.sort_values("episode_index")
        row = {
            "case_id": case_id,
            "n_episodes": int(grp["n_episodes"].iloc[0]),
            "outcome": int(grp["outcome"].iloc[-1]),
        }
        for rid in rule_ids:
            verdicts = set(grp[rid])
            if "violated" in verdicts:
                row[rid] = "violated"
            elif verdicts == {"vacuous"}:
                row[rid] = "vacuous"
            else:
                row[rid] = "satisfied"
        rows.append(row)
    return pd.DataFrame(rows)
