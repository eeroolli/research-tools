# Bug Triage Guide

## Purpose

Define a lightweight, repeatable triage process so bugs are prioritized before implementation.

## Scoring Rubric

Map each dimension to a numeric score:

- Severity:
  - `critical` = 4
  - `high` = 3
  - `medium` = 2
  - `low` = 1
- Frequency:
  - `always` = 4
  - `often` = 3
  - `intermittent` = 2
  - `rare` = 1
- Confidence (root-cause confidence):
  - `high` = 4
  - `medium` = 2
  - `low` = 1
- Effort:
  - `S` = 1
  - `M` = 2
  - `L` = 3

Priority score:

`priority = severity + frequency + confidence - effort`

Use score bands:

- `>= 8`: prioritize in next batch
- `6-7`: candidate for next batch if related
- `<= 5`: backlog unless blocking

## Triage Cadence

### Daily Quick Triage (10-15 min)

- Add new bugs from latest runs.
- Deduplicate similar reports.
- Assign severity + frequency.
- Mark blockers immediately.

### Weekly Deep Triage (30-60 min)

- Assign confidence + effort.
- Compute priority score.
- Group bugs into subsystem batches.
- Select next implementation batch (2-4 related bugs).

## Batch Selection Rules

Prefer batching by shared code path:

- same control-flow area (`process_paper`, restart/back routing)
- same UI/navigation contract (`z/r/q`)
- same subsystem (`enrichment`, `metadata-search`, `queue-control`)

Every selected batch must define:

- target files
- regression tests
- risk notes and rollback expectation

## Definition of Ready

A bug is `ready` only if it has:

- reproducible steps (or explicit non-deterministic note),
- evidence (log/transcript or code refs),
- suspected scope,
- priority score,
- test expectation.

## Definition of Done

A bug is `done` only if:

- fix merged,
- targeted tests pass,
- no related regression in touched flow,
- backlog entry updated with resolution note.
