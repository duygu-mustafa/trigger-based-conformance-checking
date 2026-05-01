"""Clinical rule-model loaders and entry points."""

from __future__ import annotations

from pathlib import Path
import re
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


_TEMPLATE_ALIASES: dict[str, str] = {
    # Multi-perspective aliases in newer configs.
    "MP_EXISTENCE": "EXISTENCE",
    "MP_RESPONSE": "RESPONSE",
    "MP_PRECEDENCE": "PRECEDENCE",
    "MP_SUCCESSION": "SUCCESSION",
    # Timed aliases in newer configs.
    "TIMED_RESPONSE": "RESPONSE",
    # Some configs encode observation-window checks as TIMED_PRECEDENCE without a target.
    # EXISTENCE is the safest unary fallback for those checks in this lightweight checker.
    "TIMED_PRECEDENCE": "EXISTENCE",
    "TIMED_SUCCESSION": "SUCCESSION",
}


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
    normalized = _TEMPLATE_ALIASES.get(normalized, normalized)
    try:
        return DeclareTemplate[normalized]
    except KeyError as exc:
        supported = ", ".join(t.name for t in DeclareTemplate)
        raise ValueError(f"Unknown template '{name}'. Supported templates: {supported}") from exc


def _pick_first(raw: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in raw and raw.get(key) is not None:
            return raw.get(key)
    return None


def _hours_to_seconds(value: Any) -> float | None:
    if value is None:
        return None
    return float(value) * 3600.0


def _build_time_condition(raw: dict[str, Any]) -> TimeCondition | None:
    explicit = raw.get("time_condition")
    if isinstance(explicit, dict):
        min_seconds = explicit.get("min_seconds")
        max_seconds = explicit.get("max_seconds")
    else:
        min_seconds = _pick_first(raw, "min_seconds", "min_gap_seconds")
        max_seconds = _pick_first(raw, "max_seconds", "max_gap_seconds")

    # Newer configs often specify windows as hours.
    if min_seconds is None:
        min_seconds = _hours_to_seconds(_pick_first(raw, "min_gap_hours"))
    if max_seconds is None:
        max_seconds = _hours_to_seconds(
            _pick_first(raw, "max_gap_hours", "observation_window_hours")
        )

    if min_seconds is None and max_seconds is None:
        return None

    return TimeCondition(
        min_seconds=float(min_seconds) if min_seconds is not None else None,
        max_seconds=float(max_seconds) if max_seconds is not None else None,
    )


def _build_data_condition_map(model_data: dict[str, Any]) -> dict[str, str]:
    raw_conditions = model_data.get("data_conditions")
    if not isinstance(raw_conditions, dict):
        return {}

    base_map: dict[str, str] = {}
    for name, condition in raw_conditions.items():
        if not isinstance(name, str) or not isinstance(condition, dict):
            continue

        if condition.get("expression") is not None:
            base_map[name] = str(condition["expression"])
            continue

        expressions = condition.get("expressions")
        if isinstance(expressions, list) and expressions:
            join_op = str(condition.get("logic") or "OR").strip().upper()
            if join_op not in {"AND", "OR"}:
                join_op = "OR"
            parts = [str(part) for part in expressions if part is not None]
            if parts:
                base_map[name] = f" {join_op} ".join(f"({part})" for part in parts)

    resolved: dict[str, str] = {}

    def resolve(name: str, stack: set[str]) -> str:
        if name in resolved:
            return resolved[name]
        if name in stack:
            # Circular references are left as-is.
            return base_map.get(name, "")

        expr = base_map.get(name, "")
        stack = set(stack)
        stack.add(name)

        for other_name in base_map.keys():
            if other_name == name:
                continue
            pattern = rf"\b{re.escape(other_name)}\b"
            if re.search(pattern, expr):
                other_expr = resolve(other_name, stack)
                expr = re.sub(pattern, f"({other_expr})", expr)

        resolved[name] = expr
        return expr

    for name in base_map.keys():
        resolve(name, set())

    return resolved


def _expand_condition_expr(expr: Any, condition_map: dict[str, str]) -> Any:
    if expr is None or not condition_map:
        return expr

    expanded = str(expr)
    # Replace longer names first to avoid accidental partial matches.
    for name in sorted(condition_map.keys(), key=len, reverse=True):
        pattern = rf"\b{re.escape(name)}\b"
        replacement = f"({condition_map[name]})"
        expanded = re.sub(pattern, replacement, expanded)
    return expanded


def _parse_constraint(raw: dict[str, Any], condition_map: dict[str, str]) -> DeclareConstraint:
    if not isinstance(raw, dict):
        raise ValueError("Each constraint must be a mapping")

    missing = [k for k in ("template", "activation") if k not in raw]
    if missing:
        raise ValueError(f"Constraint is missing required fields: {missing}")

    # Accept both old and new config naming.
    activation_cond = _pick_first(
        raw,
        "activation_cond",
        "activation_condition",
        "condition_on_activation",
        "guard",
    )
    correlation_cond = _pick_first(raw, "correlation_cond", "target_condition")
    activation_cond = _expand_condition_expr(activation_cond, condition_map)
    correlation_cond = _expand_condition_expr(correlation_cond, condition_map)
    time_condition = _build_time_condition(raw)

    template = _to_template(str(raw["template"]))
    activation = str(raw["activation"])
    target = str(raw["target"]) if raw.get("target") is not None else None

    # Some MP-style constraints are encoded without an explicit target activity.
    # For this lightweight checker we keep them loadable using a self-target fallback.
    if target is None and template not in {
        DeclareTemplate.EXISTENCE,
        DeclareTemplate.ABSENCE,
        DeclareTemplate.EXACTLY,
        DeclareTemplate.INIT,
    }:
        target = activation

    raw_id = str(raw["id"]) if raw.get("id") is not None else None

    constraint = DeclareConstraint(
        template=template,
        activation=activation,
        target=target,
        activation_cond=DataCondition(str(activation_cond)) if activation_cond is not None else None,
        correlation_cond=DataCondition(str(correlation_cond)) if correlation_cond is not None else None,
        time_condition=time_condition,
        label=(
            str(raw["label"])
            if raw.get("label") is not None
            else raw_id
        ),
    )

    # Attach additional metadata used by downstream exporters/UI.
    constraint.id = raw_id or constraint.label
    constraint.description = str(raw.get("description") or "")
    constraint.rationale = str(raw.get("rationale") or "")
    constraint.semantics = raw.get("semantics")
    constraint.activation_condition_raw = activation_cond
    constraint.target_condition_raw = correlation_cond
    obs_window = raw.get("observation_window_hours")
    if obs_window is not None:
        try:
            constraint.observation_window_hours = float(obs_window)
        except (TypeError, ValueError):
            constraint.observation_window_hours = obs_window

    return constraint


def load_model_from_yaml(path: str | Path) -> DeclareModel:
    config_path = Path(path)
    data = _load_yaml_dict(config_path)

    model_data = data.get("model")
    if not isinstance(model_data, dict):
        # Support a flatter structure where constraints are at the top-level.
        model_data = {}

    name = model_data.get("name") or data.get("name") or config_path.stem
    constraints_data = model_data.get("constraints", data.get("constraints", []))
    condition_map = _build_data_condition_map(model_data)

    if not isinstance(constraints_data, list):
        raise ValueError(f"Invalid rule config at {config_path}: model.constraints must be a list")

    model = DeclareModel(name=str(name))
    for raw_constraint in constraints_data:
        model.add(_parse_constraint(raw_constraint, condition_map=condition_map))

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
