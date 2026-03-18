"""Clinical rule-model entry points in one place."""

from conformance.types import DeclareConstraint, DeclareModel, DeclareTemplate


def build_readiness_assessment_model() -> DeclareModel:
    model = DeclareModel(name="readiness_assessment")
    model.add(
        DeclareConstraint(
            template=DeclareTemplate.PRECEDENCE,
            activation="ReadinessCheck",
            target="SBTStarted",
            label="Readiness must precede SBT start",
        )
    )
    model.add(
        DeclareConstraint(
            template=DeclareTemplate.NOT_CO_EXISTENCE,
            activation="ReadinessFailed",
            target="SBTStarted",
            label="No SBT start when readiness failed",
        )
    )
    return model


def build_sbt_execution_model() -> DeclareModel:
    return DeclareModel(name="sbt_execution")


def build_failure_correction_model() -> DeclareModel:
    return DeclareModel(name="failure_correction")

__all__ = [
    "build_readiness_assessment_model",
    "build_sbt_execution_model",
    "build_failure_correction_model",
]
