from __future__ import annotations

from typing import Any


MIN_QUALITY_SCORE = 0
MAX_QUALITY_SCORE = 100

QUALITY_SCORE_VERSION = "2.0"
SCORING_POLICY_ID = "archseed-static-geometry"
SCORING_POLICY_VERSION = "2.0"
BREAKDOWN_SCHEMA_VERSION = "2"

COMPONENT_MAX_POINTS = {
    "structural_validity": 30,
    "metrics_completeness": 20,
    "repair_stability": 15,
    "opening_completeness": 15,
    "geometry_plausibility": 20,
}
TOTAL_MAX_POINTS = sum(COMPONENT_MAX_POINTS.values())

ASPECT_RATIO_THRESHOLDS = {
    "preferred_min": 0.50,
    "preferred_max": 2.00,
    "fallback_low_min": 0.33,
    "fallback_high_max": 3.00,
    "extreme_low_min": 0.20,
    "extreme_high_max": 5.00,
}
OPENING_RATIO_THRESHOLDS = {
    "preferred_min": 0.05,
    "preferred_max": 0.40,
    "fallback_low_min": 0.01,
    "fallback_high_max": 0.60,
    "extreme_high_max": 0.80,
}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _legacy_component(points: int, reason: str) -> dict[str, int | str]:
    return {"points": points, "reason": reason}


def _component(
    name: str,
    points: int,
    *,
    status: str,
    reasons: list[str],
    metrics: dict[str, Any] | None = None,
    thresholds: dict[str, Any] | None = None,
) -> dict[str, Any]:
    max_points = COMPONENT_MAX_POINTS[name]
    if not 0 <= points <= max_points:
        raise ValueError(
            f"{name} points must be between 0 and {max_points}, got {points}."
        )
    result: dict[str, Any] = {
        "component": name,
        "points": points,
        "max_points": max_points,
        "status": status,
        "reasons": reasons,
        "metrics": metrics or {},
    }
    if thresholds is not None:
        result["thresholds"] = thresholds
    return result


def _append_warning(warnings: list[str], message: str) -> None:
    if message not in warnings:
        warnings.append(message)


def clamp_quality_score(value: int) -> int:
    return max(MIN_QUALITY_SCORE, min(MAX_QUALITY_SCORE, value))


def _metadata() -> dict[str, str]:
    return {
        "quality_score_version": QUALITY_SCORE_VERSION,
        "scoring_policy_id": SCORING_POLICY_ID,
        "scoring_policy_version": SCORING_POLICY_VERSION,
        "breakdown_schema_version": BREAKDOWN_SCHEMA_VERSION,
    }


def _not_calculated_breakdown(
    validation_status: str,
    metrics_status: str,
) -> dict[str, dict[str, Any]]:
    structural_reason = (
        "Candidate is not VALID; structural validity was not scored."
        if validation_status != "VALID"
        else "Candidate is VALID, but quality metrics are unavailable."
    )
    structural_points = 0 if validation_status != "VALID" else 30
    structural_status = (
        "NOT_CALCULATED" if validation_status != "VALID" else "COMPLETE"
    )
    return {
        "structural_validity": _component(
            "structural_validity",
            structural_points,
            status=structural_status,
            reasons=[structural_reason],
            metrics={"validation_status": validation_status},
        ),
        "metrics_completeness": _component(
            "metrics_completeness",
            0,
            status="NOT_CALCULATED",
            reasons=["Candidate quality metrics are unavailable."],
            metrics={"quality_metrics_status": metrics_status},
        ),
        "repair_stability": _component(
            "repair_stability",
            0,
            status="NOT_APPLICABLE",
            reasons=["Repair stability was not evaluated without quality metrics."],
        ),
        "opening_completeness": _component(
            "opening_completeness",
            0,
            status="NOT_APPLICABLE",
            reasons=[
                "Opening observations were not evaluated without quality metrics."
            ],
        ),
        "geometry_plausibility": _component(
            "geometry_plausibility",
            0,
            status="NOT_APPLICABLE",
            reasons=[
                "Geometry observations were not evaluated without quality metrics."
            ],
        ),
    }


def _repair_component(
    metrics: dict[str, Any],
    repair_status: str,
    warnings: list[str],
) -> dict[str, Any]:
    repaired = metrics.get("repaired")
    if not isinstance(repaired, bool):
        if repair_status == "NOT_NEEDED":
            repaired = False
        elif repair_status == "SUCCEEDED":
            repaired = True

    if repaired is False:
        return _component(
            "repair_stability",
            15,
            status="COMPLETE",
            reasons=["No repair was required."],
            metrics={"repaired": False},
        )
    if repaired is True:
        return _component(
            "repair_stability",
            5,
            status="COMPLETE",
            reasons=[
                "The candidate became VALID after repair; repair severity was "
                "not inferred."
            ],
            metrics={"repaired": True},
        )

    _append_warning(
        warnings,
        "Repair information is unavailable; repair stability was not scored.",
    )
    return _component(
        "repair_stability",
        0,
        status="PARTIAL",
        reasons=["Repair information is unavailable."],
        metrics={"repaired": None},
    )


def _opening_component(
    metrics: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    has_door = metrics.get("has_door")
    has_window = metrics.get("has_window")
    observed = {"has_door": has_door, "has_window": has_window}

    if not isinstance(has_door, bool) or not isinstance(has_window, bool):
        _append_warning(
            warnings,
            "Door or window presence is unavailable in static candidate metrics.",
        )
        return _component(
            "opening_completeness",
            0,
            status="PARTIAL",
            reasons=["Door and window presence must both be known for this component."],
            metrics=observed,
        )

    reasons: list[str] = []
    if not has_door:
        reasons.append("Door not detected in static candidate metrics.")
        _append_warning(
            warnings,
            "Door not detected in static candidate metrics; this is not a "
            "validity failure.",
        )
    if not has_window:
        reasons.append("Window not detected in static candidate metrics.")
        _append_warning(
            warnings,
            "Window not detected in static candidate metrics; this is not a "
            "validity failure.",
        )

    if has_door and has_window:
        points = 15
        reasons.append("Both door and window observations are present.")
    elif has_door or has_window:
        points = 8
        reasons.append("Only one opening type is present.")
    else:
        points = 0
        reasons.append("No door or window observation is present.")

    return _component(
        "opening_completeness",
        points,
        status="COMPLETE",
        reasons=reasons,
        metrics=observed,
    )


def _aspect_ratio_points(
    value: float | None,
    warnings: list[str],
) -> tuple[int, str, str]:
    if value is None:
        _append_warning(warnings, "Aspect ratio is unavailable.")
        return 0, "PARTIAL", "Aspect ratio is unavailable."
    if 0.50 <= value <= 2.00:
        return 10, "COMPLETE", "Aspect ratio is within the preferred draft range."
    if 0.33 <= value < 0.50 or 2.00 < value <= 3.00:
        return 6, "COMPLETE", "Aspect ratio is within the fallback draft range."
    if 0.20 <= value < 0.33 or 3.00 < value <= 5.00:
        return 2, "COMPLETE", "Aspect ratio is within the extreme draft range."

    _append_warning(
        warnings,
        "Aspect ratio is outside the preferred draft range.",
    )
    return 0, "COMPLETE", "Aspect ratio is outside the scored draft ranges."


def _opening_ratio_points(
    value: float | None,
    warnings: list[str],
) -> tuple[int, str, str]:
    if value is None:
        _append_warning(warnings, "Opening-to-wall-area ratio is unavailable.")
        return 0, "PARTIAL", "Opening-to-wall-area ratio is unavailable."
    if 0.05 <= value <= 0.40:
        return (
            10,
            "COMPLETE",
            "Opening-to-wall-area ratio is within the preferred draft range.",
        )
    if 0.01 <= value < 0.05 or 0.40 < value <= 0.60:
        return (
            6,
            "COMPLETE",
            "Opening-to-wall-area ratio is within the fallback draft range.",
        )
    if 0 < value < 0.01 or 0.60 < value <= 0.80:
        return (
            2,
            "COMPLETE",
            "Opening-to-wall-area ratio is within the extreme draft range.",
        )

    _append_warning(
        warnings,
        "Opening-to-wall-area ratio is outside the preferred draft range.",
    )
    return (
        0,
        "COMPLETE",
        "Opening-to-wall-area ratio is outside the scored draft ranges.",
    )


def _geometry_component(
    metrics: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    aspect_ratio = _number(metrics.get("aspect_ratio"))
    opening_ratio = _number(metrics.get("opening_to_wall_area_ratio"))
    aspect_points, aspect_status, aspect_reason = _aspect_ratio_points(
        aspect_ratio, warnings
    )
    opening_points, opening_status, opening_reason = _opening_ratio_points(
        opening_ratio, warnings
    )
    status = (
        "COMPLETE"
        if aspect_status == "COMPLETE" and opening_status == "COMPLETE"
        else "PARTIAL"
    )
    return _component(
        "geometry_plausibility",
        aspect_points + opening_points,
        status=status,
        reasons=[aspect_reason, opening_reason],
        metrics={
            "aspect_ratio": aspect_ratio,
            "opening_to_wall_area_ratio": opening_ratio,
        },
        thresholds={
            "aspect_ratio": ASPECT_RATIO_THRESHOLDS,
            "opening_to_wall_area_ratio": OPENING_RATIO_THRESHOLDS,
        },
    )


def calculate_quality_score_v2(
    quality_metrics: dict[str, Any] | None,
    validation_status: str,
    repair_status: str,
    *,
    metrics_status: str | None = None,
) -> dict[str, Any]:
    """Calculate deterministic Candidate Quality Score Policy v2 output."""
    warnings: list[str] = []
    resolved_metrics_status = metrics_status
    if resolved_metrics_status is None:
        resolved_metrics_status = (
            "COMPLETE" if isinstance(quality_metrics, dict) else "NOT_CALCULATED"
        )

    if validation_status != "VALID":
        return {
            **_metadata(),
            "quality_score": None,
            "quality_score_raw": None,
            "quality_score_status": "NOT_CALCULATED",
            "quality_score_breakdown": _not_calculated_breakdown(
                validation_status, resolved_metrics_status
            ),
            "quality_score_warnings": [
                "Quality score was not calculated because the candidate is not VALID."
            ],
        }

    if (
        resolved_metrics_status == "NOT_CALCULATED"
        or not isinstance(quality_metrics, dict)
    ):
        return {
            **_metadata(),
            "quality_score": None,
            "quality_score_raw": None,
            "quality_score_status": "NOT_CALCULATED",
            "quality_score_breakdown": _not_calculated_breakdown(
                validation_status, "NOT_CALCULATED"
            ),
            "quality_score_warnings": [
                "Quality score was not calculated because quality metrics are "
                "unavailable."
            ],
        }

    metrics = quality_metrics
    if resolved_metrics_status not in ("COMPLETE", "PARTIAL"):
        _append_warning(
            warnings,
            f"Quality metrics status {resolved_metrics_status!r} is unknown; "
            "the score is PARTIAL.",
        )
        resolved_metrics_status = "PARTIAL"

    completeness_points = 20 if resolved_metrics_status == "COMPLETE" else 5
    if resolved_metrics_status == "PARTIAL":
        _append_warning(
            warnings,
            "Candidate quality metrics are incomplete; missing components were not "
            "re-normalized.",
        )

    breakdown = {
        "structural_validity": _component(
            "structural_validity",
            30,
            status="COMPLETE",
            reasons=["Candidate validation status is VALID."],
            metrics={"validation_status": validation_status},
        ),
        "metrics_completeness": _component(
            "metrics_completeness",
            completeness_points,
            status=resolved_metrics_status,
            reasons=[
                (
                    "Candidate quality metrics are complete."
                    if resolved_metrics_status == "COMPLETE"
                    else "Candidate quality metrics are partial and were not "
                    "re-normalized."
                )
            ],
            metrics={"quality_metrics_status": resolved_metrics_status},
        ),
        "repair_stability": _repair_component(
            metrics, repair_status, warnings
        ),
        "opening_completeness": _opening_component(metrics, warnings),
        "geometry_plausibility": _geometry_component(metrics, warnings),
    }

    score_status = (
        "COMPLETE"
        if resolved_metrics_status == "COMPLETE"
        and all(
            component["status"] == "COMPLETE"
            for component in breakdown.values()
        )
        else "PARTIAL"
    )
    raw_score = sum(component["points"] for component in breakdown.values())
    score = clamp_quality_score(raw_score)
    return {
        **_metadata(),
        "quality_score": score,
        "quality_score_raw": raw_score,
        "quality_score_status": score_status,
        "quality_score_breakdown": breakdown,
        "quality_score_warnings": warnings,
    }


def calculate_quality_score(
    quality_metrics: dict[str, Any] | None,
    validation_status: str,
    repair_status: str,
    *,
    metrics_status: str | None = None,
) -> dict[str, Any]:
    """Calculate the current Candidate Quality Score policy (v2)."""
    return calculate_quality_score_v2(
        quality_metrics,
        validation_status,
        repair_status,
        metrics_status=metrics_status,
    )


def calculate_quality_score_v1(
    quality_metrics: dict[str, Any] | None,
    validation_status: str,
    repair_status: str,
) -> dict[str, Any]:
    """Calculate the legacy unversioned v1-equivalent score without migration."""
    warnings: list[str] = []
    if validation_status != "VALID":
        return {
            "quality_score": None,
            "quality_score_status": "NOT_CALCULATED",
            "quality_score_breakdown": {
                "validation": _legacy_component(
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
        "base": _legacy_component(50, "Base score"),
        "validation": _legacy_component(20, "Candidate is VALID"),
    }

    if repair_status == "NOT_NEEDED":
        breakdown["repair"] = _legacy_component(10, "No repair was required")
    elif repair_status == "SUCCEEDED":
        breakdown["repair"] = _legacy_component(
            5, "Candidate became VALID after repair"
        )
    else:
        breakdown["repair"] = _legacy_component(0, "Repair status is unknown")
        warnings.append(
            f"Repair status {repair_status!r} is not recognized for scoring; "
            "no points added."
        )

    has_door = metrics.get("has_door")
    if isinstance(has_door, bool):
        breakdown["door"] = _legacy_component(
            5 if has_door else 0,
            "At least one door is present" if has_door else "No door is present",
        )
    else:
        breakdown["door"] = _legacy_component(0, "Door presence is unavailable")
        warnings.append("Door presence is unavailable; no door points added.")

    has_window = metrics.get("has_window")
    if isinstance(has_window, bool):
        breakdown["window"] = _legacy_component(
            5 if has_window else 0,
            "At least one window is present" if has_window else "No window is present",
        )
    else:
        breakdown["window"] = _legacy_component(
            0, "Window presence is unavailable"
        )
        warnings.append("Window presence is unavailable; no window points added.")

    aspect_ratio = _number(metrics.get("aspect_ratio"))
    if aspect_ratio is None:
        breakdown["aspect_ratio"] = _legacy_component(
            0, "Aspect ratio is unavailable"
        )
        warnings.append("Aspect ratio is unavailable; no aspect-ratio points added.")
    elif aspect_ratio < 1.0:
        breakdown["aspect_ratio"] = _legacy_component(
            0, "Aspect ratio is below the expected observation range"
        )
        warnings.append(
            "Aspect ratio is below 1.0; the value was not inverted or otherwise "
            "corrected."
        )
    elif aspect_ratio <= 2.0:
        breakdown["aspect_ratio"] = _legacy_component(
            5, "Aspect ratio is within the preferred observation range"
        )
    elif aspect_ratio <= 3.0:
        breakdown["aspect_ratio"] = _legacy_component(
            2, "Aspect ratio is within the extended observation range"
        )
    else:
        breakdown["aspect_ratio"] = _legacy_component(
            -5, "Aspect ratio exceeds the observation range"
        )

    opening_ratio = _number(metrics.get("opening_to_wall_area_ratio"))
    if opening_ratio is None:
        breakdown["opening_ratio"] = _legacy_component(
            0, "Opening-to-wall-area ratio is unavailable"
        )
        warnings.append(
            "Opening-to-wall-area ratio is unavailable; no opening-ratio points added."
        )
    elif opening_ratio < 0:
        breakdown["opening_ratio"] = _legacy_component(
            0, "Opening-to-wall-area ratio is negative and was not scored"
        )
        warnings.append(
            "Opening-to-wall-area ratio is negative; the value was not corrected."
        )
    elif opening_ratio == 0:
        breakdown["opening_ratio"] = _legacy_component(0, "No nominal opening area")
    elif opening_ratio <= 0.40:
        breakdown["opening_ratio"] = _legacy_component(
            5, "Opening-to-wall-area ratio is within the observation range"
        )
    elif opening_ratio <= 0.60:
        breakdown["opening_ratio"] = _legacy_component(
            0, "Opening-to-wall-area ratio is within the high observation range"
        )
    else:
        breakdown["opening_ratio"] = _legacy_component(
            -10, "Opening-to-wall-area ratio exceeds the observation range"
        )

    footprint_area = _number(metrics.get("footprint_area"))
    if footprint_area is None or footprint_area <= 0:
        breakdown["footprint"] = _legacy_component(
            0, "Positive footprint area is unavailable"
        )
        warnings.append(
            "Footprint area is unavailable or non-positive; score is partial."
        )
    else:
        breakdown["footprint"] = _legacy_component(
            0, "Footprint area is positive"
        )

    raw_score = sum(int(component["points"]) for component in breakdown.values())
    score = clamp_quality_score(raw_score)
    return {
        "quality_score": score,
        "quality_score_status": "PARTIAL" if warnings else "COMPLETE",
        "quality_score_breakdown": breakdown,
        "quality_score_warnings": warnings,
    }
