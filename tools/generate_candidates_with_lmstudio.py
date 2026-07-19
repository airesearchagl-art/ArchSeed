from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

try:
    from tools.candidate_quality import calculate_candidate_quality
    from tools.candidate_quality_score import calculate_quality_score
    from tools.generate_with_lmstudio import (
        DEFAULT_TIMEOUT_SECONDS,
        MAX_REPAIR_ATTEMPTS,
        JSONExtractionError,
        LMStudioGenerationError,
        generate_with_lmstudio,
        utc_now,
        write_json,
    )
    from tools.preview_llm_prompt import DEFAULT_CONFIG_PATH
    from tools.print_sketchup_import_command import build_import_command
    from tools.validate_archseed import ValidationError
    from tools.validate_llm_config import (
        ConfigValidationError,
        load_json,
        parse_local_base_url,
        validate_llm_config,
    )
except ModuleNotFoundError:
    from candidate_quality import calculate_candidate_quality
    from candidate_quality_score import calculate_quality_score
    from generate_with_lmstudio import (
        DEFAULT_TIMEOUT_SECONDS,
        MAX_REPAIR_ATTEMPTS,
        JSONExtractionError,
        LMStudioGenerationError,
        generate_with_lmstudio,
        utc_now,
        write_json,
    )
    from preview_llm_prompt import DEFAULT_CONFIG_PATH
    from print_sketchup_import_command import build_import_command
    from validate_archseed import ValidationError
    from validate_llm_config import (
        ConfigValidationError,
        load_json,
        parse_local_base_url,
        validate_llm_config,
    )


DEFAULT_CANDIDATE_COUNT = 3
MIN_CANDIDATE_COUNT = 1
MAX_CANDIDATE_COUNT = 5
DEFAULT_OUTPUT_ROOT = Path("generated") / "candidates"
DEFAULT_SESSION_ROOT = Path("draft_sessions")


class CandidateGenerationError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        session: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.session = session


def candidate_count(value: str) -> int:
    try:
        count = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("count must be an integer") from exc
    if not MIN_CANDIDATE_COUNT <= count <= MAX_CANDIDATE_COUNT:
        raise argparse.ArgumentTypeError(
            f"count must be between {MIN_CANDIDATE_COUNT} and "
            f"{MAX_CANDIDATE_COUNT}"
        )
    return count


def make_run_id() -> str:
    timestamp = utc_now().replace("-", "").replace(":", "")
    return f"{timestamp}-{uuid4().hex[:8]}"


def select_best_candidate(
    candidates: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, str]:
    valid_candidates = [
        candidate
        for candidate in candidates
        if candidate.get("final_validation_status") == "VALID"
    ]
    if not valid_candidates:
        return None, "No candidate finished with VALID ArchSeed JSON."

    selected = min(
        valid_candidates,
        key=lambda candidate: (
            candidate.get("repair_status") == "SUCCEEDED",
            int(candidate["candidate_index"]),
        ),
    )
    if selected.get("repair_status") == "SUCCEEDED":
        reason = (
            "Selected the earliest VALID candidate after repair because no "
            "earlier unrepaired VALID candidate ranked higher."
        )
    else:
        reason = (
            "Selected the earliest candidate that was VALID without repair; "
            "unrepaired VALID candidates rank above repaired candidates."
        )
    return selected, reason


def _load_candidate_session(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CandidateGenerationError(
            f"Candidate session could not be read: {path}"
        ) from exc
    if not isinstance(value, dict):
        raise CandidateGenerationError(
            f"Candidate session is not a JSON object: {path}"
        )
    return value


def _candidate_record(
    index: int,
    candidate_path: Path,
    session: dict[str, Any],
) -> dict[str, Any]:
    repair_status = str(session.get("repair_status", "NOT_APPLICABLE"))
    validation_status = str(session.get("validation_status", "INVALID"))
    if repair_status == "SUCCEEDED":
        validation_status = "INVALID"
    return {
        "candidate_index": index,
        "json_path": candidate_path.expanduser().resolve().as_posix(),
        "validation_status": validation_status,
        "validation_message": str(session.get("validation_message", "")),
        "repair_attempts": int(session.get("repair_attempts", 0)),
        "repair_status": repair_status,
        "repair_messages": list(session.get("repair_messages", [])),
        "final_validation_status": str(
            session.get("final_validation_status", validation_status)
        ),
    }


def _add_quality_metrics(record: dict[str, Any], candidate_path: Path) -> None:
    final_status = str(record["final_validation_status"])
    candidate_json: dict[str, Any] | None = None
    warnings: list[str] = []
    if final_status == "VALID":
        try:
            loaded = json.loads(candidate_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                candidate_json = loaded
            else:
                warnings.append("Candidate JSON root is not an object.")
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(f"Candidate JSON could not be read for metrics: {exc}")

    quality = calculate_candidate_quality(
        candidate_json,
        repaired=record.get("repair_status") == "SUCCEEDED",
        validation_status=final_status,
    )
    if warnings:
        quality["quality_metrics_status"] = "PARTIAL"
        quality["quality_metrics_warnings"] = [
            *warnings,
            *quality["quality_metrics_warnings"],
        ]
    record.update(quality)


def _add_quality_score(record: dict[str, Any]) -> None:
    score = calculate_quality_score(
        record.get("quality_metrics"),
        str(record.get("final_validation_status", "INVALID")),
        str(record.get("repair_status", "NOT_APPLICABLE")),
    )
    if (
        record.get("quality_metrics_status") == "PARTIAL"
        and score["quality_score_status"] == "COMPLETE"
    ):
        score["quality_score_status"] = "PARTIAL"
        score["quality_score_warnings"] = [
            "Candidate quality metrics are PARTIAL; the score uses only available values.",
            *score["quality_score_warnings"],
        ]
    record.update(score)


def generate_candidates(
    description: str,
    *,
    count: int = DEFAULT_CANDIDATE_COUNT,
    repair_attempts: int = 0,
    config_path: Path = DEFAULT_CONFIG_PATH,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    session_root: Path = DEFAULT_SESSION_ROOT,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    model_override: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    if not MIN_CANDIDATE_COUNT <= count <= MAX_CANDIDATE_COUNT:
        raise CandidateGenerationError(
            f"count must be between {MIN_CANDIDATE_COUNT} and "
            f"{MAX_CANDIDATE_COUNT}."
        )
    if not 0 <= repair_attempts <= MAX_REPAIR_ATTEMPTS:
        raise CandidateGenerationError(
            f"repair_attempts must be between 0 and {MAX_REPAIR_ATTEMPTS}."
        )

    validated_config = validate_llm_config(load_json(config_path))
    parse_local_base_url(validated_config["base_url"])

    active_run_id = run_id or make_run_id()
    run_directory = output_root / active_run_id
    aggregate_session_path = session_root / f"{active_run_id}.candidates.session.json"
    candidates: list[dict[str, Any]] = []

    for index in range(1, count + 1):
        candidate_path = run_directory / f"candidate_{index:02d}.v0.1.json"
        temporary_session_path = run_directory / f".candidate_{index:02d}.session.json"
        generation_error: Exception | None = None
        try:
            generate_with_lmstudio(
                description,
                config_path=config_path,
                output_json=candidate_path,
                output_session=temporary_session_path,
                timeout=timeout,
                model_override=model_override,
                repair_attempts=repair_attempts,
            )
        except (
            OSError,
            json.JSONDecodeError,
            ValidationError,
            LMStudioGenerationError,
            JSONExtractionError,
        ) as exc:
            generation_error = exc

        if temporary_session_path.is_file():
            candidate_session = _load_candidate_session(temporary_session_path)
            temporary_session_path.unlink()
        else:
            candidate_session = {
                "validation_status": "INVALID",
                "validation_message": f"INVALID: {generation_error}",
                "repair_attempts": 0,
                "repair_status": "NOT_APPLICABLE",
                "repair_messages": [],
                "final_validation_status": "INVALID",
            }
        candidate_record = _candidate_record(index, candidate_path, candidate_session)
        _add_quality_metrics(candidate_record, candidate_path)
        _add_quality_score(candidate_record)
        candidates.append(candidate_record)

    selected, selection_reason = select_best_candidate(candidates)
    best_candidate_path = run_directory / "best_candidate.v0.1.json"
    import_command = ""
    selected_candidate_path: str | None = None
    if selected is not None:
        selected_path = Path(selected["json_path"])
        selected_json = json.loads(selected_path.read_text(encoding="utf-8"))
        write_json(best_candidate_path, selected_json)
        selected_candidate_path = selected["json_path"]
        import_command = build_import_command(best_candidate_path)

    session = {
        "user_prompt": description,
        "generator_mode": "lmstudio_local_multiple_candidates",
        "candidate_count": count,
        "candidates": candidates,
        "selected_candidate": selected_candidate_path,
        "selection_reason": selection_reason,
        "best_candidate_json_path": (
            best_candidate_path.expanduser().resolve().as_posix()
            if selected is not None
            else None
        ),
        "sketchup_import_command": import_command,
        "created_at": utc_now(),
        "notes": (
            "Candidates were generated and evaluated with the configured local "
            "LM Studio server. Architectural quality still requires visual review."
        ),
    }
    write_json(aggregate_session_path, session)
    session["session_path"] = aggregate_session_path.expanduser().resolve().as_posix()

    if selected is None:
        raise CandidateGenerationError(selection_reason, session=session)
    return session


def build_candidate_summary(session: dict[str, Any]) -> dict[str, Any]:
    selected_candidate = session.get("selected_candidate")
    candidates = []
    for candidate in session.get("candidates", []):
        json_path = candidate.get("json_path")
        candidates.append(
            {
                "candidate_index": candidate.get("candidate_index"),
                "validation_status": candidate.get("validation_status"),
                "repair_status": candidate.get("repair_status"),
                "final_validation_status": candidate.get(
                    "final_validation_status"
                ),
                "selected": json_path == selected_candidate,
                "json_path": json_path,
                "quality_metrics": candidate.get("quality_metrics", {}),
                "quality_metrics_status": candidate.get(
                    "quality_metrics_status", "NOT_CALCULATED"
                ),
                "quality_metrics_warnings": candidate.get(
                    "quality_metrics_warnings", []
                ),
                "quality_score": candidate.get("quality_score"),
                "quality_score_status": candidate.get(
                    "quality_score_status", "NOT_CALCULATED"
                ),
                "quality_score_breakdown": candidate.get(
                    "quality_score_breakdown", {}
                ),
                "quality_score_warnings": candidate.get(
                    "quality_score_warnings", []
                ),
            }
        )
    selected_record = next(
        (
            candidate
            for candidate in candidates
            if candidate.get("selected")
        ),
        None,
    )
    return {
        "candidate_count": session.get("candidate_count", len(candidates)),
        "candidates": candidates,
        "selected_candidate": selected_candidate,
        "selection_reason": session.get("selection_reason", ""),
        "best_candidate_json_path": session.get("best_candidate_json_path"),
        "sketchup_import_command": session.get("sketchup_import_command", ""),
        "selected_quality_score": (
            selected_record.get("quality_score") if selected_record else None
        ),
    }


def format_candidate_summary(summary: dict[str, Any]) -> str:
    lines = ["CANDIDATE SUMMARY"]
    for candidate in summary["candidates"]:
        metrics = candidate.get("quality_metrics", {})
        lines.extend(
            [
                f"Candidate {int(candidate['candidate_index']):02d}",
                f"  validation_status: {candidate['validation_status']}",
                f"  repair_status: {candidate['repair_status']}",
                (
                    "  final_validation_status: "
                    f"{candidate['final_validation_status']}"
                ),
                f"  repaired: {metrics.get('repaired')}",
                (
                    "  quality_metrics_status: "
                    f"{candidate.get('quality_metrics_status')}"
                ),
                f"  footprint_area: {metrics.get('footprint_area')}",
                f"  aspect_ratio: {metrics.get('aspect_ratio')}",
                f"  door_count: {metrics.get('door_count')}",
                f"  window_count: {metrics.get('window_count')}",
                (
                    "  opening_to_wall_area_ratio: "
                    f"{metrics.get('opening_to_wall_area_ratio')}"
                ),
                f"  quality_score: {candidate.get('quality_score')}",
                (
                    "  quality_score_status: "
                    f"{candidate.get('quality_score_status')}"
                ),
                f"  selected: {'yes' if candidate['selected'] else 'no'}",
                f"  json_path: {candidate['json_path']}",
            ]
        )
    lines.extend(
        [
            "BEST CANDIDATE",
            f"  selected_candidate: {summary['selected_candidate']}",
            f"  selection_reason: {summary['selection_reason']}",
            f"  quality_score: {summary.get('selected_quality_score')}",
            "  quality_score_used_for_selection: no",
            (
                "  sketchup_import_command: "
                f"{summary['sketchup_import_command']}"
            ),
        ]
    )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate, compare, and select local LM Studio ArchSeed candidates."
    )
    parser.add_argument("description", help="Short building description.")
    parser.add_argument(
        "--count",
        type=candidate_count,
        default=DEFAULT_CANDIDATE_COUNT,
        help="Number of candidates to generate (1-5; default: 3).",
    )
    parser.add_argument(
        "--repair-attempts",
        type=int,
        default=0,
        help="Repair attempts per invalid candidate (0-3; default: 0).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Local-only LLM config JSON path.",
    )
    parser.add_argument(
        "--model",
        help="Optional local LM Studio model id override.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Local server timeout in seconds for each candidate.",
    )
    parser.add_argument(
        "--summary-json",
        type=Path,
        help="Optional human-readable candidate comparison JSON output path.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 0 <= args.repair_attempts <= MAX_REPAIR_ATTEMPTS:
        print(
            f"INVALID: --repair-attempts must be between 0 and "
            f"{MAX_REPAIR_ATTEMPTS}.",
            file=sys.stderr,
        )
        return 2
    if not 0 < args.timeout <= 300:
        print("INVALID: --timeout must be greater than 0 and at most 300.", file=sys.stderr)
        return 2

    try:
        session = generate_candidates(
            args.description,
            count=args.count,
            repair_attempts=args.repair_attempts,
            config_path=args.config,
            timeout=args.timeout,
            model_override=args.model,
        )
        summary = build_candidate_summary(session)
        if args.summary_json is not None:
            write_json(args.summary_json, summary)
    except CandidateGenerationError as exc:
        if exc.session is not None:
            failed_summary = build_candidate_summary(exc.session)
            if args.summary_json is not None:
                write_json(args.summary_json, failed_summary)
            print(f"WROTE SESSION: {exc.session['session_path']}")
            if args.summary_json is not None:
                print(f"WROTE SUMMARY: {args.summary_json}")
            print(format_candidate_summary(failed_summary))
        print(f"Candidate generation failed: {exc}", file=sys.stderr)
        return 1
    except (
        OSError,
        json.JSONDecodeError,
        ConfigValidationError,
    ) as exc:
        print(f"Candidate generation failed: {exc}", file=sys.stderr)
        return 1

    print(f"WROTE SESSION: {session['session_path']}")
    if args.summary_json is not None:
        print(f"WROTE SUMMARY: {args.summary_json}")
    print(format_candidate_summary(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
