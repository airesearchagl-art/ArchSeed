from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.candidate_quality import calculate_candidate_quality
from tools.generate_candidates_with_lmstudio import select_best_candidate


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


def load_example(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "name",
    [
        "simple_house.v0.1.json",
        "small_office.v0.1.json",
        "two_story_box.v0.1.json",
        "compact_house.v0.1.json",
        "house_with_openings.v0.1.json",
    ],
)
def test_quality_metrics_are_calculated_for_existing_samples(name: str) -> None:
    result = calculate_candidate_quality(
        load_example(name), repaired=False, validation_status="VALID"
    )
    assert result["quality_metrics_status"] == "COMPLETE"
    assert result["quality_metrics_warnings"] == []
    assert result["quality_metrics"]["footprint_area"] is not None


def test_footprint_area_and_aspect_ratio_use_schema_millimeters() -> None:
    result = calculate_candidate_quality(
        load_example("simple_house.v0.1.json"),
        repaired=False,
        validation_status="VALID",
    )
    metrics = result["quality_metrics"]
    assert metrics["footprint_area"] == pytest.approx(38_880_000.0)
    assert metrics["aspect_ratio"] == pytest.approx(4 / 3)
    assert metrics["wall_count"] == 8


def test_opening_counts_and_area_are_deterministic() -> None:
    result = calculate_candidate_quality(
        load_example("house_with_openings.v0.1.json"),
        repaired=True,
        validation_status="VALID",
    )
    metrics = result["quality_metrics"]
    wall_area = 2 * (7200 + 5400) * (3000 - 180)
    assert metrics["opening_count"] == 3
    assert metrics["door_count"] == 1
    assert metrics["window_count"] == 2
    assert metrics["total_opening_area"] == pytest.approx(5_850_000.0)
    assert metrics["opening_to_wall_area_ratio"] == pytest.approx(
        5_850_000.0 / wall_area
    )
    assert metrics["has_door"] is True
    assert metrics["has_window"] is True
    assert metrics["repaired"] is True


def test_wall_area_sums_generated_clear_height_across_levels() -> None:
    data = load_example("simple_house.v0.1.json")
    data["building"]["openings"] = [
        {
            "type": "window",
            "level": "Level 1",
            "wall": "south",
            "offset_mm": 1000,
            "width_mm": 1000,
            "height_mm": 1000,
            "sill_height_mm": 900,
        }
    ]

    result = calculate_candidate_quality(
        data, repaired=False, validation_status="VALID"
    )
    expected_wall_area = 2 * (7200 + 5400) * ((3000 - 180) + (2800 - 180))
    assert result["quality_metrics"][
        "opening_to_wall_area_ratio"
    ] == pytest.approx(1_000_000 / expected_wall_area)


def test_wall_area_uses_validator_default_slab_thickness_when_omitted() -> None:
    data = load_example("simple_house.v0.1.json")
    data["building"].pop("slabThickness")
    data["building"]["openings"] = [
        {
            "type": "door",
            "level": "Level 1",
            "wall": "south",
            "offset_mm": 1000,
            "width_mm": 1000,
            "height_mm": 2000,
        }
    ]

    result = calculate_candidate_quality(
        data, repaired=False, validation_status="VALID"
    )
    expected_wall_area = 2 * (7200 + 5400) * ((3000 - 180) + (2800 - 180))
    assert result["quality_metrics"][
        "opening_to_wall_area_ratio"
    ] == pytest.approx(2_000_000 / expected_wall_area)


def test_empty_openings_have_zero_complete_metrics() -> None:
    data = load_example("simple_house.v0.1.json")
    data["building"]["openings"] = []

    result = calculate_candidate_quality(
        data, repaired=False, validation_status="VALID"
    )
    metrics = result["quality_metrics"]
    assert metrics["opening_count"] == 0
    assert metrics["total_opening_area"] == 0
    assert metrics["opening_to_wall_area_ratio"] == 0
    assert result["quality_metrics_status"] == "COMPLETE"


def test_roof_parapet_height_is_not_added_to_gross_wall_area() -> None:
    data = load_example("simple_house.v0.1.json")
    data["building"]["openings"] = [
        {
            "type": "window",
            "level": "Level 2",
            "wall": "north",
            "offset_mm": 1000,
            "width_mm": 1000,
            "height_mm": 1000,
            "sill_height_mm": 900,
        }
    ]
    data["building"]["roof"]["parapetHeight"] = 10_000

    result = calculate_candidate_quality(
        data, repaired=False, validation_status="VALID"
    )
    expected_wall_area = 2 * (7200 + 5400) * ((3000 - 180) + (2800 - 180))
    assert result["quality_metrics"][
        "opening_to_wall_area_ratio"
    ] == pytest.approx(1_000_000 / expected_wall_area)


def test_zero_generated_wall_area_returns_null_ratio_and_warning() -> None:
    data = load_example("compact_house.v0.1.json")
    data["building"]["levels"][0]["height"] = data["building"]["slabThickness"]
    data["building"]["openings"] = []

    result = calculate_candidate_quality(
        data, repaired=False, validation_status="VALID"
    )
    assert result["quality_metrics"]["opening_to_wall_area_ratio"] is None
    assert result["quality_metrics_status"] == "PARTIAL"
    assert result["quality_metrics_warnings"]


def test_missing_data_does_not_raise_and_records_warnings() -> None:
    result = calculate_candidate_quality(
        {"building": {"footprint": {}, "levels": [], "openings": [{}]}},
        repaired=False,
        validation_status="VALID",
    )
    assert result["quality_metrics_status"] == "PARTIAL"
    assert result["quality_metrics"]["footprint_area"] is None
    assert result["quality_metrics"]["total_opening_area"] is None
    assert len(result["quality_metrics_warnings"]) >= 3


def test_invalid_candidate_is_not_force_scored() -> None:
    result = calculate_candidate_quality(
        None, repaired=False, validation_status="INVALID"
    )
    assert result["quality_metrics_status"] == "NOT_CALCULATED"
    assert result["quality_metrics"]["footprint_area"] is None
    assert result["quality_metrics_warnings"]


def test_quality_metrics_do_not_change_candidate_selection() -> None:
    candidates = [
        {
            "candidate_index": 1,
            "final_validation_status": "VALID",
            "repair_status": "SUCCEEDED",
            "quality_metrics": {"footprint_area": 99_000_000.0},
        },
        {
            "candidate_index": 2,
            "final_validation_status": "VALID",
            "repair_status": "NOT_NEEDED",
            "quality_metrics": {"footprint_area": 1.0},
        },
        {
            "candidate_index": 3,
            "final_validation_status": "VALID",
            "repair_status": "NOT_NEEDED",
            "quality_metrics": {"footprint_area": 999_000_000.0},
        },
    ]
    selected, _reason = select_best_candidate(candidates)
    assert selected is candidates[1]


def test_quality_module_has_no_network_or_dangerous_execution() -> None:
    source = (ROOT / "tools" / "candidate_quality.py").read_text(
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
