# Candidate Quality Score Policy v2 Design

Status: Draft proposal. This document defines design constraints and evaluation
work for a future implementation. It does not change scoring, ranking, or best
candidate selection.

## 1. Background

ArchSeed v0.6 added multiple candidate generation and deterministic best
candidate selection. v0.7 added Candidate Quality Metrics, Candidate Quality
Score, and saved-score distribution analysis.

The first real-data analysis used `ministral-3-14b-instruct-2512` and observed:

- 3 sessions and 9 candidates
- every candidate `VALID`
- every score status `COMPLETE`
- every score equal to 100
- 100-point concentration of 100%
- a top-score tie and an all-candidates-equal result in every session
- every selected candidate tied for highest score
- no warnings, malformed records, or missing breakdowns

This is not evidence of an analyzer defect. It shows that the current policy
did not discriminate among this small set of normal candidates. The current
score remains useful as an explainable static observation, but its suitability
for ranking is unverified. Score Policy v2 must therefore be designed and
benchmarked before ranking changes are considered.

## 2. Current Policy Purpose

The current implementation confirms only the following behavior:

- non-`VALID` candidates receive `NOT_CALCULATED`
- a `VALID` candidate receives validation points
- no-repair candidates receive more repair points than repaired candidates
- observed door and window presence receive points
- aspect ratios inside configured observation ranges receive points
- an opening-to-wall-area ratio inside the configured observation range
  receives points, while a high ratio can receive a penalty
- a positive footprint is required for `COMPLETE`, but adds no points
- missing or unusual values create warnings and may produce `PARTIAL`
- final scores are clamped to 0 through 100

These rules are static observations. Door or window points do not establish
that either opening type is required. Aspect and opening-ratio ranges are not
regulatory or architectural-quality guarantees.

Best candidate selection is separate and remains:

1. final validation status is `VALID`
2. no repair is preferred
3. earlier generation order breaks ties

Candidate Quality Score is not used by this selection.

## 3. Analysis of 100-Point Concentration

### Confirmed Facts

The current breakdown can award:

| Component | Typical normal candidate |
| --- | ---: |
| base | 50 |
| `VALID` | 20 |
| repair not needed | 10 |
| door present | 5 |
| window present | 5 |
| aspect ratio from 1.0 through 2.0 | 5 |
| opening ratio above 0 through 0.40 | 5 |
| **Total before clamp** | **100** |

Further confirmed behavior:

- repaired `VALID` candidates receive 5 repair points instead of 10
- door and window components test presence, not count or suitability
- footprint size does not affect points when it is positive
- wall count does not affect the score
- aspect ratios through 2.0 receive full aspect points; ratios through 3.0
  still receive partial points
- opening ratios through 0.40 receive full opening-ratio points
- candidate-to-candidate differences are not part of the absolute score
- the final score is clamped to 100

### Inferred Concentration Factors

The observed concentration is consistent with several design properties:

- the base and validation components already provide 70 points
- common generated buildings can satisfy every positive component
- presence checks for door and window are easy for the tested prompt family to
  satisfy and do not distinguish quantity or placement
- normal aspect and opening ratios span broad point plateaus
- footprint and wall-count variation remain observational
- there are few penalties for otherwise `VALID` and `COMPLETE` candidates
- clamp-to-100 removes any distinction if future positive components exceed
  the ceiling
- data availability and candidate quality are partly mixed: presence of a
  metric or opening can increase score without demonstrating better quality

These are design inferences from the implementation and the nine-candidate
result. They are not proof that every prompt or model produces 100.

### Additional Data Required

The following cannot be concluded from nine normal candidates:

- whether repaired candidates create useful score separation
- whether `PARTIAL` handling produces a safe ordering
- whether extreme geometry receives sufficient penalties
- whether the current ranges generalize across building types
- whether component distributions vary across prompts and models
- whether clamp behavior affects real candidates outside the observed set

## 4. Policy v2 Principles

Policy v2 should be:

- deterministic and local-only
- explainable from stored inputs and breakdown data
- explicitly versioned
- an absolute evaluation of one candidate, separate from ranking
- prompt-independent for this phase
- conservative with missing data and never infer absent values
- explicit that it does not guarantee code compliance or architectural quality

Additional rules:

- do not make a perfect score routine
- separate metric availability from quality observations
- keep `PARTIAL` distinct from `COMPLETE`; do not normalize missing components
  into a complete-equivalent score
- do not compare non-`VALID` candidates through a normal numeric score
- retain raw component results and explain the relationship between component
  totals and the final score
- distinguish warnings from score penalties
- decide and document whether a pre-clamp total is retained
- do not affect the current selector until a later reviewed change

## 5. Candidate Score Structures

### Option A: Base + Bonus - Penalty

Possible components:

- base
- validation adjustment
- repair penalty
- completeness adjustment
- door/window observation
- aspect-ratio adjustment
- opening-ratio adjustment

Advantages:

- easiest migration from the current implementation
- simple arithmetic and familiar breakdown

Risks:

- additive bonuses can reproduce 100-point concentration
- availability checks can remain mixed with quality observations
- missing-component behavior becomes difficult to explain

### Option B: Weighted Components

Possible components:

- structural validity
- metric completeness
- repair stability
- opening observations
- geometric plausibility

Each component has a bounded internal result and an explicit maximum weight.

Advantages:

- component ceilings make the breakdown explicit
- missing, omitted, and not-applicable states can be represented separately
- component distributions can be analyzed independently
- future versions can evolve one component while retaining policy metadata
- better suited to controlled benchmarking before ranking

Risks:

- missing-component rules require careful definition
- weights and soft ranges require fixtures and benchmark evidence
- apparently precise component numbers can be overinterpreted

### Option C: Penalty-First

Start at 100 and deduct for:

- repair
- missing expected observations
- extreme aspect ratio
- extreme opening ratio
- incomplete metrics
- warnings with defined scoring significance

Advantages:

- straightforward explanation of deductions
- abnormal fixtures should be visibly lower

Risks:

- normal candidates can again cluster at 100
- prompt-independent policy cannot know whether an opening is expected
- warnings and penalties can be conflated

### Comparison

| Criterion | A: Base/Bonus/Penalty | B: Weighted | C: Penalty-First |
| --- | --- | --- | --- |
| Explainability | High | High with structured breakdown | High |
| Implementation effort | Low | Medium | Low |
| 100-point concentration risk | High | Medium, benchmark-dependent | High |
| `PARTIAL` support | Difficult | Explicit component states | Difficult |
| Version management | Moderate | Strong component boundaries | Moderate |
| Future extension | Moderate | High | Moderate |
| Ranking evaluation | Limited plateaus | Best diagnostic detail | Limited plateaus |
| Current breakdown compatibility | High | Requires migration | Moderate |

### Recommended Structure

Option B, Weighted Components, is recommended for implementation experiments.
It most clearly separates component availability, component quality, and
maximum contribution. It also gives the analysis workflow useful component
variance.

Final weights and thresholds are intentionally not fixed in this design PR.
The available real dataset is too small and too concentrated. Proposed values
must first be exercised against the fixtures and benchmark plan below.

## 6. Score Status Comparison

Recommended status policy:

- `VALID` and `COMPLETE`: eligible for normal score comparison in a future
  ranking policy
- `VALID` and `PARTIAL`: retain a score and breakdown for observation, but keep
  in a separate comparison group
- `INVALID` or `NOT_CALCULATED`: exclude from normal numeric comparison
- compare status before score
- do not treat missing components as zero-quality facts
- do not re-normalize the denominator for `PARTIAL`

`validation_status` is a validity gate. `quality_score_status` describes score
data completeness. They are related but not interchangeable. A `VALID`
candidate can still have a `PARTIAL` score.

This is a future comparison contract, not a ranking implementation.

## 7. Repair Treatment

Repair information has two distinct uses:

- an absolute score component can record reduced confidence or stability
- a future ranking policy can prefer no-repair candidates before score

Applying both without an explicit policy would double-count the same fact.
The implementation PR must document whether repair is represented in score,
ranking, or both, and why.

Recommended initial direction:

- retain a bounded repair-stability component in Policy v2 for standalone
  explanation
- preserve repair metadata and attempt count
- do not infer repair severity from attempt count alone
- if a later ranking retains no-repair priority, benchmark and document the
  combined effect before adoption
- do not estimate severity when the saved repair information is insufficient

## 8. Metric Classification

| Metric | v2 classification | Reason |
| --- | --- | --- |
| `footprint_area` | Observation only | Larger is not inherently better; no prompt target exists |
| `aspect_ratio` | Score with soft-range warning/penalty | Extreme values are observable, but acceptable ranges are use-dependent |
| `wall_count` | Warning/observation | More walls are not inherently better; may help detect topology anomalies |
| `opening_count` | Observation | Expected count is unknown without prompt requirements |
| `door_count` | Observation; possible future prompt-aware input | Presence is not a universal quality requirement |
| `window_count` | Observation; possible future prompt-aware input | Presence is not a universal quality requirement |
| `has_door` | Warning/observation | Must not create a large unconditional bonus |
| `has_window` | Warning/observation | Must not create a large unconditional bonus |
| `total_opening_area` | Observation | Absolute area depends on building size and intent |
| `opening_to_wall_area_ratio` | Score with soft-range warning/penalty | Useful for extreme-value detection, not a universal ideal or code check |
| `validation_status` | Gate, not score component | Scoring and gating it would double-count validity |
| `repaired` | Policy decision required | Score and ranking uses must not double-count repair |

Soft ranges are proposals to detect extremes. They do not establish regulatory
limits or preferred architectural forms.

## 9. Prompt-Aware Boundary

Policy v2 remains prompt-independent. A fixed policy cannot safely judge
requests such as "no doors", "many windows", "a long narrow building", or "a
small warehouse" without structured requirements.

Prompt-aware evaluation should be a separate policy and version. A future
workflow may compare a candidate with JSON-encoded design requirements.
Subjective LLM scoring is not part of Policy v2 and must not be introduced as
an implicit component.

## 10. Score Version Design

Proposed metadata:

```json
{
  "quality_score_version": "2.0",
  "scoring_policy_id": "archseed-static-geometry",
  "scoring_policy_version": "2.0",
  "breakdown_schema_version": "2"
}
```

Version rules:

- use dotted numeric strings for score and policy versions
- increment major when score meaning, component set, comparison contract, or
  breakdown compatibility changes
- increment minor for backward-compatible clarification or added optional
  metadata that does not change existing results
- do not directly compare scores from different major versions
- aggregate analysis by version
- treat records without version metadata as `unversioned`
- never infer a v1 version onto stored historical data
- never rewrite historical candidate/session JSON during migration
- any rescoring must be an explicit CLI or separate workflow

The exact metadata placement and serialization are deferred to implementation.

## 11. Breakdown Schema v2

Proposed component shape:

```json
{
  "component": "geometry_plausibility",
  "points": 18,
  "max_points": 25,
  "status": "COMPLETE",
  "reasons": [
    "Aspect ratio is within the proposal soft range."
  ],
  "metrics": {
    "aspect_ratio": 1.5
  },
  "thresholds": {
    "preferred_min": 1.0,
    "preferred_max": 2.0
  },
  "warnings": []
}
```

Required design behavior:

- `points` and `max_points` show contribution and ceiling
- `status` distinguishes `COMPLETE`, `PARTIAL`, `OMITTED`, and
  `NOT_APPLICABLE` where relevant
- `reasons` explain applied evaluation
- `metrics` records only observed source values
- `thresholds` records policy inputs used for the result
- `warnings` remain distinct from deductions
- the policy and breakdown schema versions accompany the overall score
- component sum, pre-clamp total if retained, and final score have an explicit
  documented relationship
- `calculated_at` is unnecessary for deterministic equality and should remain
  session metadata unless an audit requirement is identified

The current flat component mapping is not assumed compatible with v2. Migration
must preserve v1 records and let readers branch by version.

## 12. Draft Score Meaning

If Policy v2 retains a 0 through 100 presentation, provisional language is:

- 90-100: no major issue detected by the configured static checks
- 70-89: one or more warnings or limited penalties
- 40-69: multiple static quality concerns
- 0-39: substantial caution required before comparison

These bands are proposals only. They are not validated thresholds and do not
represent building-code compliance or architectural quality. Benchmark results
must precede adoption.

## 13. Pre-Implementation Data Plan

Deterministic fixtures should cover:

- `VALID` / `COMPLETE` / no repair
- `VALID` / `COMPLETE` / repaired
- `VALID` / `PARTIAL`
- `INVALID` / `NOT_CALCULATED`
- no door, no window, and no openings
- extreme aspect ratio
- extremely low and high opening ratios
- breakdown warnings
- fixtures producing multiple scores
- fixtures intentionally producing ties
- records with different score versions

Proposed real benchmark:

- 3 to 5 prompts
- at least 2 local models
- at least 3 candidates per prompt/model combination
- repaired and unrepaired outcomes
- at least 30 candidates as an initial target

This PR does not generate benchmark data.

## 14. Evaluation Measures

After implementation, compare v1 and v2 with the score analysis workflow:

- 100-point concentration
- unique score count
- standard deviation
- median and mode
- score range and percentiles
- top-score tie rate
- all-candidates-equal session rate
- agreement between current selection and highest score
- distributions by score status, repair outcome, warning, and version
- malformed record count
- component-level variance
- entropy if its interpretation is documented

Standard deviation, entropy, percentile, score-range, component-variance, and
version-aware aggregation may require separate Analysis CLI changes.

## 15. Adoption Conditions

Exact thresholds will be set after benchmarking. Minimum qualitative evidence:

- not every candidate scores 100
- more than one score appears in representative data
- not every session is tied
- clearly abnormal fixtures score below corresponding normal fixtures
- repaired outcomes behave as designed
- `PARTIAL` does not incorrectly outrank `COMPLETE`
- identical inputs and policy versions produce identical scores
- component totals and final score are explainable
- score and breakdown versions are saved

Passing these checks permits review; it does not automatically enable ranking.

## 16. Boundary With Ranking

Score Policy v2 evaluates one candidate as an absolute static observation.
Ranking Policy compares candidates within the same session and defines the
priority of validation, score status, repair, score, and generation order.

Possible future orders:

1. `VALID` -> `COMPLETE` -> no repair -> score -> generation order
2. `VALID` -> no repair -> `COMPLETE` -> score -> generation order
3. `VALID` -> `COMPLETE` -> score -> no repair -> generation order

Option 1 is the safest provisional direction because it gates incomplete score
data before comparing repair and score, while remaining close to the current
no-repair preference. Its risk is double-valuing repair if Policy v2 also
applies a repair penalty. Option 2 preserves current repair priority but may
prefer a `PARTIAL` result. Option 3 gives score more influence before the
repair preference has been benchmarked.

No order is adopted or implemented by this PR.

## 17. Migration Plan

1. Finalize this Policy v2 design.
2. Implement Policy v2 and versioned serialization in a separate PR.
3. Compare v1 and v2 score distributions on fixtures and benchmark data.
4. Design Ranking Policy only after reviewing those results.
5. Implement ranking or expand benchmarks in a later PR.

Migration rules:

- do not rewrite v1 saved JSON
- save v2 with explicit version metadata
- analyze scores by version
- do not change best candidate selection during v2 implementation/evaluation
- do not use a newly observed score difference for ranking without review

## 18. Implementation Task Breakdown

| Task | Purpose | Candidate files | Test focus | Out of scope |
| --- | --- | --- | --- | --- |
| Policy constants | Define IDs, versions, component ceilings, and proposed ranges | `tools/candidate_quality_score.py` or new policy module | deterministic constants; bounds | ranking |
| Version metadata | Serialize score/policy/breakdown versions | score result and candidate summary/session integration | exact metadata; unversioned compatibility | historical rewrite |
| Component evaluators | Isolate weighted component calculations | score policy module | boundary, missing, and abnormal fixtures | prompt interpretation |
| Breakdown schema | Emit points, maxima, statuses, reasons, metrics, thresholds, warnings | score policy module | component sum and schema states | UI |
| Status handling | Preserve `COMPLETE`, `PARTIAL`, `NOT_CALCULATED` semantics | score policy module | no normalization; invalid gating | ranking |
| Repair policy | Apply only the approved absolute-score treatment | score policy module | repaired/unrepaired and missing metadata | severity inference |
| Geometry soft ranges | Detect extremes without claiming universal ideals | score policy module | threshold boundaries | regulatory checks |
| Warning handling | Keep warnings separate from penalties | score policy module | warning-only vs deduction cases | automatic correction |
| Serialization/output | Include v2 fields in session, summary, and stdout | candidate generation/output modules | round trip; ignored artifacts | schema change |
| Backward compatibility | Read existing unversioned records without mutation | analyzer/reader modules | v1 and v2 fixtures | inferred rescoring |
| Analysis support | Group and compare records by score version | `tools/analyze_candidate_scores.py` | cross-version separation | direct major-version comparison |
| Documentation | Record policy, migration, and non-guarantees | README and docs | link validation | ranking promise |

Each implementation PR must keep generated candidate/session artifacts out of
Git and must explicitly state that ranking and selection remain unchanged.
