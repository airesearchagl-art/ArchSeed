from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tools.validate_archseed import ValidationError, validate_archseed


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PATH = ROOT / "examples" / "simple_house.v0.1.json"
SAMPLE_PATHS = (
    SAMPLE_PATH,
    ROOT / "examples" / "small_office.v0.1.json",
    ROOT / "examples" / "two_story_box.v0.1.json",
    ROOT / "examples" / "compact_house.v0.1.json",
)
RUBY_LOADER_PATH = ROOT / "sketchup" / "archseed_loader.rb"


def load_sample(path: Path = SAMPLE_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("sample_path", SAMPLE_PATHS, ids=lambda path: path.stem)
def test_sample_json_is_valid(sample_path: Path) -> None:
    data = load_sample(sample_path)
    assert validate_archseed(data) == data


@pytest.mark.parametrize("sample_path", SAMPLE_PATHS, ids=lambda path: path.stem)
def test_sample_json_has_minimum_building_structure(sample_path: Path) -> None:
    assert sample_path.is_file()
    data = load_sample(sample_path)
    assert data["project"]["name"].strip()
    assert data["building"]["levels"]
    assert data["building"]["footprint"]["width"] > 0
    assert data["building"]["footprint"]["depth"] > 0


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("schemaVersion",), "archseed.v9"),
        (("units",), "inch"),
        (("building", "footprint", "width"), -1),
        (("building", "levels", 0, "height"), 0),
    ],
)
def test_invalid_core_values_are_rejected(path: tuple, value: object) -> None:
    data = load_sample()
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(ValidationError):
        validate_archseed(data)


def test_unknown_keys_are_rejected() -> None:
    data = load_sample()
    data["building"]["unsafeRuby"] = "puts :nope"

    with pytest.raises(ValidationError, match="unknown key"):
        validate_archseed(data)


def test_validation_does_not_mutate_input() -> None:
    data = load_sample()
    before = copy.deepcopy(data)
    validate_archseed(data)
    assert data == before


def test_sketchup_loader_avoids_forbidden_execution_apis() -> None:
    source = RUBY_LOADER_PATH.read_text(encoding="utf-8")
    forbidden_tokens = [
        "eval(",
        "instance_eval",
        "module_eval",
        "class_eval",
        "system(",
        "exec(",
        "spawn(",
        "`",
    ]
    for token in forbidden_tokens:
        assert token not in source


def test_sketchup_loader_builds_named_editable_geometry_groups() -> None:
    source = RUBY_LOADER_PATH.read_text(encoding="utf-8")
    expected_group_names = [
        "ArchSeed Building - #{project_name}",
        "ArchSeed #{level_name}",
        "ArchSeed Floor - #{level_name}",
        "ArchSeed Walls - #{level_name}",
        "ArchSeed Roof",
    ]
    for name in expected_group_names:
        assert name in source

    assert "level_group = add_named_group(building_group.entities" in source
    assert "floor_group = add_named_group(level_group.entities" in source
    assert "walls_group = add_named_group(level_group.entities" in source
    assert "roof_group = add_named_group(building_group.entities" in source
    assert "add_slab(floor_group.entities" in source
    assert "add_walls(walls_group.entities" in source
    assert "add_roof(roof_group.entities" in source


def test_sketchup_loader_constants_are_reload_safe() -> None:
    source = RUBY_LOADER_PATH.read_text(encoding="utf-8")
    constants = {
        "MM_TO_INCH": "1.0 / 25.4",
        "DEFAULT_WALL_THICKNESS_MM": "150.0",
        "DEFAULT_SLAB_THICKNESS_MM": "180.0",
        "DEFAULT_PARAPET_HEIGHT_MM": "300.0",
    }
    for constant, value in constants.items():
        definition = f"{constant} = {value} unless const_defined?(:{constant}, false)"
        assert definition in source


def test_sketchup_loader_geometry_dimension_rules_are_explicit() -> None:
    source = RUBY_LOADER_PATH.read_text(encoding="utf-8")
    expected_rules = [
        "floor_bottom_z = level_bottom_z",
        "floor_top_z = floor_bottom_z + slab",
        "wall_bottom_z = floor_top_z",
        "wall_top_z = level_bottom_z + story_height",
        "wall_height = wall_top_z - wall_bottom_z",
        "roof_bottom_z = level_bottom_z",
        "roof_top_z = roof_bottom_z + slab",
    ]
    for rule in expected_rules:
        assert rule in source

    assert "height must exceed slab thickness" in source
