# Fix Zotero author name order (Last, First)

Cleanup tool for a common **old-import** problem in Zotero: a personal name stored as one field (`Brendon Swedlow`) instead of two fields (`lastName=Swedlow`, `firstName=Brendon`).

This is a **library maintenance script**, not part of the paper/book processing daemons. It is safe to run more than once: a clean library reports `0 candidates` and writes nothing.

A Zotero desktop plugin is unnecessary for this import cleanup.

## Problem

Zotero stores people as two fields and institutions as one field:

| Mode | What you want | What old imports often leave |
|------|---------------|------------------------------|
| Two-field person | `Swedlow` + `Brendon` | — |
| One-field person (bug) | — | whole name in lastName / `name`: `Brendon Swedlow` |
| One-field institution | `University of Oslo` | correctly left alone |

Indicators used by this tool:

1. No first name (empty `firstName`, or API `name` set)
2. The stored name has two or more tokens
3. Preferably, that string can be split to match an **existing** two-field author in the same library

## Safety

- **Scan** uses the local `zotero.sqlite` in **read-only** mode. It never writes the SQLite file.
- **Writes** go only through the Zotero **Web API** (`PATCH` on `creators`), and only after confirmation.
- There is **no silent `--yes`**. Apply always asks, or uses a review file where you marked `approved: true`.
- Before any write, a **timestamped backup** is written under `data/backups/creators-YYYYMMDD-HHMMSS.json`. Older backups are never overwritten.
- **Revert** restores `creators_before` only when the item still has exactly what this tool wrote (`creators_after`). If you edited the item in Zotero afterward, that item is skipped.

## Requirements

1. `PATHS.zotero_db_path` in `config.conf` / `config.personal.conf` pointing at your local `zotero.sqlite`
2. Zotero Web API credentials (`APIS.zotero_api_key`, `zotero_library_id`) — same as other research-tools scripts
3. Network access to `api.zotero.org` for apply/revert (desktop Zotero syncs the change)

If the SQLite file is locked (Zotero busy / WAL), the scan retries a few times, then exits with a clear message. Close Zotero or wait for sync and retry the scan. API apply can still work while Zotero is open.

## Commands

From the repo root (activate your usual Python env first):

```bash
# 1) Scan only — no Zotero writes
python scripts/fix_zotero_author_name_order.py

# 2) Interactive review, then optional apply
python scripts/fix_zotero_author_name_order.py --review

# 3) Apply a previously reviewed JSON (groups with approved: true)
python scripts/fix_zotero_author_name_order.py --apply-approved data/cache/author_name_fixes.json

# 4) Revert a backup from an apply run
python scripts/fix_zotero_author_name_order.py --revert data/backups/creators-TIMESTAMP.json
```

### Flags

| Flag | Meaning |
|------|---------|
| `--include-unmatched` | Also show **medium** confidence heuristic splits (no matching two-field author in the library yet) |
| `--include-skipped` | Show names you previously answered `n` to |
| `--suggestions-out PATH` | Where to write the scan/review JSON (default `data/cache/author_name_fixes.json`) |
| `--skipped-file PATH` | Skip-memory file (default `data/cache/author_name_fixes_skipped.json`) |

### Review keys

During `--review`:

- `y` — approve this suggestion
- `n` — skip and remember (hidden on later scans unless `--include-skipped`)
- `e` — edit lastName / firstName, then approve
- `a` — approve this and all remaining
- `q` — quit review; keep decisions so far (does not apply until you confirm)

After review, the script asks once more before calling the Web API.

## Confidence tiers

- **High** — some suffix of the tokens equals an existing well-formed `lastName`, and the remaining prefix equals that author’s `firstName` (case-insensitive). Longest last-name suffix wins (`van der Waals` over `Waals`).
- **Medium** — heuristic split (last token, or particle-aware surname such as `van` / `de` / `von` / `der`), but no library twin. Hidden unless `--include-unmatched`.

Organizations (`University`, `Institute`, `Foundation`, `Inc`, `Press`, …), already two-field people, single-token last names, and comma-style `Last, First` strings are never candidates.

Suggestions are **grouped by the malformed name string**, not by item. Approving `Brendon Swedlow → Swedlow, Brendon` updates every item that still uses that one-field form.

## Running a second time

Expect one cleanup pass for old imports, but re-runs are designed to be safe.

| Situation | What happens |
|-----------|----------------|
| Names already fixed (`Swedlow` + `Brendon`) | Not candidates. Silent skip. |
| Whole library clean | Prints `0 candidates` and exits. No new backup. |
| You skipped a group with `n` | Name stored in skip memory; hidden until `--include-skipped`. |
| You quit mid-review; some groups applied | Applied names gone; remaining proposed again. New backup covers **only this run**. |
| First pass had no two-field twin (everyone was one-field) | High-confidence list may be empty. Use `--include-unmatched`, or fix one person in Zotero, then scan again — the index grows and can unlock the rest. |
| Stale `--apply-approved` file | GET each item. Already fixed → skip. Creators edited in Zotero since the plan → **do not PATCH** (`skipped_changed`). |
| `--revert` | Reverts only if current creators still equal `creators_after`. Further edits → skip and warn. |
| Revert, then scan again | Malformed names become candidates again; skip memory still applies. |

## What it will not change

- Institutions and other intentional one-field creators
- Already correct two-field people
- Names you skipped (`n`), unless you pass `--include-skipped`
- Items whose creators changed in Zotero after the backup / plan was made

## Limitations

- Compound surnames and particles are handled heuristically; review carefully when unsure.
- High confidence needs at least one well-formed two-field copy of that person in the library (or a prior medium/manual fix that created one).
- Odd but valid two-field authors (e.g. `lastName="6"`, `firstName="Perry"`) are kept as-is and do not crash the scan. Digit-only surnames are not invented as medium-confidence guesses without a library twin.
- Desktop UI may take a sync cycle to show Web API changes.
- Do not write `zotero.sqlite` by hand; this tool never does.

## Files

| Path | Role |
|------|------|
| `scripts/fix_zotero_author_name_order.py` | CLI: scan, review, apply, revert |
| `shared_tools/utils/author_name_splitter.py` | Pure detection / split / apply-decision logic |
| `tests/test_author_name_splitter.py` | Unit tests |
| `data/cache/author_name_fixes.json` | Last scan / review output |
| `data/cache/author_name_fixes_skipped.json` | Names skipped with `n` |
| `data/backups/creators-*.json` | Per-apply backups for revert |

## Extracting as a standalone public tool

This feature does **not** depend on the paper processor daemon. A future small public repo can copy:

- `shared_tools/utils/author_name_splitter.py`
- `scripts/fix_zotero_author_name_order.py` (or a slimmed CLI that only needs config + `requests`)
- this document
- `tests/test_author_name_splitter.py`
- dependencies: Python 3.11+, `requests`, pytest for tests
- Zotero: local DB path + Web API key

The apply path currently reuses `shared_tools.zotero.paper_processor.ZoteroPaperProcessor` for config loading and PATCH. A standalone fork can replace that with a few dozen lines of `requests` against `https://api.zotero.org`.
