# Explore manual split trim flow
_Exported on 8/1/2026 at 14:49:13 GMT+2 from Cursor (3.13.25)_

---

**User**

Investigate the PDF preprocessing workflow in f:\prog\research-tools related to manual split + trimming. The bug: after a successful manual split (e.g. 52/48), when user chooses "Add trimming", the code logs "manual split requested without manual_split_ratio" and produces a trimmed but NON-split PDF.

Find:
1. Where "manual split requested without manual_split_ratio" is logged
2. How the preview menu options for "Add trimming" / "Drop trimming" / "manual split" restart preprocessing
3. How manual_split_ratio is supposed to be preserved across restarts
4. Recent git changes today (Aug 1 2026 or recent commits) related to this workflow

Search in scripts/, shared_tools/, and related files. Look at git log and git diff for today's changes.

Return:
- Exact file paths and line numbers for the bug
- The call chain when "Add trimming" is chosen after manual split
- What state (manual_split_ratio, force_manual_split, etc.) is lost and why
- Relevant code snippets
- Summary of today's related commits/diffs

---

**Cursor**

Found the log site. Now let me trace the preview menu and how preprocessing restarts.

Both handler sets have the same issue. Now let me check today's diffs for how this area changed.

The working-tree diff doesn't touch the preview loop (hunks are elsewhere), so the buggy code is as committed today. Let me check when the missing-ratio pattern was introduced.

All the facts are in hand. Here is the full investigation report.

# Bug report: manual split lost when "Add trimming" is chosen

## 1. Where the error is logged

`f:\prog\research-tools\scripts\paper_processor_daemon.py`, line 6485, inside `_preprocess_pdf_with_options` (defined at line 6423):

```6480:6493:scripts/paper_processor_daemon.py
        if split_method != 'none':
            if split_method == 'manual':
                # Forced split from original (post-border) with user-defined ratio.
                # Always restart from original two-up pages — never from an already-split PDF.
                if manual_split_ratio is None:
                    self.logger.error("manual split requested without manual_split_ratio")
                    preprocessing_state['split_method'] = 'manual'
                    preprocessing_state['split_attempted'] = True
                    preprocessing_state['split_succeeded'] = False
                else:
                    preprocessing_state['split_method'] = 'manual'
                    ...
                    preprocessing_state['manual_split_ratio'] = manual_split_ratio
```

When the ratio is `None`, the function silently skips the split (leaving `current_pdf` unsplit) and then still runs the trim step at lines 6604–6609 — which is exactly why you get a trimmed but non-split PDF.

## 2. The call chain when "Add trimming" is chosen after a manual split

There are two parallel implementations of the preview menu; both have the same bug.

**A. Daemon preview loop (the one used by today's early-preprocessing flow):** `_preview_and_modify_preprocessing` (`scripts/paper_processor_daemon.py`, line 6613). After a successful manual split, `preprocessing_state` holds `split_method='manual'`, `manual_split_ratio=52.0`. The user picks "Add trimming" (`add_trim` action), handled at lines 6837–6850:

```6837:6850:scripts/paper_processor_daemon.py
                    elif action == 'add_trim':
                        # Add trimming
                        new_state = preprocessing_state.copy()
                        new_state['trim_leading'] = True
                        print("\n🔄 Restarting preprocessing with trimming...")
                        processed_pdf, new_state = self._preprocess_pdf_with_options(
                            original_pdf,
                            border_removal=new_state.get('border_removal', True),
                            split_method=new_state.get('split_method', 'auto'),
                            trim_leading=True
                        )
                        preprocessing_state = new_state
                        last_previewed_pdf = None
```

It forwards `split_method='manual'` (from state) but **never passes `manual_split_ratio`**, which defaults to `None` in the signature (line 6429). Chain: `add_trim` handler (6842) → `_preprocess_pdf_with_options(..., split_method='manual', manual_split_ratio=None)` → line 6484 `manual_split_ratio is None` → error logged at 6485, `split_succeeded=False`, PDF left unsplit → trim step at 6604 runs anyway → returns trimmed, non-split PDF.

**B. Navigation-page version:** `_handle_add_trimming` in `scripts/handle_item_selected_pages.py`, lines 1723–1738 — identical omission (calls `daemon._preprocess_pdf_with_options` at line 1729 with `split_method=preprocessing_state.get('split_method', 'auto')`, no ratio).

## 3. What state is lost and why

- **`manual_split_ratio` is lost twice.** First, it is stored only in `preprocessing_state`, and the restart handlers pass `split_method` through but not the ratio as the function argument. Second, `_preprocess_pdf_with_options` builds a **fresh** `preprocessing_state` (lines 6459–6464), and the `manual_split_ratio is None` branch (6486–6488) does not write `manual_split_ratio` into it — so after one bad restart the ratio is gone from state entirely, and the menu label reverts from "Split by manual definition (52/48)" to the generic "(e.g., 55/45)" (lines 6730–6736).
- **`force_manual_split` does not exist** anywhere in the codebase — the only carrier of manual-split intent is `split_method='manual'` + `manual_split_ratio`.
- **Same bug in sibling handlers:** `drop_border` (daemon line 6768 / `handle_item_selected_pages.py` line 1637) and `drop_trim` (daemon line 6827 / line 1711) also forward `split_method` from state without the ratio, so any of these options after a manual split hits the same failure. `improve_split`, `use_5050`, and `drop_split` are unaffected because they force a specific method.

**The fix** is to pass `manual_split_ratio=preprocessing_state.get('manual_split_ratio')` in the `drop_border`, `drop_trim`, and `add_trim` restart calls in both files (and ideally also persist the ratio in the `None` branch of `_preprocess_pdf_with_options`).

## 4. Today's commits (Aug 1 2026)

- **`06a87e0`** (12:10) "Snapshot current daemon and enrichment work before early-preprocessing rewrite" — this commit **introduced the manual-split branch** including the "manual split requested without manual_split_ratio" error message. The `add_trim`/`drop_trim`/`drop_border` restart handlers predate it (commit `580cd16`) and were never updated to forward the new ratio parameter — that mismatch is the root cause.
- **`cb4dc2a`** (12:45) "Move PDF split/trim preprocessing before metadata extraction" — moved preprocessing to Step 0 of `process_paper` (new code around line 4963: `_preprocess_pdf_with_options` → `_preview_and_modify_preprocessing`, result stored in `self._working_pdf` / `self._preprocessing_state`). This made the daemon-side preview loop (`_preview_and_modify_preprocessing`) the one users hit, and removed the later per-attachment preprocessing passes. It renamed menu text ("Accept and proceed", "[z] Cancel this scan") but did not touch the ratio handling, so it exposed rather than caused the bug.
- The **uncommitted working-tree changes** to `scripts/paper_processor_daemon.py` are in other regions (around lines 948, 1485, 3516–3688, 5500–5575, 10272+); none touch the preview loop or `_preprocess_pdf_with_options`, so the buggy code in the working tree matches HEAD.

There is also a test file `tests/test_manual_split_handler.py` covering the manual-split handler, but no test covers "Add trimming after manual split" — which is why this regression slipped through.

The investigation is complete — full details are in the report above. In short: the "Add trimming" handler (line 6842 of `scripts/paper_processor_daemon.py`, and `_handle_add_trimming` at line 1729 of `scripts/handle_item_selected_pages.py`) restarts preprocessing with `split_method='manual'` from state but never passes `manual_split_ratio`, triggering the error at line 6485 and yielding a trimmed, non-split PDF; the ratio is then also dropped from state. The same omission exists in the `drop_border` and `drop_trim` handlers. The manual-split branch came in today's commit `06a87e0`, and commit `cb4dc2a` made this preview loop the primary user path.

