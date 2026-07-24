from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

import tools.generate_candidates_with_lmstudio as candidates_module
from tools.generate_candidates_with_lmstudio import (
    CandidateGenerationError,
    build_candidate_summary,
    candidate_count,
    format_candidate_summary,
    generate_candidates,
    main as candidates_main,
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
    assert saved_session["candidates"][0]["quality_metrics_status"] == "COMPLETE"
    assert saved_session["candidates"][0]["quality_metrics"]["repaired"] is True
    assert saved_session["candidates"][1]["quality_metrics"][
        "footprint_area"
    ] == pytest.approx(48_000_000.0)
    assert saved_session["candidates"][0]["quality_score_status"] == "COMPLETE"
    assert saved_session["candidates"][0]["quality_score"] == 65
    assert saved_session["candidates"][1]["quality_score"] == 75
    assert saved_session["candidates"][1]["quality_score_version"] == "2.0"
    assert (
        saved_session["candidates"][1]["scoring_policy_id"]
        == "archseed-static-geometry"
    )
    assert saved_session["candidates"][1]["scoring_policy_version"] == "2.0"
    assert saved_session["candidates"][1]["breakdown_schema_version"] == "2"
    assert saved_session["candidates"][1]["quality_score_breakdown"][
        "repair_stability"
    ]["points"] == 15
    summary = build_candidate_summary(saved_session)
    assert summary["candidates"][1]["quality_score_version"] == "2.0"
    assert summary["candidates"][1]["scoring_policy_version"] == "2.0"
    assert summary["candidates"][1]["quality_score_raw"] == 75
    assert summary["selected_quality_score_version"] == "2.0"
    summary_path = tmp_path / "draft_sessions" / "v2.summary.json"
    candidates_module.write_json(summary_path, summary)
    assert json.loads(summary_path.read_text(encoding="utf-8")) == summary
    assert not list((tmp_path / "generated").rglob(".candidate_*.session.json"))


def summary_session() -> dict:
    selected_path = "/workspace/generated/candidates/run/candidate_02.v0.1.json"
    return {
        "candidate_count": 2,
        "candidates": [
            {
                "candidate_index": 1,
                "json_path": "/workspace/generated/candidates/run/candidate_01.v0.1.json",
                "validation_status": "INVALID",
                "repair_status": "FAILED",
                "final_validation_status": "INVALID",
                "quality_metrics": {
                    "repaired": False,
                    "footprint_area": None,
                    "aspect_ratio": None,
                    "door_count": None,
                    "window_count": None,
                    "opening_to_wall_area_ratio": None,
                },
                "quality_metrics_status": "NOT_CALCULATED",
                "quality_metrics_warnings": ["candidate is invalid"],
                "quality_score": None,
                "quality_score_status": "NOT_CALCULATED",
                "quality_score_breakdown": {},
                "quality_score_warnings": ["candidate is invalid"],
            },
            {
                "candidate_index": 2,
                "json_path": selected_path,
                "validation_status": "VALID",
                "repair_status": "NOT_NEEDED",
                "final_validation_status": "VALID",
                "quality_metrics": {
                    "repaired": False,
                    "footprint_area": 48_000_000.0,
                    "aspect_ratio": 4 / 3,
                    "door_count": 1,
                    "window_count": 2,
                    "opening_to_wall_area_ratio": 0.08,
                },
                "quality_metrics_status": "COMPLETE",
                "quality_metrics_warnings": [],
                "quality_score": 100,
                "quality_score_status": "COMPLETE",
                "quality_score_breakdown": {
                    "base": {"points": 50, "reason": "Base score"},
                    "validation": {
                        "points": 20,
                        "reason": "Candidate is VALID",
                    },
                    "repair": {
                        "points": 10,
                        "reason": "No repair was required",
                    },
                    "door": {"points": 5, "reason": "Door present"},
                    "window": {"points": 5, "reason": "Window present"},
                    "aspect_ratio": {"points": 5, "reason": "Observed"},
                    "opening_ratio": {"points": 5, "reason": "Observed"},
                },
                "quality_score_warnings": [],
            },
        ],
        "selected_candidate": selected_path,
        "selection_reason": "Selected the earliest unrepaired VALID candidate.",
        "best_candidate_json_path": (
            "/workspace/generated/candidates/run/best_candidate.v0.1.json"
        ),
        "sketchup_import_command": (
            'ArchSeed.import_json("/workspace/generated/candidates/run/'
            'best_candidate.v0.1.json")'
        ),
        "session_path": "/workspace/draft_sessions/run.candidates.session.json",
    }


def test_candidate_summary_contains_human_review_fields() -> None:
    summary = build_candidate_summary(summary_session())
    rendered = format_candidate_summary(summary)

    assert "Candidate 01" in rendered
    assert "Candidate 02" in rendered
    assert "validation_status: VALID" in rendered
    assert "repair_status: NOT_NEEDED" in rendered
    assert "footprint_area: 48000000.0" in rendered
    assert "aspect_ratio:" in rendered
    assert "door_count: 1" in rendered
    assert "window_count: 2" in rendered
    assert "opening_to_wall_area_ratio: 0.08" in rendered
    assert "quality_metrics_status: COMPLETE" in rendered
    assert "quality_score: 100" in rendered
    assert "quality_score_status: COMPLETE" in rendered
    assert "quality_score_version: unversioned" in rendered
    assert "quality_score_used_for_selection: no" in rendered
    assert "selected: yes" in rendered
    assert "selected_candidate:" in rendered
    assert "selection_reason:" in rendered
    assert "sketchup_import_command:" in rendered


def test_quality_score_inherits_partial_metrics_status() -> None:
    record = {
        "final_validation_status": "VALID",
        "repair_status": "NOT_NEEDED",
        "quality_metrics_status": "PARTIAL",
        "quality_metrics": {
            "footprint_area": 48_000_000.0,
            "aspect_ratio": 1.5,
            "has_door": True,
            "has_window": True,
            "opening_to_wall_area_ratio": 0.2,
        },
    }
    candidates_module._add_quality_score(record)
    assert record["quality_score"] == 85
    assert record["quality_score_status"] == "PARTIAL"
    assert record["quality_score_warnings"]


def test_summary_json_option_writes_concise_comparison(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = summary_session()
    summary_path = tmp_path / "draft_sessions" / "candidates.summary.json"
    monkeypatch.setattr(
        candidates_module,
        "generate_candidates",
        lambda *_args, **_kwargs: session,
    )

    assert candidates_main(["small office", "--summary-json", str(summary_path)]) == 0

    saved = json.loads(summary_path.read_text(encoding="utf-8"))
    assert saved["selected_candidate"] == session["selected_candidate"]
    assert saved["selection_reason"] == session["selection_reason"]
    assert saved["sketchup_import_command"] == session["sketchup_import_command"]
    assert saved["candidates"][1]["selected"] is True
    assert saved["candidates"][1]["quality_metrics_status"] == "COMPLETE"
    assert saved["candidates"][1]["quality_metrics"]["door_count"] == 1
    assert saved["candidates"][0]["quality_metrics_warnings"]
    assert saved["candidates"][1]["quality_score"] == 100
    assert saved["candidates"][1]["quality_score_status"] == "COMPLETE"
    assert saved["candidates"][1]["quality_score_breakdown"]["base"]["points"] == 50
    assert saved["candidates"][1]["quality_score_version"] is None
    assert saved["selected_quality_score"] == 100
    assert saved["selected_quality_score_version"] is None
    assert "validation_message" not in saved["candidates"][0]
    output = capsys.readouterr().out
    assert f"WROTE SUMMARY: {summary_path}" in output
    assert "CANDIDATE SUMMARY" in output


def test_failed_generation_still_writes_requested_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = summary_session()
    session["candidates"] = [session["candidates"][0]]
    session["candidate_count"] = 1
    session["selected_candidate"] = None
    session["selection_reason"] = "No candidate finished with VALID ArchSeed JSON."
    session["best_candidate_json_path"] = None
    session["sketchup_import_command"] = ""
    summary_path = tmp_path / "draft_sessions" / "failed.summary.json"

    def fail_with_session(*_args: object, **_kwargs: object) -> dict:
        raise CandidateGenerationError(
            session["selection_reason"],
            session=session,
        )

    monkeypatch.setattr(candidates_module, "generate_candidates", fail_with_session)
    assert candidates_main(
        ["small office", "--summary-json", str(summary_path)]
    ) == 1

    saved = json.loads(summary_path.read_text(encoding="utf-8"))
    assert saved["selected_candidate"] is None
    assert saved["selection_reason"] == session["selection_reason"]
    assert saved["sketchup_import_command"] == ""
    assert saved["candidates"][0]["final_validation_status"] == "INVALID"
    captured = capsys.readouterr()
    assert "CANDIDATE SUMMARY" in captured.out
    assert "Candidate generation failed" in captured.err


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
    with pytest.raises(CandidateGenerationError, match="No candidate") as exc_info:
        generate_candidates(
            "small office",
            count=2,
            config_path=CONFIG_PATH,
            output_root=tmp_path / "generated",
            session_root=tmp_path / "sessions",
            run_id="invalid-run",
        )

    assert exc_info.value.session is not None
    assert exc_info.value.session["selected_candidate"] is None

    aggregate = tmp_path / "sessions" / "invalid-run.candidates.session.json"
    saved = json.loads(aggregate.read_text(encoding="utf-8"))
    assert saved["selected_candidate"] is None
    assert saved["sketchup_import_command"] == ""


def test_candidate_outputs_are_ignored_and_source_has_no_unsafe_integration() -> None:
    gitignore = GITIGNORE_PATH.read_text(encoding="utf-8").splitlines()
    assert "generated/*.json" in gitignore
    assert "generated/candidates/**/*.json" in gitignore
    assert "draft_sessions/*.json" in gitignore
    assert Path("draft_sessions/candidates.summary.json").match(
        "draft_sessions/*.json"
    )

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
