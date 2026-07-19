from __future__ import annotations

import json
from pathlib import Path

import pytest

import tools.repair_archseed_json as repair_module
from tools.generate_with_lmstudio import extract_json_object
from tools.repair_archseed_json import build_repair_prompt, main as repair_main


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "llm_config.example.json"
REPAIR_CLI_PATH = ROOT / "tools" / "repair_archseed_json.py"


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def invalid_archseed_json() -> dict:
    return {
        "schemaVersion": "archseed.v0.1",
        "units": "mm",
        "project": {"name": "Repair Input"},
        "building": {
            "footprint": {"width": -1, "depth": 6000},
            "levels": [{"name": "Level 1", "height": 3000}],
        },
    }


def valid_archseed_json() -> dict:
    data = invalid_archseed_json()
    data["building"]["footprint"]["width"] = 8000
    return data


def test_repair_cli_exists_and_prompt_is_constrained() -> None:
    assert REPAIR_CLI_PATH.is_file()
    prompt = build_repair_prompt(
        invalid_archseed_json(),
        "$.building.footprint.width must be > 0",
        load_config(),
    )

    assert "ArchSeed JSON only" in prompt
    assert "Do not use Markdown" in prompt
    assert "Do not return SketchUp Ruby code" in prompt
    assert "Fix only the reported validation error" in prompt
    assert "Preserve the original building intent and existing openings" in prompt


@pytest.mark.parametrize(
    "response",
    [
        '{"schemaVersion":"archseed.v0.1"}',
        '```json\n{"schemaVersion":"archseed.v0.1"}\n```',
        'Result: {"schemaVersion":"archseed.v0.1"} done.',
    ],
)
def test_repair_uses_json_extraction_for_supported_response_shapes(
    response: str,
) -> None:
    assert extract_json_object(response) == {"schemaVersion": "archseed.v0.1"}


def test_repair_cli_saves_and_validates_local_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "invalid.json"
    output_path = tmp_path / "repaired.json"
    input_path.write_text(json.dumps(invalid_archseed_json()), encoding="utf-8")

    def fake_request_json(
        _host: str,
        _port: int,
        path: str,
        *,
        method: str,
        payload: dict | None = None,
        timeout: float,
    ) -> dict:
        if path.endswith("/models"):
            return {"data": [{"id": "local-test-model"}]}
        assert method == "POST"
        assert payload is not None
        return {
            "choices": [
                {"message": {"content": json.dumps(valid_archseed_json())}}
            ]
        }

    monkeypatch.setattr(repair_module, "request_json", fake_request_json)
    result = repair_main(
        [
            str(input_path),
            "$.building.footprint.width must be > 0",
            "--output",
            str(output_path),
        ]
    )

    assert result == 0
    assert json.loads(output_path.read_text(encoding="utf-8")) == valid_archseed_json()


def test_repair_rejects_non_local_config_before_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config()
    config["base_url"] = "https://example.com/v1"
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    input_path = tmp_path / "invalid.json"
    input_path.write_text(json.dumps(invalid_archseed_json()), encoding="utf-8")

    def fail_request(*_args: object, **_kwargs: object) -> dict:
        raise AssertionError("external request must not be attempted")

    monkeypatch.setattr(repair_module, "request_json", fail_request)
    assert repair_main(
        [
            str(input_path),
            "validation error",
            "--config",
            str(config_path),
            "--output",
            str(tmp_path / "out.json"),
        ]
    ) == 1


def test_repair_cli_has_no_cloud_secret_or_dangerous_api() -> None:
    source = REPAIR_CLI_PATH.read_text(encoding="utf-8").lower()
    forbidden_tokens = [
        "requests",
        "httpx",
        "urlopen",
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
        "api.openai.com",
        "api.anthropic.com",
    ]
    for token in forbidden_tokens:
        assert token not in source

    assert "/chat/completions" in source
    assert "parse_local_base_url" in source
