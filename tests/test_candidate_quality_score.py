from __future__ import annotations

from pathlib import Path

import pytest

from tools.candidate_quality_score import (
    BREAKDOWN_SCHEMA_VERSION,
    COMPONENT_MAX_POINTS,
    QUALITY_SCORE_VERSION,
    SCORING_POLICY_ID,
    SCORING_POLICY_VERSION,
    TOTAL_MAX_POINTS,
    calculate_quality_score,
    calculate_quality_score_v1,
    clamp_quality_score,
)
from tools.generate_candidates_with_lmstudio import select_best_candidate


ROOT = Path(__file__).resolve().parents[1]


def metrics(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "footprint_area": 48_000_000.0,
        "aspect_ratio": 1.5,
        "has_door": True,
        "has_window": True,
        "opening_to_wall_area_ratio": 0.20,
        "repaired": False,
    }
    values.update(overrides)
    return values


def score(
    quality_metrics: dict[str, object] | None = None,
    *,
    validation_status: str = "VALID",
    repair_status: str = "NOT_NEEDED",
    metrics_status: str | None = "COMPLETE",
) -> dict:
    return calculate_quality_score(
        metrics() if quality_metrics is None else quality_metrics,
        validation_status,
        repair_status,
        metrics_status=metrics_status,
    )


def test_policy_v2_identity_and_weights() -> None:
    assert QUALITY_SCORE_VERSION == "2.0"
    assert SCORING_POLICY_ID == "archseed-static-geometry"
    assert SCORING_POLICY_VERSION == "2.0"
    assert BREAKDOWN_SCHEMA_VERSION == "2"
    assert COMPONENT_MAX_POINTS == {
        "structural_validity": 30,
        "metrics_completeness": 20,
        "repair_stability": 15,
        "opening_completeness": 15,
        "geometry_plausibility": 20,
    }
    assert TOTAL_MAX_POINTS == 100


def test_complete_high_score_candidate() -> None:
    result = score()
    assert result["quality_score"] == 100
    assert result["quality_score_raw"] == 100
    assert result["quality_score_status"] == "COMPLETE"
    assert result["quality_score_warnings"] == []


def test_complete_candidate_can_score_below_100() -> None:
    result = score(metrics(aspect_ratio=2.5))
    assert result["quality_score"] == 96
    assert result["quality_score_status"] == "COMPLETE"
    assert result["quality_score_breakdown"]["geometry_plausibility"][
        "points"
    ] == 16


def test_repaired_candidate_loses_only_repair_stability_points() -> None:
    result = score(
        metrics(repaired=True),
        repair_status="SUCCEEDED",
    )
    assert result["quality_score"] == 90
    assert result["quality_score_breakdown"]["repair_stability"]["points"] == 5
    assert result["quality_score_breakdown"]["structural_validity"]["points"] == 30
    assert result["quality_score_breakdown"]["geometry_plausibility"]["points"] == 20


def test_invalid_candidate_is_not_scored() -> None:
    result = score(validation_status="INVALID")
    assert result["quality_score"] is None
    assert result["quality_score_raw"] is None
    assert result["quality_score_status"] == "NOT_CALCULATED"
    assert result["quality_score_warnings"]


def test_unavailable_metrics_are_not_scored() -> None:
    result = score(None, metrics_status="NOT_CALCULATED")
    assert result["quality_score"] is None
    assert result["quality_score_status"] == "NOT_CALCULATED"
    assert result["quality_score_breakdown"]["metrics_completeness"][
        "status"
    ] == "NOT_CALCULATED"


def test_partial_metrics_are_not_renormalized() -> None:
    result = score(metrics_status="PARTIAL")
    assert result["quality_score"] == 85
    assert result["quality_score_status"] == "PARTIAL"
    completeness = result["quality_score_breakdown"]["metrics_completeness"]
    assert completeness["points"] == 5
    assert completeness["max_points"] == 20
    assert any(
        "not re-normalized" in warning
        for warning in result["quality_score_warnings"]
    )


@pytest.mark.parametrize(
    ("has_door", "has_window", "expected_points"),
    [
        (True, True, 15),
        (True, False, 8),
        (False, True, 8),
        (False, False, 0),
    ],
)
def test_opening_completeness_points(
    has_door: bool,
    has_window: bool,
    expected_points: int,
) -> None:
    result = score(metrics(has_door=has_door, has_window=has_window))
    component = result["quality_score_breakdown"]["opening_completeness"]
    assert component["points"] == expected_points
    assert component["status"] == "COMPLETE"
    assert result["quality_score_status"] == "COMPLETE"
    assert bool(result["quality_score_warnings"]) is not (has_door and has_window)


def test_missing_opening_metric_is_partial_without_inference() -> None:
    result = score(metrics(has_door=None))
    component = result["quality_score_breakdown"]["opening_completeness"]
    assert component["points"] == 0
    assert component["status"] == "PARTIAL"
    assert result["quality_score_status"] == "PARTIAL"


@pytest.mark.parametrize(
    ("aspect_ratio", "expected_aspect_points"),
    [
        (0.50, 10),
        (2.00, 10),
        (0.33, 6),
        (2.01, 6),
        (3.00, 6),
        (0.20, 2),
        (3.01, 2),
        (5.00, 2),
        (0.19, 0),
        (5.01, 0),
    ],
)
def test_aspect_ratio_soft_ranges(
    aspect_ratio: float,
    expected_aspect_points: int,
) -> None:
    result = score(metrics(aspect_ratio=aspect_ratio))
    geometry = result["quality_score_breakdown"]["geometry_plausibility"]
    assert geometry["points"] == expected_aspect_points + 10


@pytest.mark.parametrize(
    ("opening_ratio", "expected_opening_points"),
    [
        (0.05, 10),
        (0.40, 10),
        (0.01, 6),
        (0.049, 6),
        (0.401, 6),
        (0.60, 6),
        (0.001, 2),
        (0.601, 2),
        (0.80, 2),
        (0.0, 0),
        (-0.1, 0),
        (0.801, 0),
    ],
)
def test_opening_ratio_soft_ranges(
    opening_ratio: float,
    expected_opening_points: int,
) -> None:
    result = score(metrics(opening_to_wall_area_ratio=opening_ratio))
    geometry = result["quality_score_breakdown"]["geometry_plausibility"]
    assert geometry["points"] == 10 + expected_opening_points


def test_extreme_geometry_produces_deterministic_warnings() -> None:
    result = score(
        metrics(aspect_ratio=8.0, opening_to_wall_area_ratio=0.9)
    )
    assert result["quality_score_breakdown"]["geometry_plausibility"]["points"] == 0
    assert result["quality_score_status"] == "COMPLETE"
    assert result["quality_score_warnings"] == [
        "Aspect ratio is outside the preferred draft range.",
        "Opening-to-wall-area ratio is outside the preferred draft range.",
    ]


def test_missing_geometry_metric_is_partial() -> None:
    result = score(metrics(aspect_ratio=None))
    geometry = result["quality_score_breakdown"]["geometry_plausibility"]
    assert geometry["points"] == 10
    assert geometry["status"] == "PARTIAL"
    assert result["quality_score_status"] == "PARTIAL"
    assert any("unavailable" in reason.lower() for reason in geometry["reasons"])


def test_unknown_repair_information_is_partial_without_assumed_points() -> None:
    result = score(metrics(repaired=None), repair_status="UNKNOWN")
    component = result["quality_score_breakdown"]["repair_stability"]
    assert component["points"] == 0
    assert component["status"] == "PARTIAL"
    assert result["quality_score_status"] == "PARTIAL"


def test_v2_metadata_is_saved_in_score_result() -> None:
    result = score()
    assert result["quality_score_version"] == "2.0"
    assert result["scoring_policy_id"] == "archseed-static-geometry"
    assert result["scoring_policy_version"] == "2.0"
    assert result["breakdown_schema_version"] == "2"


def test_breakdown_schema_and_score_are_consistent() -> None:
    result = score(metrics(aspect_ratio=2.5))
    breakdown = result["quality_score_breakdown"]
    assert set(breakdown) == set(COMPONENT_MAX_POINTS)
    assert sum(component["max_points"] for component in breakdown.values()) == 100
    assert sum(component["points"] for component in breakdown.values()) == result[
        "quality_score"
    ]
    assert result["quality_score_raw"] == result["quality_score"]
    for name, component in breakdown.items():
        assert component["component"] == name
        assert 0 <= component["points"] <= component["max_points"]
        assert component["reasons"]
        assert isinstance(component["metrics"], dict)


def test_score_output_is_deterministic() -> None:
    first = score(metrics(aspect_ratio=2.5, has_window=False))
    second = score(metrics(aspect_ratio=2.5, has_window=False))
    assert first == second


def test_legacy_v1_scorer_remains_available_and_unversioned() -> None:
    result = calculate_quality_score_v1(
        metrics(),
        "VALID",
        "NOT_NEEDED",
    )
    assert result["quality_score"] == 100
    assert "quality_score_version" not in result


@pytest.mark.parametrize(
    ("value", "expected"), [(-1, 0), (0, 0), (100, 100), (101, 100)]
)
def test_quality_score_clamps_to_supported_range(value: int, expected: int) -> None:
    assert clamp_quality_score(value) == expected


def test_quality_score_does_not_change_candidate_selection() -> None:
    candidates = [
        {
            "candidate_index": 1,
            "final_validation_status": "VALID",
            "repair_status": "NOT_NEEDED",
            "quality_score": 55,
        },
        {
            "candidate_index": 2,
            "final_validation_status": "VALID",
            "repair_status": "NOT_NEEDED",
            "quality_score": 100,
        },
        {
            "candidate_index": 3,
            "final_validation_status": "VALID",
            "repair_status": "NOT_NEEDED",
            "quality_score": 99,
        },
    ]
    selected, _reason = select_best_candidate(candidates)
    assert selected is candidates[0]


def test_quality_score_module_has_no_network_or_dangerous_execution() -> None:
    source = (ROOT / "tools" / "candidate_quality_score.py").read_text(
        encoding="utf-8"
    ).lower()
    for token in (
        "urlopen",
        "requests",
        "httpx",
        "socket",
        "subprocess",
        "eval(",
        "exec(",
        "system(",
        "spawn(",
    ):
        assert token not in source
