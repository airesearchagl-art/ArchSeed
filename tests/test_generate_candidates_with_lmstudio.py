from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

import tools.generate_candidates_with_lmstudio as candidates_module
from tools.generate_candidates_with_lmstudio import (
    CandidateGenerationError,
    candidate_count,
    generate_candidates,
    select_best_candidate,
)
from tools.validate_archseed import ValidationError
from tools.validate_llm_config import ConfigValidationError


ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = ROOT / "tools" / "generate_candidates_with_lmstudio.py"
CONFIG_PATH = ROOT / "config" / "llm_config.example.json"
GITIGNORE_PATH = ROOT / ".gitignore"


def candidate(
    index: int,
    *,
    final_status: str = "VALID",
    repair_status: str = "NOT_NEEDED",
) -> dict:
    return {
        "candidate_index": index,
        "json_path": f"candidate_{index:02d}.v0.1.json",
        "final_validation_status": final_status,
        "repair_status": repair_status,
    }


def valid_archseed_json(name: str) -> dict:
    return {
        "schemaVersion": "archseed.v0.1",
        "project": {"name": name},
        "units": "mm",
        "building": {
            "footprint": {"width": 8000, "depth": 6000},
            "levels": [{"name": "Level 1", "height": 3000}],
            "roof": {"type": "flat", "parapetHeight": 300},
        },
    }


def test_multiple_candidate_cli_exists() -> None:
    assert CLI_PATH.is_file()


@pytest.mark.parametrize("value", ["1", "3", "5"])
def test_candidate_count_accepts_supported_range(value: str) -> None:
    assert candidate_count(value) == int(value)


@pytest.mark.parametrize("value", ["0", "6", "many"])
def test_candidate_count_rejects_unsupported_values(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        candidate_count(value)


def test_best_candidate_requires_valid_status() -> None:
    selected, reason = select_best_candidate(
        [candidate(1, final_status="INVALID"), candidate(2, final_status="INVALID")]
    )
    assert selected is None
    assert "No candidate" in reason


def test_best_candidate_prefers_valid_candidate() -> None:
    selected, _reason = select_best_candidate(
        [candidate(1, final_status="INVALID"), candidate(2)]
    )
    assert selected is not None
    assert selected["candidate_index"] == 2


def test_best_candidate_prefers_unrepaired_valid_candidate() -> None:
    selected, _reason = select_best_candidate(
        [candidate(1, repair_status="SUCCEEDED"), candidate(2)]
    )
    assert selected is not None
    assert selected["candidate_index"] == 2


def test_best_candidate_uses_generation_order_for_ties() -> None:
    selected, _reason = select_best_candidate([candidate(2), candidate(1)])
    assert selected is not None
    assert selected["candidate_index"] == 1


def test_generate_candidates_writes_comparison_session_and_best_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_generate(
        description: str,
        *,
        config_path: Path,
        output_json: Path,
        output_session: Path,
        timeout: float,
        model_override: str | None,
        repair_attempts: int,
    ) -> dict:
        del description, config_path, timeout, model_override, repair_attempts
        index = int(output_json.stem.split("_")[1].split(".")[0])
        candidates_module.write_json(output_json, valid_archseed_json(f"Candidate {index}"))
        repair_status = "SUCCEEDED" if index == 1 else "NOT_NEEDED"
        session = {
            "validation_status": "VALID",
            "validation_message": f"VALID: {output_json}",
            "repair_attempts": 1 if index == 1 else 0,
            "repair_status": repair_status,
            "repair_messages": ["repaired"] if index == 1 else [],
            "final_validation_status": "VALID",
        }
        candidates_module.write_json(output_session, session)
        return session

    monkeypatch.setattr(candidates_module, "generate_with_lmstudio", fake_generate)
    session = generate_candidates(
        "small office with openings",
        count=3,
        repair_attempts=1,
        config_path=CONFIG_PATH,
        output_root=tmp_path / "generated" / "candidates",
        session_root=tmp_path / "draft_sessions",
        run_id="test-run",
    )

    assert session["candidate_count"] == 3
    assert len(session["candidates"]) == 3
    assert session["selected_candidate"].endswith("candidate_02.v0.1.json")
    assert "without repair" in session["selection_reason"]
    assert session["sketchup_import_command"].startswith("ArchSeed.import_json(")
    assert Path(session["best_candidate_json_path"]).is_file()

    session_path = Path(session["session_path"])
    saved_session = json.loads(session_path.read_text(encoding="utf-8"))
    assert saved_session["selected_candidate"].endswith("candidate_02.v0.1.json")
    assert saved_session["selection_reason"] == session["selection_reason"]
    assert saved_session["candidates"][0]["validation_status"] == "INVALID"
    assert saved_session["candidates"][0]["repair_status"] == "SUCCEEDED"
    assert not list((tmp_path / "generated").rglob(".candidate_*.session.json"))


def test_generate_candidates_rejects_non_local_config_before_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    config["base_url"] = "https://example.com/v1"
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    def fail_generate(*_args: object, **_kwargs: object) -> dict:
        raise AssertionError("generation must not run for an external URL")

    monkeypatch.setattr(candidates_module, "generate_with_lmstudio", fail_generate)
    with pytest.raises(ConfigValidationError):
        generate_candidates(
            "small office",
            config_path=config_path,
            output_root=tmp_path / "generated",
            session_root=tmp_path / "sessions",
        )


def test_generate_candidates_rejects_when_no_valid_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_invalid(
        _description: str,
        *,
        output_session: Path,
        **_kwargs: object,
    ) -> dict:
        candidates_module.write_json(
            output_session,
            {
                "validation_status": "INVALID",
                "validation_message": "INVALID: fixture",
                "repair_attempts": 0,
                "repair_status": "NOT_REQUESTED",
                "repair_messages": [],
                "final_validation_status": "INVALID",
            },
        )
        raise ValidationError("fixture")

    monkeypatch.setattr(candidates_module, "generate_with_lmstudio", fake_invalid)
    with pytest.raises(CandidateGenerationError, match="No candidate"):
        generate_candidates(
            "small office",
            count=2,
            config_path=CONFIG_PATH,
            output_root=tmp_path / "generated",
            session_root=tmp_path / "sessions",
            run_id="invalid-run",
        )

    aggregate = tmp_path / "sessions" / "invalid-run.candidates.session.json"
    saved = json.loads(aggregate.read_text(encoding="utf-8"))
    assert saved["selected_candidate"] is None
    assert saved["sketchup_import_command"] == ""


def test_candidate_outputs_are_ignored_and_source_has_no_unsafe_integration() -> None:
    gitignore = GITIGNORE_PATH.read_text(encoding="utf-8").splitlines()
    assert "generated/*.json" in gitignore
    assert "generated/candidates/**/*.json" in gitignore
    assert "draft_sessions/*.json" in gitignore

    source = CLI_PATH.read_text(encoding="utf-8").lower()
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
        "authorization",
        "bearer ",
        "api.openai.com",
        "api.anthropic.com",
    ]
    for token in forbidden_tokens:
        assert token not in source

    assert "generate_with_lmstudio" in source
    assert "parse_local_base_url" in source
