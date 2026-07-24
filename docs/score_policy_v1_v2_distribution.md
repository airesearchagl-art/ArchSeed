# Score Policy v1/v2 Distribution Comparison

## Decision

**Policy adjustment followed by another distribution review is required.**

Do not implement Ranking and do not connect Quality Score to best-candidate
selection based on this dataset. Policy v2 did not reduce 100-point
concentration or session ties compared with the legacy baseline.

This is an observational result for a small local dataset. It does not establish
regulatory compliance or architectural quality.

## Method

The analyzer read saved Candidate Session JSON without regenerating candidates,
recalculating saved scores, migrating records, or inferring missing versions.
Legacy records are reported as `unversioned`; "v1 baseline" below is a
historical dataset label, not an assigned score version.

Policy v2 data was generated on 2026-07-24 with:

- Provider: LM Studio local server
- Model: `ministral-3-14b-instruct-2512`
- Prompts: 3
- Candidates per prompt: 3
- Repair attempts per candidate: 1
- Temperature: 0
- Output contract: ArchSeed v0.1 JSON
- External cloud API: none
- API key: none

The prompts were:

1. `small office with openings`
2. `compact house with one door and several windows`
3. `two story rectangular building with openings`

These match the three prompt categories used by the saved legacy baseline.
Only the Ministral model had a loaded LM Studio instance during this run. A
second-model comparison was therefore not performed.

## Distribution

| Metric | Legacy baseline (`unversioned`) | Policy v2 (`2.0`) |
| --- | ---: | ---: |
| Sessions | 3 | 3 |
| Candidates | 9 | 9 |
| Minimum | 100 | 100 |
| Maximum | 100 | 100 |
| Mean | 100 | 100 |
| Median | 100 | 100 |
| Mode | 100 | 100 |
| Population standard deviation | 0 | 0 |
| Unique score count | 1 | 1 |
| 100-point concentration | 100% | 100% |
| Top-score tie rate | 3/3 (100%) | 3/3 (100%) |
| All-candidates-equal session rate | 3/3 (100%) | 3/3 (100%) |
| Selected/highest agreement | 3/3 (100%, tied) | 3/3 (100%, tied) |
| Malformed candidate records | 0 | 0 |

The selected/highest agreement does not show score discrimination: every
selected candidate was tied with every other candidate in its session.

## Status, Repair, And Warnings

| Observation | Legacy baseline | Policy v2 |
| --- | ---: | ---: |
| VALID | 9 | 9 |
| COMPLETE score | 9 | 9 |
| PARTIAL score | 0 | 0 |
| NOT_CALCULATED score | 0 | 0 |
| Repair NOT_NEEDED | 9 | 9 |
| Candidates with score warnings | 0 | 0 |

No repair path, partial metrics path, or warning path contributed variation in
this dataset.

## Policy v2 Component Variance

Population variance is calculated from saved component points.

| Component | Mean points | Population variance | Frequency |
| --- | ---: | ---: | --- |
| `structural_validity` | 30 | 0 | 30: 9 |
| `metrics_completeness` | 20 | 0 | 20: 9 |
| `repair_stability` | 15 | 0 | 15: 9 |
| `opening_completeness` | 15 | 0 | 15: 9 |
| `geometry_plausibility` | 20 | 0 | 20: 9 |

`geometry_plausibility` did not distinguish candidates. All observed aspect
ratios were approximately 1.333, and all opening-to-wall-area ratios were
within the preferred range (approximately 0.054 to 0.105).

`opening_completeness` did not dominate the numeric result through variance;
it was a constant full 15 points for all candidates. It still contributes to
the ceiling concentration because every prompt and result contained both a door
and windows.

`repair_stability` and `metrics_completeness` were also constant at full points.
Their behavior for repaired and partial candidates remains unobserved in this
real-data run.

## Aspect Ratio Lower Range

The lower-side aspect-ratio ranges below 0.50 were not observed. Every candidate
had an aspect ratio of approximately 1.333. The current metric uses the longer
footprint side divided by the shorter side, so values below 1 are not expected
for valid positive rectangular footprints. The lower-side policy range remains
unchanged in this analysis branch and should be reviewed as a later Policy
adjustment.

## Analyzer Additions

Analysis version `0.2` adds only missing observations:

- population standard deviation
- all-candidates-equal session rate
- selected/highest agreement count and rate
- component point minimum, maximum, population variance, and standard deviation
- complete per-version partitions for score, status, repair, warning, session,
  selection, and component observations
- an explicit diagnostic-only marker for combined mixed comparison groups

Saved scores are never recalculated. `unversioned`, v1, and v2 records remain
separate, and mixed major versions are not used for direct session comparison.

## Ranking Gate

Decision: **Policy adjustment followed by another distribution review**.

Before Ranking is reconsidered:

- review component weights and soft ranges in a separate Policy change
- test more varied prompts and at least one additional loaded local model
- include repaired, PARTIAL, NOT_CALCULATED, and warning-producing candidates
- verify that unique score count and component variance increase
- set explicit acceptance criteria for concentration and tie rates

Ranking is not implemented by this analysis. The existing selection order
remains `VALID`, then no repair, then generation order.
