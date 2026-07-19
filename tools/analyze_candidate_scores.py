from __future__ import annotations

import argparse
import glob
import json
import math
import re
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable


ANALYSIS_VERSION = "0.1"
KNOWN_SCORE_STATUSES = ("COMPLETE", "PARTIAL", "NOT_CALCULATED")
KNOWN_BREAKDOWN_ITEMS = (
    "base",
    "validation",
    "repair",
    "door",
    "window",
    "aspect_ratio",
    "opening_ratio",
)
LOCAL_PATH_PATTERN = re.compile(r"(?<!\w)(?:[A-Za-z]:[\\/]|/)[^\s\"']+")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _score_key(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return repr(value)


def _safe_text(value: Any) -> str:
    return LOCAL_PATH_PATTERN.sub("<local-path>", str(value))


def _safe_source_name(path: Path, cwd: Path) -> str:
    resolved = path.expanduser().resolve()
    try:
        return resolved.relative_to(cwd.resolve()).as_posix()
    except ValueError:
        return resolved.name


def expand_input_paths(patterns: Iterable[str]) -> list[Path]:
    paths: list[Path] = []
    for pattern in patterns:
        matches = [
            Path(match) for match in sorted(glob.glob(pattern, recursive=True))
        ]
        paths.extend(matches or [Path(pattern)])
    return paths


def normalize_repair_status(candidate: dict[str, Any]) -> str:
    repair_status = candidate.get("repair_status")
    if repair_status == "SUCCEEDED":
        return "AFTER_REPAIR"
    if repair_status == "NOT_NEEDED":
        return "NOT_NEEDED"
    if repair_status is not None:
        return "UNKNOWN"

    repaired = candidate.get("repaired")
    if not isinstance(repaired, bool):
        metrics = candidate.get("quality_metrics")
        if isinstance(metrics, dict):
            repaired = metrics.get("repaired")
    if repaired is True:
        return "AFTER_REPAIR"
    if repaired is False:
        return "WITHOUT_REPAIR"
    return "UNKNOWN"


def normalize_candidate_record(
    candidate: Any,
    *,
    source_file: str,
    selected_candidate_path: str | None,
) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        return {
            "source_file": source_file,
            "candidate_index": None,
            "final_validation_status": "UNKNOWN",
            "repair_category": "UNKNOWN",
            "quality_metrics_status": "UNKNOWN",
            "quality_score": None,
            "quality_score_status": "UNKNOWN",
            "selected": False,
            "quality_score_breakdown": {},
            "quality_score_warnings": [],
            "identity": None,
            "malformed": True,
        }

    malformed = False
    score_value = candidate.get("quality_score")
    score = _finite_number(score_value)
    if score_value is not None and score is None:
        malformed = True

    breakdown = candidate.get("quality_score_breakdown", {})
    if not isinstance(breakdown, dict):
        breakdown = {}
        malformed = True

    raw_warnings = candidate.get("quality_score_warnings", [])
    if not isinstance(raw_warnings, list):
        raw_warnings = []
        malformed = True
    warnings = [_safe_text(item) for item in raw_warnings if isinstance(item, str)]
    if len(warnings) != len(raw_warnings):
        malformed = True

    json_path = candidate.get("json_path")
    candidate_index = candidate.get("candidate_index")
    identity = None
    if isinstance(json_path, str) and candidate_index is not None:
        identity = (json_path.replace("\\", "/"), str(candidate_index))

    selected = candidate.get("selected")
    if not isinstance(selected, bool):
        selected = bool(
            selected_candidate_path
            and isinstance(json_path, str)
            and json_path.replace("\\", "/")
            == selected_candidate_path.replace("\\", "/")
        )

    final_status = candidate.get("final_validation_status")
    if not isinstance(final_status, str):
        final_status = "UNKNOWN"

    metrics_status = candidate.get("quality_metrics_status")
    if not isinstance(metrics_status, str):
        metrics_status = "UNKNOWN"

    score_status = candidate.get("quality_score_status")
    if not isinstance(score_status, str):
        score_status = "UNKNOWN"

    return {
        "source_file": source_file,
        "candidate_index": candidate_index,
        "final_validation_status": final_status,
        "repair_category": normalize_repair_status(candidate),
        "quality_metrics_status": metrics_status,
        "quality_score": score,
        "quality_score_status": score_status,
        "selected": selected,
        "quality_score_breakdown": breakdown,
        "quality_score_warnings": warnings,
        "identity": identity,
        "malformed": malformed,
    }


def load_candidate_records(
    paths: Iterable[Path],
    *,
    cwd: Path | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    base = cwd or Path.cwd()
    documents: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for path in paths:
        source_file = _safe_source_name(path, base)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or not isinstance(
                payload.get("candidates"), list
            ):
                raise ValueError("JSON does not contain a candidate array")
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            failures.append(
                {
                    "source_file": source_file,
                    "error": f"{type(exc).__name__}: {_safe_text(exc)}",
                }
            )
            continue

        selected_path = payload.get("selected_candidate")
        if not isinstance(selected_path, str):
            selected_path = None
        session_analyzable = any(
            key in payload for key in ("generator_mode", "user_prompt", "created_at")
        )
        records = [
            normalize_candidate_record(
                candidate,
                source_file=source_file,
                selected_candidate_path=selected_path,
            )
            for candidate in payload["candidates"]
        ]
        documents.append(
            {
                "source_file": source_file,
                "session_analyzable": session_analyzable,
                "records": records,
            }
        )
    return documents, failures


def analyze_score_distribution(records: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [record["quality_score"] for record in records if record["quality_score"] is not None]
    frequency = Counter(scores)
    if not scores:
        return {
            "count": 0,
            "minimum": None,
            "maximum": None,
            "mean": None,
            "median": None,
            "unique_score_count": 0,
            "mode_scores": [],
            "mode_count": 0,
            "score_frequency": {},
        }

    mode_count = max(frequency.values())
    mode_scores = sorted(score for score, count in frequency.items() if count == mode_count)
    return {
        "count": len(scores),
        "minimum": min(scores),
        "maximum": max(scores),
        "mean": statistics.fmean(scores),
        "median": statistics.median(scores),
        "unique_score_count": len(frequency),
        "mode_scores": mode_scores,
        "mode_count": mode_count,
        "score_frequency": {
            _score_key(score): frequency[score] for score in sorted(frequency)
        },
    }


def analyze_concentration(score_distribution: dict[str, Any]) -> dict[str, Any]:
    count = int(score_distribution["count"])
    frequency = score_distribution["score_frequency"]
    if count == 0:
        return {
            "score_100_count": 0,
            "score_100_rate": None,
            "top_score_count": 0,
            "top_score_rate": None,
            "most_common_score": None,
            "most_common_score_count": 0,
            "most_common_score_rate": None,
        }

    maximum = float(score_distribution["maximum"])
    top_count = int(frequency[_score_key(maximum)])
    mode_scores = score_distribution["mode_scores"]
    most_common = float(min(mode_scores))
    most_common_count = int(score_distribution["mode_count"])
    score_100_count = int(frequency.get("100", 0))
    return {
        "score_100_count": score_100_count,
        "score_100_rate": score_100_count / count,
        "top_score_count": top_count,
        "top_score_rate": top_count / count,
        "most_common_score": most_common,
        "most_common_score_count": most_common_count,
        "most_common_score_rate": most_common_count / count,
    }


def analyze_session_ties(documents: list[dict[str, Any]]) -> dict[str, Any]:
    sessions = [doc for doc in documents if doc["session_analyzable"]]
    files_without_boundary = len(documents) - len(sessions)
    multiple = ties = all_equal = 0
    unique_counts: list[int] = []
    for document in sessions:
        scores = [
            record["quality_score"]
            for record in document["records"]
            if record["quality_score"] is not None
        ]
        if scores:
            unique_counts.append(len(set(scores)))
        if len(scores) < 2:
            continue
        multiple += 1
        if scores.count(max(scores)) > 1:
            ties += 1
        if len(set(scores)) == 1:
            all_equal += 1
    return {
        "sessions_analyzed": len(sessions),
        "files_without_session_boundary": files_without_boundary,
        "sessions_with_multiple_scored_candidates": multiple,
        "sessions_with_top_score_tie": ties,
        "top_score_tie_rate": ties / multiple if multiple else None,
        "average_unique_scores_per_session": (
            statistics.fmean(unique_counts) if unique_counts else None
        ),
        "sessions_where_all_scored_candidates_equal": all_equal,
    }


def analyze_selection_relationship(
    documents: list[dict[str, Any]], records: list[dict[str, Any]]
) -> dict[str, Any]:
    selected_records = [record for record in records if record["selected"]]
    selected_scores = [
        record["quality_score"]
        for record in selected_records
        if record["quality_score"] is not None
    ]
    selected_frequency = Counter(selected_scores)
    highest = not_highest = tied = unavailable = 0
    for document in documents:
        if not document["session_analyzable"]:
            continue
        scores = [
            record["quality_score"]
            for record in document["records"]
            if record["quality_score"] is not None
        ]
        selected = [record for record in document["records"] if record["selected"]]
        if len(selected) != 1 or selected[0]["quality_score"] is None or not scores:
            unavailable += 1
            continue
        selected_score = selected[0]["quality_score"]
        top_score = max(scores)
        if selected_score < top_score:
            not_highest += 1
        elif scores.count(top_score) > 1:
            tied += 1
        else:
            highest += 1
    return {
        "selected_candidate_count": len(selected_records),
        "selected_with_score_count": len(selected_scores),
        "selected_score_mean": (
            statistics.fmean(selected_scores) if selected_scores else None
        ),
        "selected_score_distribution": {
            _score_key(score): selected_frequency[score]
            for score in sorted(selected_frequency)
        },
        "sessions_where_selected_had_highest_score": highest,
        "sessions_where_selected_did_not_have_highest_score": not_highest,
        "sessions_where_selected_tied_for_highest_score": tied,
        "sessions_where_comparison_not_possible": unavailable,
    }


def analyze_breakdowns(
    records: list[dict[str, Any]], total_candidate_records: int
) -> tuple[dict[str, Any], set[int]]:
    item_points: dict[str, list[float]] = {
        item: [] for item in KNOWN_BREAKDOWN_ITEMS
    }
    appearances: Counter[str] = Counter()
    malformed_record_indexes: set[int] = set()
    for record_index, record in enumerate(records):
        breakdown = record["quality_score_breakdown"]
        for name, component in breakdown.items():
            appearances[str(name)] += 1
            item_points.setdefault(str(name), [])
            if not isinstance(component, dict):
                malformed_record_indexes.add(record_index)
                continue
            points = _finite_number(component.get("points"))
            if points is None:
                malformed_record_indexes.add(record_index)
                continue
            item_points[str(name)].append(points)

    analysis = {}
    for name in sorted(item_points):
        points = item_points[name]
        frequency = Counter(points)
        analysis[name] = {
            "appearance_count": appearances[name],
            "points_frequency": {
                _score_key(value): frequency[value] for value in sorted(frequency)
            },
            "average_points": statistics.fmean(points) if points else None,
            "missing_count": total_candidate_records - appearances[name],
        }
    return analysis, malformed_record_indexes


def analyze_warnings(
    records: list[dict[str, Any]], *, malformed_record_count: int
) -> dict[str, Any]:
    warning_frequency: Counter[str] = Counter()
    candidates_with_warnings = 0
    for record in records:
        warnings = record["quality_score_warnings"]
        if warnings:
            candidates_with_warnings += 1
            warning_frequency.update(warnings)
    return {
        "candidates_with_warnings": candidates_with_warnings,
        "warning_frequency": dict(sorted(warning_frequency.items())),
        "malformed_record_count": malformed_record_count,
    }


def build_analysis_report(
    paths: list[Path],
    *,
    generated_at: str | None = None,
    cwd: Path | None = None,
) -> dict[str, Any]:
    documents, failed_files = load_candidate_records(paths, cwd=cwd)
    records = [record for document in documents for record in document["records"]]
    total_records = len(records)
    status_counts = Counter(record["quality_score_status"] for record in records)
    status_distribution = {
        status: status_counts[status] for status in KNOWN_SCORE_STATUSES
    }
    status_distribution["UNKNOWN"] = sum(
        count
        for status, count in status_counts.items()
        if status not in KNOWN_SCORE_STATUSES
    )
    metrics_status_counts = Counter(
        record["quality_metrics_status"] for record in records
    )
    metrics_status_distribution = {
        status: metrics_status_counts[status] for status in KNOWN_SCORE_STATUSES
    }
    metrics_status_distribution["UNKNOWN"] = sum(
        count
        for status, count in metrics_status_counts.items()
        if status not in KNOWN_SCORE_STATUSES
    )

    validation_counts = Counter(
        record["final_validation_status"] for record in records
    )
    validation_distribution = {
        "VALID": validation_counts["VALID"],
        "INVALID": validation_counts["INVALID"],
        "OTHER_OR_UNKNOWN": sum(
            count
            for status, count in validation_counts.items()
            if status not in ("VALID", "INVALID")
        ),
    }
    repair_counts = Counter(record["repair_category"] for record in records)
    repair_distribution = {
        category: repair_counts[category]
        for category in (
            "WITHOUT_REPAIR",
            "AFTER_REPAIR",
            "NOT_NEEDED",
            "UNKNOWN",
        )
    }

    score_distribution = analyze_score_distribution(records)
    breakdown_analysis, malformed_breakdown_indexes = analyze_breakdowns(
        records, total_records
    )
    malformed_record_indexes = {
        index for index, record in enumerate(records) if record["malformed"]
    }
    malformed_records = len(
        malformed_record_indexes | malformed_breakdown_indexes
    )

    identities = [record["identity"] for record in records if record["identity"]]
    identity_counts = Counter(identities)
    possible_duplicates = sum(count - 1 for count in identity_counts.values() if count > 1)
    if not identities:
        duplicate_status = "INSUFFICIENT_IDENTIFIERS"
    elif possible_duplicates:
        duplicate_status = "POSSIBLE_DUPLICATES_FOUND"
    else:
        duplicate_status = "NO_IDENTIFIABLE_DUPLICATES"

    analysis_warnings: list[str] = []
    if failed_files:
        analysis_warnings.append(
            f"{len(failed_files)} input file(s) could not be processed."
        )
    if score_distribution["count"] == 0:
        analysis_warnings.append("No finite numeric quality scores were available.")
    files_without_boundary = sum(not doc["session_analyzable"] for doc in documents)
    if files_without_boundary:
        analysis_warnings.append(
            f"{files_without_boundary} file(s) lacked a reliable session boundary and "
            "were excluded from session and selection comparisons."
        )
    if possible_duplicates:
        analysis_warnings.append(
            f"{possible_duplicates} possible duplicate candidate record(s) were "
            "detected and retained."
        )
    if malformed_records:
        analysis_warnings.append(
            f"{malformed_records} malformed candidate record(s) contained fields "
            "that were excluded from affected calculations."
        )

    return {
        "analysis_version": ANALYSIS_VERSION,
        "generated_at": generated_at or utc_now(),
        "inputs": {
            "total_input_files": len(paths),
            "successfully_parsed_files": len(documents),
            "failed_file_count": len(failed_files),
            "failed_files": failed_files,
            "duplicate_detection_status": duplicate_status,
            "possible_duplicate_candidate_records": possible_duplicates,
        },
        "candidates": {
            "total": total_records,
            "scored": int(score_distribution["count"]),
            "unscored": total_records - int(score_distribution["count"]),
        },
        "status_distribution": status_distribution,
        "metrics_status_distribution": metrics_status_distribution,
        "validation_distribution": validation_distribution,
        "repair_distribution": repair_distribution,
        "score_distribution": score_distribution,
        "concentration": analyze_concentration(score_distribution),
        "session_ties": analyze_session_ties(documents),
        "selection_observation": analyze_selection_relationship(
            documents, records
        ),
        "breakdown_analysis": breakdown_analysis,
        "warning_analysis": analyze_warnings(
            records, malformed_record_count=malformed_records
        ),
        "analysis_warnings": analysis_warnings,
    }


def print_analysis_summary(report: dict[str, Any]) -> str:
    inputs = report["inputs"]
    candidates = report["candidates"]
    statuses = report["status_distribution"]
    scores = report["score_distribution"]
    concentration = report["concentration"]
    ties = report["session_ties"]
    selection = report["selection_observation"]

    def display(value: Any) -> str:
        return "N/A" if value is None else str(value)

    lines = [
        "Candidate Quality Score Analysis",
        "",
        f"Input files: {inputs['total_input_files']}",
        f"Parsed files: {inputs['successfully_parsed_files']}",
        f"Failed files: {inputs['failed_file_count']}",
        f"Candidate records: {candidates['total']}",
        f"Scored: {candidates['scored']}",
        f"Complete: {statuses['COMPLETE']}",
        f"Partial: {statuses['PARTIAL']}",
        f"Not calculated: {statuses['NOT_CALCULATED']}",
        "",
        "Score:",
        f"Minimum: {display(scores['minimum'])}",
        f"Maximum: {display(scores['maximum'])}",
        f"Mean: {display(scores['mean'])}",
        f"Median: {display(scores['median'])}",
        f"Unique scores: {scores['unique_score_count']}",
        f"100-point rate: {display(concentration['score_100_rate'])}",
        f"Most common score: {display(concentration['most_common_score'])}",
        (
            "Most common score rate: "
            f"{display(concentration['most_common_score_rate'])}"
        ),
        "",
        "Sessions:",
        f"Sessions analyzed: {ties['sessions_analyzed']}",
        f"Top-score ties: {ties['sessions_with_top_score_tie']}",
        (
            "All scores equal: "
            f"{ties['sessions_where_all_scored_candidates_equal']}"
        ),
        "",
        "Selection observation:",
        f"Selected candidates: {selection['selected_candidate_count']}",
        (
            "Selected was highest: "
            f"{selection['sessions_where_selected_had_highest_score']}"
        ),
        (
            "Selected was not highest: "
            f"{selection['sessions_where_selected_did_not_have_highest_score']}"
        ),
        (
            "Selected tied for highest: "
            f"{selection['sessions_where_selected_tied_for_highest_score']}"
        ),
        (
            "Comparison unavailable: "
            f"{selection['sessions_where_comparison_not_possible']}"
        ),
        "",
        "Warnings:",
    ]
    lines.extend(
        f"- {warning}" for warning in report["analysis_warnings"]
    )
    if not report["analysis_warnings"]:
        lines.append("- None")
    return "\n".join(lines)


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze saved ArchSeed candidate quality scores."
    )
    parser.add_argument("paths", nargs="*", help="Candidate session or summary JSON.")
    parser.add_argument(
        "--input",
        action="append",
        default=[],
        help="Input path or glob pattern. May be repeated.",
    )
    parser.add_argument("--output", type=Path, help="Optional analysis JSON path.")
    return parser


def main(
    argv: list[str] | None = None,
    *,
    now: Callable[[], str] = utc_now,
) -> int:
    args = build_parser().parse_args(argv)
    patterns = [*args.paths, *args.input]
    if not patterns:
        print("Score analysis failed: no input files were provided.", file=sys.stderr)
        return 1

    paths = expand_input_paths(patterns)
    report = build_analysis_report(paths, generated_at=now())
    if args.output is not None:
        write_report(args.output, report)
        print(f"WROTE ANALYSIS: {args.output}")
    print(print_analysis_summary(report))

    parsed = int(report["inputs"]["successfully_parsed_files"])
    failed = int(report["inputs"]["failed_file_count"])
    if parsed == 0:
        return 1
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
