from weaning_conformance.model import DeclareConstraint, DeclareTemplate
from weaning_conformance.model.constraint import TimeCondition, DataCondition

# Control-flow only
c1 = DeclareConstraint(
    template=DeclareTemplate.RESPONSE,
    activation="SBT_Started",
    target="SBT_Completed",
)

# Control-flow + time perspective
c2 = DeclareConstraint(
    template=DeclareTemplate.RESPONSE,
    activation="SBT_Failed",
    target="Cause_Identified",
    time_condition=TimeCondition(min_seconds=0, max_seconds=86400),  # within 24h
)

# Control-flow + data perspective (activation condition only)
c3 = DeclareConstraint(
    template=DeclareTemplate.ABSENCE,
    activation="SBT_Started",
    activation_cond=DataCondition("RSBI >= 105"),
)

# Full multi-perspective: control-flow + data + time
c4 = DeclareConstraint(
    template=DeclareTemplate.NOT_RESPONSE,
    activation="SBT_Started",
    target="Sedation_Bolus",
    activation_cond=DataCondition("vasopressor_dose <= 0.1"),
    correlation_cond=DataCondition("A.FiO2 <= 0.4 and B.dose > 0"),
    time_condition=TimeCondition(max_seconds=7200),  # not within 2h
    label="No sedation bolus within 2h of SBT start under low vasopressor dose",
)
