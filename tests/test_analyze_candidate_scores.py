from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tools.analyze_candidate_scores import (
    analyze_score_distribution,
    build_analysis_report,
    expand_input_paths,
    main,
    normalize_repair_status,
    print_analysis_summary,
)
from tools.candidate_quality_score import calculate_quality_score
from tools.generate_candidates_with_lmstudio import select_best_candidate


ROOT = Path(__file__).resolve().parents[1]
ANALYZER = ROOT / "tools" / "analyze_candidate_scores.py"


def candidate(
    index: int,
    score: float | None,
    *,
    score_status: str = "COMPLETE",
    validation: str = "VALID",
    repair: str | None = "NOT_NEEDED",
    selected: bool | None = None,
    warnings: list[str] | None = None,
    breakdown: dict | None = None,
    score_version: str | None = None,
) -> dict:
    record = {
        "candidate_index": index,
        "json_path": f"C:/private/user/generated/candidate_{index:02d}.json",
        "final_validation_status": validation,
        "quality_metrics_status": "COMPLETE",
        "quality_score": score,
        "quality_score_status": score_status,
        "quality_score_breakdown": breakdown
        if breakdown is not None
        else {
            "base": {"points": 50, "reason": "Base score"},
            "validation": {"points": 20, "reason": "VALID"},
            "custom": {"points": 3.5, "reason": "Fixture"},
        },
        "quality_score_warnings": warnings or [],
    }
    if repair is not None:
        record["repair_status"] = repair
    if selected is not None:
        record["selected"] = selected
    if score_version is not None:
        record["quality_score_version"] = score_version
    return record


def write_document(
    path: Path,
    candidates: list,
    *,
    session: bool = True,
    selected_index: int | None = 1,
) -> dict:
    payload = {
        "candidate_count": len(candidates),
        "candidates": candidates,
        "selected_candidate": (
            f"C:/private/user/generated/candidate_{selected_index:02d}.json"
            if selected_index is not None
            else None
        ),
    }
    if session:
        payload.update(
            {
                "user_prompt": "fixture",
                "generator_mode": "lmstudio_local_multiple_candidates",
                "created_at": "2026-07-19T00:00:00Z",
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def report_for(tmp_path: Path, *documents: tuple[str, list, bool, int | None]) -> dict:
    paths = []
    for name, candidates, session, selected_index in documents:
        path = tmp_path / name
        write_document(
            path,
            candidates,
            session=session,
            selected_index=selected_index,
        )
        paths.append(path)
    return build_analysis_report(
        paths,
        generated_at="2026-07-19T00:00:00Z",
        cwd=tmp_path,
    )


def test_analyzes_single_session_json(tmp_path: Path) -> None:
    report = report_for(
        tmp_path,
        ("session.json", [candidate(1, 80), candidate(2, 100)], True, 1),
    )
    assert report["inputs"]["successfully_parsed_files"] == 1
    assert report["candidates"] == {"total": 2, "scored": 2, "unscored": 0}
    assert report["session_ties"]["sessions_analyzed"] == 1


def test_analyzes_summary_without_assuming_session_boundary(tmp_path: Path) -> None:
    report = report_for(
        tmp_path,
        ("summary.json", [candidate(1, 100, selected=True)], False, 1),
    )
    assert report["candidates"]["scored"] == 1
    assert report["session_ties"]["sessions_analyzed"] == 0
    assert report["session_ties"]["files_without_session_boundary"] == 1


def test_combines_multiple_mixed_input_files(tmp_path: Path) -> None:
    report = report_for(
        tmp_path,
        ("session.json", [candidate(1, 80)], True, 1),
        ("summary.json", [candidate(2, 90, selected=True)], False, 2),
    )
    assert report["inputs"]["total_input_files"] == 2
    assert report["candidates"]["total"] == 2


def test_status_validation_and_repair_distributions(tmp_path: Path) -> None:
    records = [
        candidate(1, 100, score_status="COMPLETE", repair="NOT_NEEDED"),
        candidate(2, 80, score_status="PARTIAL", repair="SUCCEEDED"),
        candidate(
            3,
            None,
            score_status="NOT_CALCULATED",
            validation="INVALID",
            repair=None,
        ),
        candidate(4, None, score_status="OTHER", validation="OTHER", repair="X"),
    ]
    records[2]["quality_metrics"] = {"repaired": False}
    report = report_for(tmp_path, ("session.json", records, True, 1))
    assert report["status_distribution"] == {
        "COMPLETE": 1,
        "PARTIAL": 1,
        "NOT_CALCULATED": 1,
        "UNKNOWN": 1,
    }
    assert report["metrics_status_distribution"] == {
        "COMPLETE": 4,
        "PARTIAL": 0,
        "NOT_CALCULATED": 0,
        "UNKNOWN": 0,
    }
    assert report["validation_distribution"] == {
        "VALID": 2,
        "INVALID": 1,
        "OTHER_OR_UNKNOWN": 1,
    }
    assert report["repair_distribution"] == {
        "WITHOUT_REPAIR": 1,
        "AFTER_REPAIR": 1,
        "NOT_NEEDED": 1,
        "UNKNOWN": 1,
    }


def test_score_distribution_statistics_and_frequency() -> None:
    records = [
        {"quality_score": 80.0},
        {"quality_score": 90.0},
        {"quality_score": 90.0},
        {"quality_score": 100.0},
    ]
    result = analyze_score_distribution(records)
    assert result["minimum"] == 80
    assert result["maximum"] == 100
    assert result["mean"] == 90
    assert result["median"] == 90
    assert result["unique_score_count"] == 3
    assert result["score_frequency"] == {"80": 1, "90": 2, "100": 1}


def test_unversioned_score_records_remain_unversioned(tmp_path: Path) -> None:
    report = report_for(
        tmp_path,
        ("legacy.json", [candidate(1, 100)], True, 1),
    )
    assert report["score_version_distribution"] == {"unversioned": 1}
    assert report["score_distributions_by_version"]["unversioned"]["count"] == 1


def test_v2_score_records_are_analyzed_by_version(tmp_path: Path) -> None:
    report = report_for(
        tmp_path,
        (
            "v2.json",
            [
                candidate(1, 96, score_version="2.0"),
                candidate(2, 100, score_version="2.0"),
            ],
            True,
            1,
        ),
    )
    assert report["score_version_distribution"] == {"2.0": 2}
    assert report["score_distributions_by_version"]["2.0"]["score_frequency"] == {
        "96": 1,
        "100": 1,
    }


def test_mixed_unversioned_and_v2_scores_warn_without_inference(
    tmp_path: Path,
) -> None:
    report = report_for(
        tmp_path,
        (
            "mixed.json",
            [
                candidate(1, 100),
                candidate(2, 96, score_version="2.0"),
            ],
            True,
            1,
        ),
    )
    assert report["score_version_distribution"] == {
        "2.0": 1,
        "unversioned": 1,
    }
    assert any(
        "Versioned and unversioned" in warning
        for warning in report["analysis_warnings"]
    )


def test_mixed_major_versions_warn_and_remain_separate(tmp_path: Path) -> None:
    report = report_for(
        tmp_path,
        (
            "versions.json",
            [
                candidate(1, 100, score_version="1.0"),
                candidate(2, 96, score_version="2.0"),
            ],
            True,
            1,
        ),
    )
    assert set(report["score_distributions_by_version"]) == {"1.0", "2.0"}
    assert report["score_distribution_comparability"] == (
        "MIXED_VERSIONS_NOT_DIRECTLY_COMPARABLE"
    )
    assert report["session_ties"][
        "sessions_excluded_for_mixed_score_versions"
    ] == 1
    assert report["selection_observation"][
        "sessions_where_comparison_not_possible"
    ] == 1
    assert any(
        "Multiple quality score major versions" in warning
        for warning in report["analysis_warnings"]
    )


def test_same_major_versions_remain_comparable_but_separately_reported(
    tmp_path: Path,
) -> None:
    report = report_for(
        tmp_path,
        (
            "minor-versions.json",
            [
                candidate(1, 96, score_version="2.0"),
                candidate(2, 98, score_version="2.1"),
            ],
            True,
            2,
        ),
    )
    assert set(report["score_distributions_by_version"]) == {"2.0", "2.1"}
    assert report["score_distribution_comparability"] == (
        "COMPARABLE_WITHIN_MAJOR_VERSION"
    )
    assert report["session_ties"][
        "sessions_excluded_for_mixed_score_versions"
    ] == 0


def test_concentration_and_most_common_score(tmp_path: Path) -> None:
    report = report_for(
        tmp_path,
        (
            "session.json",
            [candidate(1, 100), candidate(2, 100), candidate(3, 90)],
            True,
            1,
        ),
    )
    concentration = report["concentration"]
    assert concentration["score_100_count"] == 2
    assert concentration["score_100_rate"] == pytest.approx(2 / 3)
    assert concentration["most_common_score"] == 100
    assert concentration["most_common_score_rate"] == pytest.approx(2 / 3)


def test_session_top_tie_and_all_scores_equal(tmp_path: Path) -> None:
    report = report_for(
        tmp_path,
        ("tie.json", [candidate(1, 100), candidate(2, 100)], True, 1),
        ("varied.json", [candidate(1, 80), candidate(2, 100)], True, 2),
    )
    ties = report["session_ties"]
    assert ties["sessions_with_multiple_scored_candidates"] == 2
    assert ties["sessions_with_top_score_tie"] == 1
    assert ties["top_score_tie_rate"] == 0.5
    assert ties["sessions_where_all_scored_candidates_equal"] == 1
    assert ties["average_unique_scores_per_session"] == 1.5


@pytest.mark.parametrize(
    ("scores", "selected_index", "expected_key"),
    [
        ([100, 80], 1, "sessions_where_selected_had_highest_score"),
        ([80, 100], 1, "sessions_where_selected_did_not_have_highest_score"),
        ([100, 100], 1, "sessions_where_selected_tied_for_highest_score"),
    ],
)
def test_selected_candidate_relationship(
    tmp_path: Path,
    scores: list[int],
    selected_index: int,
    expected_key: str,
) -> None:
    report = report_for(
        tmp_path,
        (
            "session.json",
            [candidate(index + 1, value) for index, value in enumerate(scores)],
            True,
            selected_index,
        ),
    )
    observation = report["selection_observation"]
    assert observation[expected_key] == 1
    assert observation["selected_candidate_count"] == 1


def test_selected_comparison_unavailable_without_scored_selection(tmp_path: Path) -> None:
    report = report_for(
        tmp_path,
        ("session.json", [candidate(1, None)], True, 1),
    )
    assert report["selection_observation"][
        "sessions_where_comparison_not_possible"
    ] == 1


def test_breakdown_analysis_includes_known_and_unknown_items(tmp_path: Path) -> None:
    report = report_for(
        tmp_path,
        (
            "session.json",
            [
                candidate(1, 80),
                candidate(
                    2,
                    90,
                    breakdown={
                        "base": {"points": 50, "reason": "Base"},
                        "future_item": {"points": 7.5, "reason": "Future"},
                    },
                ),
            ],
            True,
            1,
        ),
    )
    analysis = report["breakdown_analysis"]
    assert analysis["base"]["appearance_count"] == 2
    assert analysis["base"]["average_points"] == 50
    assert analysis["future_item"]["points_frequency"] == {"7.5": 1}
    assert analysis["future_item"]["missing_count"] == 1


def test_warning_frequency_and_path_sanitization(tmp_path: Path) -> None:
    warning = "Review C:/Users/private/generated/candidate.json before use"
    report = report_for(
        tmp_path,
        (
            "session.json",
            [candidate(1, 80, warnings=[warning]), candidate(2, 90, warnings=[warning])],
            True,
            1,
        ),
    )
    frequencies = report["warning_analysis"]["warning_frequency"]
    assert list(frequencies.values()) == [2]
    assert "C:/Users/private" not in json.dumps(report)
    assert "<local-path>" in next(iter(frequencies))


def test_malformed_candidate_record_is_safe(tmp_path: Path) -> None:
    report = report_for(
        tmp_path,
        ("session.json", ["bad", candidate(2, True)], True, 2),
    )
    assert report["candidates"] == {"total": 2, "scored": 0, "unscored": 2}
    assert report["warning_analysis"]["malformed_record_count"] >= 2


def test_broken_json_does_not_prevent_other_file_analysis(tmp_path: Path) -> None:
    good = tmp_path / "good.json"
    bad = tmp_path / "bad.json"
    write_document(good, [candidate(1, 100)])
    bad.write_text("{broken", encoding="utf-8")
    report = build_analysis_report(
        [bad, good], generated_at="fixed", cwd=tmp_path
    )
    assert report["inputs"]["successfully_parsed_files"] == 1
    assert report["inputs"]["failed_file_count"] == 1
    assert report["candidates"]["scored"] == 1


def test_main_returns_one_when_all_inputs_fail(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("bad", encoding="utf-8")
    assert main([str(bad)], now=lambda: "fixed") == 1


def test_main_returns_two_for_partial_file_failure(tmp_path: Path) -> None:
    good = tmp_path / "good.json"
    bad = tmp_path / "bad.json"
    write_document(good, [candidate(1, 100)])
    bad.write_text("bad", encoding="utf-8")
    assert main([str(good), str(bad)], now=lambda: "fixed") == 2


def test_main_returns_one_without_inputs() -> None:
    assert main([], now=lambda: "fixed") == 1


def test_null_only_scores_have_empty_distribution_warning(tmp_path: Path) -> None:
    report = report_for(
        tmp_path,
        ("session.json", [candidate(1, None)], True, 1),
    )
    assert report["score_distribution"]["count"] == 0
    assert report["score_distribution"]["mean"] is None
    assert report["concentration"]["score_100_rate"] is None
    assert any("No finite" in warning for warning in report["analysis_warnings"])


def test_integer_and_float_scores_have_stable_json_keys(tmp_path: Path) -> None:
    report = report_for(
        tmp_path,
        ("session.json", [candidate(1, 80), candidate(2, 80.5)], True, 1),
    )
    assert report["score_distribution"]["score_frequency"] == {
        "80": 1,
        "80.5": 1,
    }


@pytest.mark.parametrize("invalid_score", [True, float("nan"), float("inf")])
def test_bool_nan_and_infinity_are_not_scores(
    tmp_path: Path, invalid_score: object
) -> None:
    report = report_for(
        tmp_path,
        ("session.json", [candidate(1, invalid_score)], True, 1),
    )
    assert report["candidates"]["scored"] == 0
    assert report["warning_analysis"]["malformed_record_count"] >= 1


def test_report_does_not_store_absolute_input_or_candidate_paths(tmp_path: Path) -> None:
    external = tmp_path.parent / "external-private-session.json"
    write_document(external, [candidate(1, 100)])
    report = build_analysis_report([external], generated_at="fixed", cwd=tmp_path)
    serialized = json.dumps(report)
    assert str(tmp_path.parent).replace("\\", "/") not in serialized.replace("\\", "/")
    assert "C:/private/user" not in serialized
    assert report["inputs"]["failed_files"] == []


def test_stdout_summary_contains_major_sections(tmp_path: Path) -> None:
    report = report_for(
        tmp_path,
        ("session.json", [candidate(1, 100)], True, 1),
    )
    output = print_analysis_summary(report)
    for text in (
        "Candidate Quality Score Analysis",
        "Input files:",
        "Candidate records:",
        "Minimum:",
        "100-point rate:",
        "Sessions analyzed:",
        "Selected candidates:",
        "Warnings:",
    ):
        assert text in output


def test_output_json_is_written_and_parent_is_created(tmp_path: Path) -> None:
    source = tmp_path / "session.json"
    output = tmp_path / "missing" / "score_analysis.json"
    write_document(source, [candidate(1, 100)])
    assert main(
        [str(source), "--output", str(output)], now=lambda: "fixed"
    ) == 0
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["generated_at"] == "fixed"
    assert saved["score_distribution"]["maximum"] == 100


def test_glob_input_expansion(tmp_path: Path) -> None:
    write_document(tmp_path / "one.summary.json", [candidate(1, 80)], session=False)
    write_document(tmp_path / "two.summary.json", [candidate(1, 90)], session=False)
    assert len(expand_input_paths([str(tmp_path / "*.summary.json")])) == 2


def test_analysis_does_not_modify_input_payload(tmp_path: Path) -> None:
    source = tmp_path / "session.json"
    payload = write_document(source, [candidate(1, 100)])
    before = copy.deepcopy(payload)
    build_analysis_report([source], generated_at="fixed", cwd=tmp_path)
    assert payload == before
    assert json.loads(source.read_text(encoding="utf-8")) == before


def test_possible_duplicates_are_reported_but_retained(tmp_path: Path) -> None:
    shared = candidate(1, 100)
    report = report_for(
        tmp_path,
        ("session.json", [shared], True, 1),
        ("summary.json", [shared], False, 1),
    )
    assert report["candidates"]["total"] == 2
    assert report["inputs"]["duplicate_detection_status"] == (
        "POSSIBLE_DUPLICATES_FOUND"
    )
    assert report["inputs"]["possible_duplicate_candidate_records"] == 1


def test_unknown_repair_value_is_not_assumed_to_be_unrepaired() -> None:
    assert normalize_repair_status({"repair_status": "MAYBE"}) == "UNKNOWN"


def test_analysis_does_not_change_selection_or_scoring_functions() -> None:
    candidates = [
        {
            "candidate_index": 1,
            "final_validation_status": "VALID",
            "repair_status": "NOT_NEEDED",
            "quality_score": 80,
        },
        {
            "candidate_index": 2,
            "final_validation_status": "VALID",
            "repair_status": "NOT_NEEDED",
            "quality_score": 100,
        },
    ]
    selected, _reason = select_best_candidate(candidates)
    assert selected is candidates[0]
    assert calculate_quality_score(
        {
            "footprint_area": 1,
            "aspect_ratio": 1,
            "has_door": True,
            "has_window": True,
            "opening_to_wall_area_ratio": 0.2,
        },
        "VALID",
        "NOT_NEEDED",
    )["quality_score"] == 100


def test_analyzer_has_no_network_or_dangerous_execution() -> None:
    source = ANALYZER.read_text(encoding="utf-8").lower()
    for token in (
        "urlopen",
        "requests",
        "httpx",
        "socket",
        "subprocess",
        "eval(",
        "exec(",
        "system(",
        "spawn(",
        "importlib",
    ):
        assert token not in source
