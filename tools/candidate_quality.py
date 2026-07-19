from __future__ import annotations

from typing import Any

try:
    from tools.validate_archseed import DEFAULT_SLAB_THICKNESS_MM
except ModuleNotFoundError:
    from validate_archseed import DEFAULT_SLAB_THICKNESS_MM


METRIC_KEYS = (
    "footprint_area",
    "aspect_ratio",
    "wall_count",
    "opening_count",
    "door_count",
    "window_count",
    "total_opening_area",
    "opening_to_wall_area_ratio",
    "has_door",
    "has_window",
)


def _empty_metrics(*, repaired: bool, validation_status: str) -> dict[str, Any]:
    metrics = {key: None for key in METRIC_KEYS}
    metrics.update(
        {
            "repaired": repaired,
            "validation_status": validation_status,
        }
    )
    return metrics


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def calculate_candidate_quality(
    archseed_json: dict[str, Any] | None,
    *,
    repaired: bool,
    validation_status: str,
) -> dict[str, Any]:
    metrics = _empty_metrics(
        repaired=repaired,
        validation_status=validation_status,
    )
    warnings: list[str] = []
    if validation_status != "VALID":
        warnings.append(
            "Quality metrics were not calculated because the candidate is not VALID."
        )
        return {
            "quality_metrics": metrics,
            "quality_metrics_status": "NOT_CALCULATED",
            "quality_metrics_warnings": warnings,
        }

    if not isinstance(archseed_json, dict):
        warnings.append("Candidate JSON is unavailable; quality metrics are null.")
        return {
            "quality_metrics": metrics,
            "quality_metrics_status": "PARTIAL",
            "quality_metrics_warnings": warnings,
        }

    building = archseed_json.get("building")
    if not isinstance(building, dict):
        warnings.append("$.building is unavailable; dimensional metrics are null.")
        return {
            "quality_metrics": metrics,
            "quality_metrics_status": "PARTIAL",
            "quality_metrics_warnings": warnings,
        }

    footprint = building.get("footprint")
    width = depth = None
    if isinstance(footprint, dict):
        width = _number(footprint.get("width"))
        depth = _number(footprint.get("depth"))
    if width is None or depth is None or width <= 0 or depth <= 0:
        warnings.append(
            "$.building.footprint width/depth are unavailable or non-positive; "
            "footprint, aspect ratio, and wall ratio metrics may be null."
        )
    else:
        metrics["footprint_area"] = width * depth
        metrics["aspect_ratio"] = max(width, depth) / min(width, depth)

    levels = building.get("levels")
    wall_area = None
    if not isinstance(levels, list) or not levels:
        warnings.append("$.building.levels is unavailable; wall metrics are null.")
    else:
        metrics["wall_count"] = 4 * len(levels)
        slab_thickness = _number(
            building.get("slabThickness", DEFAULT_SLAB_THICKNESS_MM)
        )
        if slab_thickness is None or slab_thickness < 0:
            warnings.append(
                "$.building.slabThickness is unavailable or negative; wall area is null."
            )
        elif width is not None and depth is not None and width > 0 and depth > 0:
            clear_heights: list[float] = []
            for index, level in enumerate(levels):
                height = _number(level.get("height")) if isinstance(level, dict) else None
                if height is None or height <= slab_thickness:
                    warnings.append(
                        f"$.building.levels[{index}].height cannot produce a positive "
                        "generated wall height; wall area is null."
                    )
                    clear_heights = []
                    break
                clear_heights.append(height - slab_thickness)
            if clear_heights:
                wall_area = 2.0 * (width + depth) * sum(clear_heights)

    openings = building.get("openings", [])
    if not isinstance(openings, list):
        warnings.append("$.building.openings is not an array; opening metrics are null.")
    else:
        metrics["opening_count"] = len(openings)
        door_count = 0
        window_count = 0
        total_opening_area = 0.0
        opening_area_complete = True
        for index, opening in enumerate(openings):
            if not isinstance(opening, dict):
                warnings.append(
                    f"$.building.openings[{index}] is not an object; its metrics were skipped."
                )
                opening_area_complete = False
                continue
            opening_type = opening.get("type")
            if opening_type == "door":
                door_count += 1
            elif opening_type == "window":
                window_count += 1
            else:
                warnings.append(
                    f"$.building.openings[{index}].type is unsupported; count is incomplete."
                )
            opening_width = _number(opening.get("width_mm"))
            opening_height = _number(opening.get("height_mm"))
            if (
                opening_width is None
                or opening_height is None
                or opening_width <= 0
                or opening_height <= 0
            ):
                warnings.append(
                    f"$.building.openings[{index}] has unavailable or non-positive "
                    "dimensions; total opening area is null."
                )
                opening_area_complete = False
            else:
                total_opening_area += opening_width * opening_height
        metrics["door_count"] = door_count
        metrics["window_count"] = window_count
        metrics["has_door"] = door_count > 0
        metrics["has_window"] = window_count > 0
        if opening_area_complete:
            metrics["total_opening_area"] = total_opening_area
            if wall_area is not None and wall_area > 0:
                metrics["opening_to_wall_area_ratio"] = total_opening_area / wall_area
            else:
                warnings.append(
                    "Generated gross wall area is unavailable or zero; "
                    "opening_to_wall_area_ratio is null."
                )

    return {
        "quality_metrics": metrics,
        "quality_metrics_status": "COMPLETE" if not warnings else "PARTIAL",
        "quality_metrics_warnings": warnings,
    }
