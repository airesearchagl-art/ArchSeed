# Candidate Ranking Design Preconditions

## Current State

ArchSeed currently selects the best candidate in this order:

1. Final validation status is `VALID`.
2. A candidate that required no repair is preferred.
3. Earlier generation order breaks ties.

Candidate Quality Score is observational and is not used for selection. The
score analysis CLI reads saved score fields without regenerating or rescoring
candidates.

## Metrics To Review Before Ranking

- Rate of candidates scoring 100.
- Number of unique scores.
- Top-score tie rate within sessions.
- Sessions where every scored candidate is equal.
- Agreement between the selected candidate and the highest-score candidate.
- Distribution of `COMPLETE`, `PARTIAL`, and `NOT_CALCULATED` score statuses.
- Candidate warning rate and repeated warning messages.
- Frequency and contribution of each score breakdown component.

These observations measure the current score's discrimination and data quality.
They do not measure regulatory compliance or prove architectural quality.

## Decision Conditions

No numerical threshold for adopting ranking is defined yet because sufficient
representative data has not been collected. Before ranking is implemented,
review the score distribution across varied prompts, candidate counts, repair
outcomes, and local models. Define acceptance thresholds in a separate proposal.

TODO:

- Define the minimum dataset size and prompt diversity.
- Decide acceptable score concentration and tie rates.
- Decide acceptable `PARTIAL` and warning rates.
- Review whether current point weights provide useful discrimination.
- Document migration behavior before changing a scoring policy.

## Future Comparison Rules

The following are design questions, not implemented rules:

- Whether validation status must always rank above score.
- Whether `COMPLETE` should rank above `PARTIAL`.
- Whether `PARTIAL` candidates should be excluded from ranking.
- Whether no-repair status should rank above score.
- Whether generation order should remain the final score tie-breaker.
- Whether candidates created by different score versions can be compared.

## Score Versioning

Analysis reports use `analysis_version: "0.1"`. Existing Candidate Quality Score
records do not have an explicit score version, and the analyzer does not infer
one. The current score storage structure remains unchanged.

Future candidates for a separate change include:

- `quality_score_version`
- scoring policy ID
- breakdown schema version
