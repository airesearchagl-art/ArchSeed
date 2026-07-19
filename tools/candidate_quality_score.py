from __future__ import annotations

from typing import Any


MIN_QUALITY_SCORE = 0
MAX_QUALITY_SCORE = 100


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _component(points: int, reason: str) -> dict[str, int | str]:
    return {"points": points, "reason": reason}


def clamp_quality_score(value: int) -> int:
    return max(MIN_QUALITY_SCORE, min(MAX_QUALITY_SCORE, value))


def calculate_quality_score(
    quality_metrics: dict[str, Any] | None,
    validation_status: str,
    repair_status: str,
) -> dict[str, Any]:
    warnings: list[str] = []
    if validation_status != "VALID":
        return {
            "quality_score": None,
            "quality_score_status": "NOT_CALCULATED",
            "quality_score_breakdown": {
                "validation": _component(
                    0, "Candidate is not VALID; score was not calculated"
                )
            },
            "quality_score_warnings": [
                "Quality score was not calculated because the candidate is not VALID."
            ],
        }

    metrics = quality_metrics if isinstance(quality_metrics, dict) else {}
    if not isinstance(quality_metrics, dict):
        warnings.append("Quality metrics are unavailable; only known components apply.")

    breakdown: dict[str, dict[str, int | str]] = {
        "base": _component(50, "Base score"),
        "validation": _component(20, "Candidate is VALID"),
    }

    if repair_status == "NOT_NEEDED":
        breakdown["repair"] = _component(10, "No repair was required")
    elif repair_status == "SUCCEEDED":
        breakdown["repair"] = _component(5, "Candidate became VALID after repair")
    else:
        breakdown["repair"] = _component(0, "Repair status is unknown")
        warnings.append(
            f"Repair status {repair_status!r} is not recognized for scoring; no points added."
        )

    has_door = metrics.get("has_door")
    if isinstance(has_door, bool):
        breakdown["door"] = _component(
            5 if has_door else 0,
            "At least one door is present" if has_door else "No door is present",
        )
    else:
        breakdown["door"] = _component(0, "Door presence is unavailable")
        warnings.append("Door presence is unavailable; no door points added.")

    has_window = metrics.get("has_window")
    if isinstance(has_window, bool):
        breakdown["window"] = _component(
            5 if has_window else 0,
            "At least one window is present" if has_window else "No window is present",
        )
    else:
        breakdown["window"] = _component(0, "Window presence is unavailable")
        warnings.append("Window presence is unavailable; no window points added.")

    aspect_ratio = _number(metrics.get("aspect_ratio"))
    if aspect_ratio is None:
        breakdown["aspect_ratio"] = _component(0, "Aspect ratio is unavailable")
        warnings.append("Aspect ratio is unavailable; no aspect-ratio points added.")
    elif aspect_ratio < 1.0:
        breakdown["aspect_ratio"] = _component(
            0, "Aspect ratio is below the expected observation range"
        )
        warnings.append(
            "Aspect ratio is below 1.0; the value was not inverted or otherwise corrected."
        )
    elif aspect_ratio <= 2.0:
        breakdown["aspect_ratio"] = _component(
            5, "Aspect ratio is within the preferred observation range"
        )
    elif aspect_ratio <= 3.0:
        breakdown["aspect_ratio"] = _component(
            2, "Aspect ratio is within the extended observation range"
        )
    else:
        breakdown["aspect_ratio"] = _component(
            -5, "Aspect ratio exceeds the observation range"
        )

    opening_ratio = _number(metrics.get("opening_to_wall_area_ratio"))
    if opening_ratio is None:
        breakdown["opening_ratio"] = _component(
            0, "Opening-to-wall-area ratio is unavailable"
        )
        warnings.append(
            "Opening-to-wall-area ratio is unavailable; no opening-ratio points added."
        )
    elif opening_ratio < 0:
        breakdown["opening_ratio"] = _component(
            0, "Opening-to-wall-area ratio is negative and was not scored"
        )
        warnings.append(
            "Opening-to-wall-area ratio is negative; the value was not corrected."
        )
    elif opening_ratio == 0:
        breakdown["opening_ratio"] = _component(0, "No nominal opening area")
    elif opening_ratio <= 0.40:
        breakdown["opening_ratio"] = _component(
            5, "Opening-to-wall-area ratio is within the observation range"
        )
    elif opening_ratio <= 0.60:
        breakdown["opening_ratio"] = _component(
            0, "Opening-to-wall-area ratio is within the high observation range"
        )
    else:
        breakdown["opening_ratio"] = _component(
            -10, "Opening-to-wall-area ratio exceeds the observation range"
        )

    footprint_area = _number(metrics.get("footprint_area"))
    if footprint_area is None or footprint_area <= 0:
        breakdown["footprint"] = _component(
            0, "Positive footprint area is unavailable"
        )
        warnings.append(
            "Footprint area is unavailable or non-positive; score is partial."
        )
    else:
        breakdown["footprint"] = _component(0, "Footprint area is positive")

    raw_score = sum(int(component["points"]) for component in breakdown.values())
    score = clamp_quality_score(raw_score)
    return {
        "quality_score": score,
        "quality_score_status": "PARTIAL" if warnings else "COMPLETE",
        "quality_score_breakdown": breakdown,
        "quality_score_warnings": warnings,
    }
