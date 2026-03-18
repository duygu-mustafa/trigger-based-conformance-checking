"""Clinical rule-model loaders and entry points."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from conformance.types import (
    DataCondition,
    DeclareConstraint,
    DeclareModel,
    DeclareTemplate,
    TimeCondition,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DECLARE_CONFIG_DIR = PROJECT_ROOT / "configs" / "declare"


def _load_yaml_dict(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "PyYAML is required to load DECLARE rule configs. Install with `pip install pyyaml`."
        ) from exc

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if not isinstance(data, dict):
        raise ValueError(f"Invalid rule config at {path}: expected a top-level mapping")

    return data


def _to_template(name: str) -> DeclareTemplate:
    normalized = name.strip().upper().replace(" ", "_").replace("-", "_")
    try:
        return DeclareTemplate[normalized]
    except KeyError as exc:
        supported = ", ".join(t.name for t in DeclareTemplate)
        raise ValueError(f"Unknown template '{name}'. Supported templates: {supported}") from exc


def _parse_constraint(raw: dict[str, Any]) -> DeclareConstraint:
    if not isinstance(raw, dict):
        raise ValueError("Each constraint must be a mapping")

    missing = [k for k in ("template", "activation") if k not in raw]
    if missing:
        raise ValueError(f"Constraint is missing required fields: {missing}")

    activation_cond = raw.get("activation_cond")
    correlation_cond = raw.get("correlation_cond")
    time_condition = raw.get("time_condition")

    return DeclareConstraint(
        template=_to_template(str(raw["template"])),
        activation=str(raw["activation"]),
        target=str(raw["target"]) if raw.get("target") is not None else None,
        activation_cond=DataCondition(str(activation_cond)) if activation_cond is not None else None,
        correlation_cond=DataCondition(str(correlation_cond)) if correlation_cond is not None else None,
        time_condition=TimeCondition(
            min_seconds=time_condition.get("min_seconds"),
            max_seconds=time_condition.get("max_seconds"),
        )
        if isinstance(time_condition, dict)
        else None,
        label=str(raw["label"]) if raw.get("label") is not None else None,
    )


def load_model_from_yaml(path: str | Path) -> DeclareModel:
    config_path = Path(path)
    data = _load_yaml_dict(config_path)

    model_data = data.get("model")
    if not isinstance(model_data, dict):
        raise ValueError(f"Invalid rule config at {config_path}: missing 'model' mapping")

    name = model_data.get("name")
    constraints_data = model_data.get("constraints", [])

    if not name:
        raise ValueError(f"Invalid rule config at {config_path}: model.name is required")
    if not isinstance(constraints_data, list):
        raise ValueError(f"Invalid rule config at {config_path}: model.constraints must be a list")

    model = DeclareModel(name=str(name))
    for raw_constraint in constraints_data:
        model.add(_parse_constraint(raw_constraint))

    return model


def build_readiness_assessment_model() -> DeclareModel:
    return load_model_from_yaml(DECLARE_CONFIG_DIR / "readiness_assessment.yaml")


def build_sbt_execution_model() -> DeclareModel:
    return load_model_from_yaml(DECLARE_CONFIG_DIR / "sbt_execution.yaml")


def build_failure_correction_model() -> DeclareModel:
    return load_model_from_yaml(DECLARE_CONFIG_DIR / "failure_correction.yaml")


__all__ = [
    "load_model_from_yaml",
    "build_readiness_assessment_model",
    "build_sbt_execution_model",
    "build_failure_correction_model",
]
