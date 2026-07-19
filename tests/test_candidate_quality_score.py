from __future__ import annotations

from pathlib import Path

import pytest

from tools.candidate_quality_score import (
    calculate_quality_score,
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
    }
    values.update(overrides)
    return values


def score(
    quality_metrics: dict[str, object] | None = None,
    *,
    validation_status: str = "VALID",
    repair_status: str = "NOT_NEEDED",
) -> dict:
    return calculate_quality_score(
        metrics() if quality_metrics is None else quality_metrics,
        validation_status,
        repair_status,
    )


def test_valid_unrepaired_candidate_receives_complete_score() -> None:
    result = score()
    assert result["quality_score"] == 100
    assert result["quality_score_status"] == "COMPLETE"
    assert result["quality_score_warnings"] == []


def test_repaired_valid_candidate_receives_reduced_repair_points() -> None:
    result = score(repair_status="SUCCEEDED")
    assert result["quality_score"] == 95
    assert result["quality_score_breakdown"]["repair"]["points"] == 5


def test_invalid_candidate_is_not_scored() -> None:
    result = score(validation_status="INVALID")
    assert result["quality_score"] is None
    assert result["quality_score_status"] == "NOT_CALCULATED"
    assert result["quality_score_warnings"]


@pytest.mark.parametrize(
    ("has_door", "has_window", "expected_door", "expected_window"),
    [
        (True, True, 5, 5),
        (True, False, 5, 0),
        (False, True, 0, 5),
        (False, False, 0, 0),
    ],
)
def test_door_and_window_points_are_observational(
    has_door: bool,
    has_window: bool,
    expected_door: int,
    expected_window: int,
) -> None:
    result = score(metrics(has_door=has_door, has_window=has_window))
    assert result["quality_score_breakdown"]["door"]["points"] == expected_door
    assert result["quality_score_breakdown"]["window"]["points"] == expected_window


@pytest.mark.parametrize(
    ("aspect_ratio", "expected_points"),
    [(1.0, 5), (2.0, 5), (3.0, 2), (3.01, -5)],
)
def test_aspect_ratio_boundaries(
    aspect_ratio: float, expected_points: int
) -> None:
    result = score(metrics(aspect_ratio=aspect_ratio))
    assert result["quality_score_breakdown"]["aspect_ratio"]["points"] == expected_points


def test_aspect_ratio_below_one_is_not_corrected() -> None:
    result = score(metrics(aspect_ratio=0.5))
    assert result["quality_score_breakdown"]["aspect_ratio"]["points"] == 0
    assert result["quality_score_status"] == "PARTIAL"
    assert result["quality_score_warnings"]


@pytest.mark.parametrize(
    ("opening_ratio", "expected_points"),
    [(0.0, 0), (0.40, 5), (0.60, 0), (0.6001, -10)],
)
def test_opening_ratio_boundaries(
    opening_ratio: float, expected_points: int
) -> None:
    result = score(metrics(opening_to_wall_area_ratio=opening_ratio))
    assert result["quality_score_breakdown"]["opening_ratio"]["points"] == expected_points


def test_null_scored_metrics_produce_partial_score_and_warnings() -> None:
    result = score(
        metrics(aspect_ratio=None, opening_to_wall_area_ratio=None)
    )
    assert result["quality_score"] == 90
    assert result["quality_score_status"] == "PARTIAL"
    assert len(result["quality_score_warnings"]) == 2


@pytest.mark.parametrize("footprint_area", [0, None])
def test_missing_or_non_positive_footprint_is_partial(
    footprint_area: float | None,
) -> None:
    result = score(metrics(footprint_area=footprint_area))
    assert result["quality_score_status"] == "PARTIAL"
    assert result["quality_score_breakdown"]["footprint"]["points"] == 0
    assert result["quality_score_warnings"]


def test_unknown_repair_status_is_partial_without_assumed_points() -> None:
    result = score(repair_status="UNKNOWN")
    assert result["quality_score_status"] == "PARTIAL"
    assert result["quality_score_breakdown"]["repair"]["points"] == 0
    assert result["quality_score_warnings"]


@pytest.mark.parametrize(
    ("value", "expected"), [(-1, 0), (0, 0), (100, 100), (101, 100)]
)
def test_quality_score_clamps_to_supported_range(value: int, expected: int) -> None:
    assert clamp_quality_score(value) == expected


def test_breakdown_points_sum_to_complete_score() -> None:
    result = score()
    points = sum(
        component["points"]
        for component in result["quality_score_breakdown"].values()
    )
    assert points == result["quality_score"]


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
