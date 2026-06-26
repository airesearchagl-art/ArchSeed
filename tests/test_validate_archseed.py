from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tools.validate_archseed import ValidationError, validate_archseed


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PATH = ROOT / "examples" / "simple_house.v0.1.json"
RUBY_LOADER_PATH = ROOT / "sketchup" / "archseed_loader.rb"


def load_sample() -> dict:
    return json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))


def test_sample_json_is_valid() -> None:
    data = load_sample()
    assert validate_archseed(data) == data


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
