from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.create_invalid_archseed_json import (
    CORRUPTION_MODES,
    corrupt_archseed_json,
    main as create_invalid_main,
)
from tools.validate_archseed import ValidationError, validate_archseed


ROOT = Path(__file__).resolve().parents[1]
HELPER_PATH = ROOT / "tools" / "create_invalid_archseed_json.py"
SAMPLE_PATH = ROOT / "examples" / "small_office.v0.1.json"
README_PATH = ROOT / "README.md"
GITIGNORE_PATH = ROOT / ".gitignore"


def load_sample() -> dict:
    return json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))


def test_invalid_json_helper_exists() -> None:
    assert HELPER_PATH.is_file()


@pytest.mark.parametrize("corruption", CORRUPTION_MODES)
def test_each_corruption_mode_produces_invalid_json(corruption: str) -> None:
    corrupted = corrupt_archseed_json(load_sample(), corruption)

    with pytest.raises(ValidationError):
        validate_archseed(corrupted)


def test_invalid_json_cli_writes_expected_fixture(tmp_path: Path) -> None:
    output_path = tmp_path / "generated" / "invalid.v0.1.json"

    assert create_invalid_main([str(SAMPLE_PATH), "--output", str(output_path)]) == 0
    generated = json.loads(output_path.read_text(encoding="utf-8"))
    with pytest.raises(ValidationError):
        validate_archseed(generated)


def test_invalid_json_cli_rejects_invalid_source(tmp_path: Path) -> None:
    source_path = tmp_path / "already-invalid.json"
    source = load_sample()
    source["building"]["footprint"]["width"] = -1
    source_path.write_text(json.dumps(source), encoding="utf-8")

    assert create_invalid_main(
        [str(source_path), "--output", str(tmp_path / "out.json")]
    ) == 1


def test_readme_contains_repair_smoke_test_commands() -> None:
    readme = README_PATH.read_text(encoding="utf-8")

    assert "tools/create_invalid_archseed_json.py" in readme
    assert "generated/invalid_small_office.v0.1.json" in readme
    assert "tools/repair_archseed_json.py" in readme
    assert "--validation-error" in readme
    assert "generated/repaired_small_office.v0.1.json" in readme


def test_readme_contains_repaired_json_import_check() -> None:
    readme = README_PATH.read_text(encoding="utf-8")

    assert (
        "tools/print_sketchup_import_command.py "
        "generated/repaired_small_office.v0.1.json"
    ) in readme
    assert 'ArchSeed.import_json("...")' in readme
    assert "Do not\npaste a `file:///...` URL" in readme
    assert "does not guarantee architectural quality" in readme


def test_generated_outputs_remain_ignored() -> None:
    patterns = GITIGNORE_PATH.read_text(encoding="utf-8").splitlines()

    assert "generated/*.json" in patterns
    assert "draft_sessions/*.json" in patterns


def test_invalid_json_helper_has_no_dangerous_api() -> None:
    source = HELPER_PATH.read_text(encoding="utf-8").lower()
    forbidden_tokens = [
        "requests",
        "httpx",
        "urllib",
        "socket",
        "subprocess",
        "eval(",
        "exec(",
        "system(",
        "spawn(",
        ".env",
        "api_key",
        "authorization",
        "bearer ",
    ]
    for token in forbidden_tokens:
        assert token not in source
