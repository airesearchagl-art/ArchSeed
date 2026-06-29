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
    ROOT / "examples" / "house_with_openings.v0.1.json",
)
OPENINGS_SAMPLE_PATH = ROOT / "examples" / "house_with_openings.v0.1.json"
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


def test_openings_sample_uses_supported_minimum_structure() -> None:
    data = load_sample(OPENINGS_SAMPLE_PATH)
    openings = data["building"]["openings"]
    assert {opening["type"] for opening in openings} == {"window", "door"}
    assert {opening["wall"] for opening in openings} <= {
        "north",
        "south",
        "east",
        "west",
    }
    assert any(isinstance(opening["level"], str) for opening in openings)
    assert any(isinstance(opening["level"], int) for opening in openings)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("wall", "ceiling", "wall must be"),
        ("level", 9, "level index is out of range"),
        ("offset_mm", 7000, "extends beyond its wall"),
        ("height_mm", 4000, "extends above the generated wall"),
    ],
)
def test_invalid_opening_values_are_rejected(
    field: str, value: object, message: str
) -> None:
    data = load_sample(OPENINGS_SAMPLE_PATH)
    data["building"]["openings"][0][field] = value

    with pytest.raises(ValidationError, match=message):
        validate_archseed(data)


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
    assert "floor_group = add_named_group(" in source
    assert "walls_group = add_named_group(" in source
    assert "roof_group = add_named_group(" in source
    assert "level_group.entities," in source
    assert "building_group.entities," in source
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
        "DEFAULT_WINDOW_SILL_HEIGHT_MM": "900.0",
        "OPENING_INDICATOR_OFFSET_MM": "2.0",
        "FLOOR_TAG_NAME": "'ArchSeed Floor'",
        "WALLS_TAG_NAME": "'ArchSeed Walls'",
        "ROOF_TAG_NAME": "'ArchSeed Roof'",
        "OPENINGS_TAG_NAME": "'ArchSeed Openings'",
        "FLOOR_MATERIAL_NAME": "'ArchSeed Floor Material'",
        "WALL_MATERIAL_NAME": "'ArchSeed Wall Material'",
        "ROOF_MATERIAL_NAME": "'ArchSeed Roof Material'",
        "WINDOW_MATERIAL_NAME": "'ArchSeed Window Material'",
        "DOOR_MATERIAL_NAME": "'ArchSeed Door Material'",
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


def test_sketchup_loader_assigns_reusable_tags_to_element_groups() -> None:
    source = RUBY_LOADER_PATH.read_text(encoding="utf-8")
    assert "tags[name] || tags.add(name)" in source
    assert "group.layer = tag if tag" in source
    assert '"ArchSeed Building - #{project_name}", untagged' in source
    assert '"ArchSeed #{level_name}", untagged' in source
    assert '"ArchSeed Floor - #{level_name}",\n        floor_tag,' in source
    assert '"ArchSeed Walls - #{level_name}",\n        walls_tag,' in source
    assert "'ArchSeed Roof',\n      roof_tag," in source


def test_sketchup_loader_builds_simple_opening_indicators() -> None:
    source = RUBY_LOADER_PATH.read_text(encoding="utf-8")
    expected_source_fragments = [
        '"ArchSeed Openings - #{level_name}"',
        '"ArchSeed #{label} - #{level_name}"',
        "add_opening_indicator(",
        "opening_points(",
        "validate_openings!(building, levels, footprint)",
        "resolve_level_index(levels, opening.fetch('level')",
        "find_or_create_tag(model, OPENINGS_TAG_NAME)",
        "face.material = material",
        "face.back_material = material",
    ]
    for fragment in expected_source_fragments:
        assert fragment in source

    opening_method = source[
        source.index("def add_opening_indicator") : source.index("def opening_points")
    ]
    assert "pushpull" not in opening_method


def test_sketchup_loader_defines_and_assigns_stable_materials() -> None:
    source = RUBY_LOADER_PATH.read_text(encoding="utf-8")
    material_names = [
        "ArchSeed Floor Material",
        "ArchSeed Wall Material",
        "ArchSeed Roof Material",
        "ArchSeed Window Material",
        "ArchSeed Door Material",
    ]
    for name in material_names:
        assert name in source

    expected_assignments = [
        "floor_tag,\n        floor_material",
        "walls_tag,\n        wall_material",
        "roof_tag,\n      roof_material",
        '"ArchSeed #{label} - #{level_name}",\n      tag,\n      material',
    ]
    for assignment in expected_assignments:
        assert assignment in source

    assert "MATERIAL_STYLES = {" in source
    assert "}.freeze unless const_defined?(:MATERIAL_STYLES, false)" in source
    assert "model.materials[name] || model.materials.add(name)" in source
    assert "group.material = material if material" in source
    assert "material.color = Sketchup::Color.new(*color)" in source
    assert "material.alpha = alpha" in source
