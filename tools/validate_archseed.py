from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


MAX_FOOTPRINT_MM = 200_000
MAX_LEVELS = 20
MAX_LEVEL_HEIGHT_MM = 10_000


class ValidationError(ValueError):
    pass


def _require_object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"{path} must be an object")
    return value


def _require_number(value: Any, path: str, *, minimum: float, maximum: float) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValidationError(f"{path} must be a number")
    number = float(value)
    if number <= minimum or number > maximum:
        raise ValidationError(f"{path} must be > {minimum} and <= {maximum}")
    return number


def _require_string(value: Any, path: str, *, max_length: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{path} must be a non-empty string")
    if len(value) > max_length:
        raise ValidationError(f"{path} must be at most {max_length} characters")
    return value


def _reject_unknown_keys(value: dict[str, Any], path: str, allowed: set[str]) -> None:
    unknown = set(value) - allowed
    if unknown:
        joined = ", ".join(sorted(unknown))
        raise ValidationError(f"{path} has unknown key(s): {joined}")


def validate_archseed(data: Any) -> dict[str, Any]:
    root = _require_object(data, "$")
    _reject_unknown_keys(root, "$", {"schemaVersion", "units", "project", "building"})

    if root.get("schemaVersion") != "archseed.v0.1":
        raise ValidationError("$.schemaVersion must be 'archseed.v0.1'")
    if root.get("units") != "mm":
        raise ValidationError("$.units must be 'mm'")

    project = _require_object(root.get("project"), "$.project")
    _reject_unknown_keys(project, "$.project", {"name", "description"})
    _require_string(project.get("name"), "$.project.name", max_length=120)
    if "description" in project:
        _require_string(project["description"], "$.project.description", max_length=1000)

    building = _require_object(root.get("building"), "$.building")
    _reject_unknown_keys(
        building,
        "$.building",
        {"footprint", "levels", "wallThickness", "slabThickness", "roof"},
    )

    footprint = _require_object(building.get("footprint"), "$.building.footprint")
    _reject_unknown_keys(footprint, "$.building.footprint", {"width", "depth"})
    _require_number(
        footprint.get("width"),
        "$.building.footprint.width",
        minimum=0,
        maximum=MAX_FOOTPRINT_MM,
    )
    _require_number(
        footprint.get("depth"),
        "$.building.footprint.depth",
        minimum=0,
        maximum=MAX_FOOTPRINT_MM,
    )

    levels = building.get("levels")
    if not isinstance(levels, list) or not 1 <= len(levels) <= MAX_LEVELS:
        raise ValidationError(f"$.building.levels must contain 1 to {MAX_LEVELS} levels")
    for index, level_value in enumerate(levels):
        level_path = f"$.building.levels[{index}]"
        level = _require_object(level_value, level_path)
        _reject_unknown_keys(level, level_path, {"name", "height"})
        _require_string(level.get("name"), f"{level_path}.name", max_length=80)
        _require_number(
            level.get("height"),
            f"{level_path}.height",
            minimum=0,
            maximum=MAX_LEVEL_HEIGHT_MM,
        )

    if "wallThickness" in building:
        _require_number(
            building["wallThickness"],
            "$.building.wallThickness",
            minimum=0,
            maximum=1000,
        )
    if "slabThickness" in building:
        _require_number(
            building["slabThickness"],
            "$.building.slabThickness",
            minimum=0,
            maximum=1000,
        )

    if "roof" in building:
        roof = _require_object(building["roof"], "$.building.roof")
        _reject_unknown_keys(roof, "$.building.roof", {"type", "parapetHeight"})
        if roof.get("type") != "flat":
            raise ValidationError("$.building.roof.type must be 'flat'")
        if "parapetHeight" in roof:
            height = roof["parapetHeight"]
            if not isinstance(height, (int, float)) or isinstance(height, bool):
                raise ValidationError("$.building.roof.parapetHeight must be a number")
            if height < 0 or height > 2000:
                raise ValidationError(
                    "$.building.roof.parapetHeight must be >= 0 and <= 2000"
                )

    return root


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(
            "Usage: python tools/validate_archseed.py <path-to-archseed-json>",
            file=sys.stderr,
        )
        return 2

    path = Path(argv[1])
    try:
        validate_archseed(load_json(path))
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1

    print(f"VALID: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
