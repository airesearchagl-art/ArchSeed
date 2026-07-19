from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import tools.generate_with_lmstudio as lmstudio_generate
from tools.generate_with_lmstudio import (
    JSONExtractionError,
    extract_json_object,
    generate_with_lmstudio,
    main as generate_with_lmstudio_main,
    select_model_from_list,
)
from tools.validate_archseed import validate_archseed


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_CONFIG_PATH = ROOT / "config" / "llm_config.example.json"
LMSTUDIO_GENERATOR_PATH = ROOT / "tools" / "generate_with_lmstudio.py"


def load_example_config() -> dict:
    return json.loads(EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8"))


def test_lmstudio_generator_cli_exists() -> None:
    assert LMSTUDIO_GENERATOR_PATH.is_file()


def test_extract_json_object_accepts_raw_json() -> None:
    candidate = extract_json_object('{"schemaVersion":"archseed.v0.1"}')
    assert candidate == {"schemaVersion": "archseed.v0.1"}


def test_extract_json_object_accepts_fenced_json() -> None:
    candidate = extract_json_object(
        """
```json
{"schemaVersion":"archseed.v0.1"}
```
"""
    )
    assert candidate == {"schemaVersion": "archseed.v0.1"}


def test_extract_json_object_accepts_surrounding_text() -> None:
    candidate = extract_json_object(
        'Here is the JSON: {"schemaVersion":"archseed.v0.1"}'
    )
    assert candidate == {"schemaVersion": "archseed.v0.1"}


def test_extract_json_object_rejects_missing_json() -> None:
    with pytest.raises(JSONExtractionError):
        extract_json_object("not json")


def test_select_model_prefers_chat_or_instruct_model_names() -> None:
    models = [
        {"id": "qwen/qwen3.6-27b"},
        {"id": "text-embedding-nomic-embed-text-v1.5"},
        {"id": "qwen3-coder-30b-a3b-instruct"},
    ]

    assert select_model_from_list(models) == "qwen3-coder-30b-a3b-instruct"


def test_lmstudio_generation_rejects_non_local_base_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_example_config()
    config["base_url"] = "https://example.com/v1"
    config_path = tmp_path / "llm_config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    def fail_request(*_args: object, **_kwargs: object) -> dict:
        raise AssertionError("request_json must not be called for external URLs")

    monkeypatch.setattr(lmstudio_generate, "request_json", fail_request)
    assert (
        generate_with_lmstudio_main(
            [
                "small office",
                "--config",
                str(config_path),
                "--output-json",
                str(tmp_path / "generated" / "out.v0.1.json"),
                "--output-session",
                str(tmp_path / "draft_sessions" / "out.session.json"),
            ]
        )
        == 1
    )


def test_lmstudio_generation_saves_valid_json_and_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []
    valid_json = {
        "schemaVersion": "archseed.v0.1",
        "units": "mm",
        "project": {"name": "LLM Studio Small Office"},
        "building": {
            "footprint": {"width": 9000, "depth": 6000},
            "levels": [{"name": "Office Level", "height": 3300}],
            "wallThickness": 180,
            "slabThickness": 200,
            "roof": {"type": "flat", "parapetHeight": 450},
            "openings": [
                {
                    "type": "window",
                    "level": 0,
                    "wall": "south",
                    "offset_mm": 1000,
                    "width_mm": 1200,
                    "height_mm": 1200,
                    "sill_height_mm": 900,
                }
            ],
        },
    }

    def fake_request_json(
        _host: str,
        _port: int,
        path: str,
        *,
        method: str,
        payload: dict | None = None,
        timeout: float,
    ) -> dict:
        calls.append((method, path))
        assert timeout == 180.0
        if path.endswith("/models"):
            return {"data": [{"id": "local-test-model"}]}
        assert path.endswith("/chat/completions")
        assert payload is not None
        assert payload["model"] == "local-test-model"
        assert payload["stream"] is False
        assert "Return ArchSeed JSON only." in payload["messages"][0]["content"]
        return {
            "choices": [
                {
                    "message": {
                        "content": "```json\n"
                        + json.dumps(valid_json)
                        + "\n```"
                    }
                }
            ]
        }

    monkeypatch.setattr(lmstudio_generate, "request_json", fake_request_json)
    output_json = tmp_path / "generated" / "lmstudio.v0.1.json"
    output_session = tmp_path / "draft_sessions" / "lmstudio.session.json"

    session = generate_with_lmstudio(
        "small office with openings",
        config_path=EXAMPLE_CONFIG_PATH,
        output_json=output_json,
        output_session=output_session,
    )

    generated = json.loads(output_json.read_text(encoding="utf-8"))
    saved_session = json.loads(output_session.read_text(encoding="utf-8"))
    assert validate_archseed(generated) == generated
    assert session == saved_session
    assert saved_session["validation_status"] == "VALID"
    assert saved_session["validation_message"].startswith("VALID:")
    assert saved_session["sketchup_import_command"].startswith(
        "ArchSeed.import_json("
    )
    assert saved_session["generator_mode"] == "lmstudio_local_chat_completion"
    assert saved_session["repair_attempts"] == 0
    assert saved_session["repair_status"] == "NOT_NEEDED"
    assert saved_session["repair_messages"] == []
    assert saved_session["final_validation_status"] == "VALID"
    assert calls == [("GET", "/v1/models"), ("POST", "/v1/chat/completions")]


def test_lmstudio_generation_model_override_skips_models_endpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, str]] = []
    valid_json = {
        "schemaVersion": "archseed.v0.1",
        "units": "mm",
        "project": {"name": "Override Model"},
        "building": {
            "footprint": {"width": 7200, "depth": 5400},
            "levels": [{"name": "Level 1", "height": 3000}],
        },
    }

    def fake_request_json(
        _host: str,
        _port: int,
        path: str,
        *,
        method: str,
        payload: dict | None = None,
        timeout: float,
    ) -> dict:
        assert payload is not None
        calls.append((method, path, payload["model"]))
        return {
            "choices": [
                {"message": {"content": json.dumps(valid_json)}}
            ]
        }

    monkeypatch.setattr(lmstudio_generate, "request_json", fake_request_json)
    result = generate_with_lmstudio(
        "simple house",
        config_path=EXAMPLE_CONFIG_PATH,
        output_json=tmp_path / "generated" / "override.v0.1.json",
        output_session=tmp_path / "draft_sessions" / "override.session.json",
        model_override="local-chat-model",
    )

    assert result["validation_status"] == "VALID"
    assert calls == [("POST", "/v1/chat/completions", "local-chat-model")]


def test_lmstudio_generation_returns_nonzero_on_validation_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid_json = copy.deepcopy(
        {
            "schemaVersion": "archseed.v0.1",
            "units": "mm",
            "project": {"name": "Invalid"},
            "building": {
                "footprint": {"width": -1, "depth": 6000},
                "levels": [{"name": "Level 1", "height": 3000}],
            },
        }
    )

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
        return {
            "choices": [
                {"message": {"content": json.dumps(invalid_json)}}
            ]
        }

    monkeypatch.setattr(lmstudio_generate, "request_json", fake_request_json)
    output_json = tmp_path / "generated" / "invalid.v0.1.json"
    output_session = tmp_path / "draft_sessions" / "invalid.session.json"

    result = generate_with_lmstudio_main(
        [
            "invalid building",
            "--output-json",
            str(output_json),
            "--output-session",
            str(output_session),
        ]
    )

    assert result == 1
    assert output_json.is_file()
    session = json.loads(output_session.read_text(encoding="utf-8"))
    assert session["validation_status"] == "INVALID"
    assert session["validation_message"].startswith("INVALID:")
    assert session["sketchup_import_command"].startswith("ArchSeed.import_json(")
    assert session["repair_attempts"] == 0
    assert session["repair_status"] == "NOT_REQUESTED"
    assert session["final_validation_status"] == "INVALID"


def test_lmstudio_generation_repairs_invalid_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid_json = {
        "schemaVersion": "archseed.v0.1",
        "units": "mm",
        "project": {"name": "Repair Test"},
        "building": {
            "footprint": {"width": -1, "depth": 6000},
            "levels": [{"name": "Level 1", "height": 3000}],
        },
    }
    repaired_json = copy.deepcopy(invalid_json)
    repaired_json["building"]["footprint"]["width"] = 8000
    completion_count = 0

    def fake_request_json(
        _host: str,
        _port: int,
        path: str,
        *,
        method: str,
        payload: dict | None = None,
        timeout: float,
    ) -> dict:
        nonlocal completion_count
        if path.endswith("/models"):
            return {"data": [{"id": "local-test-model"}]}
        completion_count += 1
        assert method == "POST"
        assert payload is not None
        if completion_count == 1:
            return {
                "choices": [
                    {"message": {"content": json.dumps(invalid_json)}}
                ]
            }
        repair_prompt = payload["messages"][0]["content"]
        assert "Fix only the reported validation error" in repair_prompt
        assert "Do not return SketchUp Ruby code" in repair_prompt
        return {
            "choices": [
                {"message": {"content": f"```json\n{json.dumps(repaired_json)}\n```"}}
            ]
        }

    monkeypatch.setattr(lmstudio_generate, "request_json", fake_request_json)
    output_json = tmp_path / "generated" / "repaired.v0.1.json"
    output_session = tmp_path / "draft_sessions" / "repaired.session.json"

    session = generate_with_lmstudio(
        "repair test",
        config_path=EXAMPLE_CONFIG_PATH,
        output_json=output_json,
        output_session=output_session,
        repair_attempts=1,
    )

    assert validate_archseed(json.loads(output_json.read_text(encoding="utf-8")))
    assert session["validation_status"] == "VALID"
    assert session["repair_attempts"] == 1
    assert session["repair_status"] == "SUCCEEDED"
    assert session["final_validation_status"] == "VALID"
    assert any("repaired JSON is VALID" in item for item in session["repair_messages"])
    assert completion_count == 2


def test_lmstudio_generation_records_failed_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid_json = {
        "schemaVersion": "archseed.v0.1",
        "units": "mm",
        "project": {"name": "Still Invalid"},
        "building": {
            "footprint": {"width": -1, "depth": 6000},
            "levels": [{"name": "Level 1", "height": 3000}],
        },
    }

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
        return {
            "choices": [
                {"message": {"content": json.dumps(invalid_json)}}
            ]
        }

    monkeypatch.setattr(lmstudio_generate, "request_json", fake_request_json)
    output_session = tmp_path / "draft_sessions" / "failed.session.json"
    result = generate_with_lmstudio_main(
        [
            "repair failure",
            "--output-json",
            str(tmp_path / "generated" / "failed.v0.1.json"),
            "--output-session",
            str(output_session),
            "--repair-attempts",
            "1",
        ]
    )

    assert result == 1
    session = json.loads(output_session.read_text(encoding="utf-8"))
    assert session["repair_attempts"] == 1
    assert session["repair_status"] == "FAILED"
    assert session["final_validation_status"] == "INVALID"
    assert any("remains invalid" in item for item in session["repair_messages"])


def test_lmstudio_generator_has_no_cloud_secret_or_dangerous_api() -> None:
    source = LMSTUDIO_GENERATOR_PATH.read_text(encoding="utf-8").lower()
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
