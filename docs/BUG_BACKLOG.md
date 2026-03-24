# Bug Backlog

This file is the single source of truth for known bugs.

## Status Lifecycle

- `new`: captured, not triaged yet
- `triaged`: severity/frequency/effort assigned
- `ready`: selected for next implementation batch
- `in_progress`: currently being fixed
- `blocked`: cannot proceed due to dependency/open question
- `done`: fixed and validated

## Bug Card Template

Use this template for every new bug.

```markdown
### BUG-YYYYMMDD-XX - <Short title>
- Status: new
- Severity: low|medium|high|critical
- Frequency: rare|intermittent|often|always
- Reproducibility: yes|no (+ short steps)
- User impact: <1-2 lines>
- Scope: <module/flow>
- Batch tag(s): <comma-separated tags>
- Suspected root cause: <hypothesis>
- Evidence: <log snippet / repro notes / file refs>
- Proposed fix direction: <short plan>
- Risk: <low/medium/high + note>
- Effort: S|M|L
```

## Active Bugs

### BUG-20260324-01 - Enrichment UI not shown after selecting existing Zotero item
- Status: triaged
- Severity: high
- Frequency: intermittent
- Reproducibility: yes (seen in daemon run transcript where selected item proceeds directly to `REVIEW & PROCEED` without enrichment review)
- User impact: user cannot enrich selected Zotero item with online metadata when expected; may require manual rework and reduces trust in flow.
- Scope: selected-item enrichment entry gate and candidate decision pipeline
- Batch tag(s): `enrichment`, `ux-selected-item`
- Suspected root cause: `_auto_enrich_selected_item` returns no bundle or `reject` status (no candidates from online search, or policy rejects best candidate).
- Evidence:
  - `scripts/paper_processor_daemon.py` (`handle_item_selected`, `_auto_enrich_selected_item`)
  - `shared_tools/daemon/enrichment_workflow.py` (`search_online`, `evaluate_and_plan`)
  - `shared_tools/metadata/enrichment_policy.py` (`_decision`)
- Proposed fix direction: add diagnostics for no-candidate vs reject paths; consider broader candidate search fallback using extracted metadata when selected-item metadata search underperforms.
- Risk: medium (changes affect enrichment routing and could increase false positives if not guarded by policy/tests).
- Effort: M

### BUG-20260324-02 - Restart/back flow regressions in scan processing
- Status: triaged
- Severity: high
- Frequency: intermittent
- Reproducibility: yes (historical runs showed restart/back occasionally falling through to next scan)
- User impact: user loses current scan context and must recover manually.
- Scope: `process_paper` control flow, page/non-page navigation handoff, queue processing loop
- Batch tag(s): `ux-navigation`, `restart-back`, `queue-control`
- Suspected root cause: mixed return contracts across nested handlers and ad-hoc prompts.
- Evidence:
  - `scripts/paper_processor_daemon.py`
  - `scripts/handle_item_selected_pages.py`
  - tests under `tests/test_item_selected_back_navigation.py` and `tests/test_restart_queue_behavior.py`
- Proposed fix direction: preserve and monitor unified return contract; add regression coverage for newly discovered edge cases.
- Risk: medium
- Effort: M

## Grouped Bug Clusters

- `enrichment`: candidate retrieval, policy decision gates, selected-item enrichment routing
- `ux-navigation`: page transitions, one-step-back semantics (`z`)
- `queue-control`: restart ordering and current-file continuity
- `metadata-search`: search parameter editing and fallback behavior

## First Planned Batch

Batch ID: `BATCH-20260324-A`

- Included bugs:
  - `BUG-20260324-01` (primary)
  - related `enrichment` diagnostics and routing safeguards
- Goal:
  - reliably surface enrichment review when a valid candidate exists,
  - provide explicit reason visibility when enrichment is skipped.
- Validation expectations:
  - targeted tests for selected-item enrichment routing,
  - no regressions in navigation/restart/back tests,
  - manual transcript validation on one known problematic PDF.
