"""Page definitions for handle_item_selected flow.

This module defines all pages in the item selection flow using the page-based
navigation system. Pages are self-contained units with display, input validation,
and navigation handlers.
"""

from typing import Dict, List
from shared_tools.ui.navigation import Page, NavigationResult
from shared_tools.utils.filename_generator import FilenameGenerator
from shared_tools.utils.enrichment_ui import parse_index_selection, clear_enrichment_context


def create_review_and_proceed_page(daemon) -> Page:
    """Create REVIEW & PROCEED page.
    
    This is the main entry point after selecting a Zotero item.
    User can proceed, edit tags, or go back.
    """
    def content(ctx):
        lines = [
            "  (y/Enter) Proceed with attaching PDF to this item",
            "  (e) Edit metadata in Zotero first",
            "  (z) Go back to item selection"
        ]
        return lines
    
    def handler_y(ctx):
        """Proceed - prepare metadata and go to PROPOSED ACTIONS."""
        daemon = ctx['daemon']
        pdf_path = ctx['pdf_path']
        selected_item = ctx['selected_item']
        
        # Get scan file info
        scan_size_mb = pdf_path.stat().st_size / 1024 / 1024
        ctx['scan_size_mb'] = scan_size_mb
        
        # Extract metadata from Zotero item
        zotero_authors = selected_item.get('authors', [])
        zotero_title = selected_item.get('title', '')
        zotero_year = selected_item.get('year', selected_item.get('date', ''))
        zotero_item_type = selected_item.get('itemType', 'journalArticle')
        
        # #region agent log
        import json
        from pathlib import Path
        log_path = Path('.cursor/debug.log')
        try:
            with open(log_path, 'a', encoding='utf-8') as f:
                log_entry = {
                    'sessionId': 'debug-session',
                    'runId': 'run1',
                    'hypothesisId': 'B',
                    'location': 'handle_item_selected_pages.py:39',
                    'message': 'Zotero item title extracted',
                    'data': {
                        'zotero_title': zotero_title,
                        'zotero_title_length': len(zotero_title),
                        'zotero_authors': zotero_authors,
                        'zotero_year': zotero_year,
                        'selected_item_keys': list(selected_item.keys())
                    },
                    'timestamp': int(__import__('time').time() * 1000)
                }
                f.write(json.dumps(log_entry) + '\n')
        except Exception:
            pass
        # #endregion
        
        # Log extracted metadata for debugging
        daemon.logger.debug(f"Extracting metadata from Zotero item - Title: '{zotero_title}' (length: {len(zotero_title)}), Authors: {zotero_authors}, Year: {zotero_year}")
        
        # Validate critical fields
        missing_fields = []
        if not zotero_title:
            missing_fields.append('title')
        if not zotero_authors:
            missing_fields.append('authors')
        
        # Show warning if critical fields missing
        if missing_fields:
            print(f"⚠️  WARNING: Zotero item missing: {', '.join(missing_fields)}")
            print("   Cannot generate proper filename without this information.")
            print("   Please edit Zotero item metadata or choose manual processing.")
            confirm_anyway = input("Proceed anyway with placeholder values? [y/n]: ").strip().lower()
            if confirm_anyway != 'y':
                print("⬅️  Going back to review...")
                return NavigationResult.show_page('review_and_proceed')
            # Set placeholders
            if 'title' in missing_fields:
                zotero_title = 'Unknown_Title'
            if 'authors' in missing_fields:
                zotero_authors = ['Unknown_Author']
        
        # Check for filename title override (set in filename_title_override page or edit_metadata)
        filename_title_override = ctx.get('filename_title_override')
        if not filename_title_override:
            # Also check metadata for override (from edit_metadata_interactively)
            metadata = ctx.get('metadata', {})
            filename_title_override = metadata.get('_filename_title_override')
        
        # Use override title if present, otherwise use Zotero title
        title_for_filename = filename_title_override if filename_title_override else zotero_title
        
        # Build metadata using title for filename (override or Zotero title)
        merged_metadata = {
            'title': title_for_filename,
            'authors': zotero_authors,
            'year': zotero_year if zotero_year else 'Unknown',
            'document_type': zotero_item_type
        }
        
        # #region agent log
        try:
            with open(log_path, 'a', encoding='utf-8') as f:
                log_entry = {
                    'sessionId': 'debug-session',
                    'runId': 'run1',
                    'hypothesisId': 'B',
                    'location': 'handle_item_selected_pages.py:69',
                    'message': 'Metadata built before filename generation',
                    'data': {
                        'merged_metadata_title': merged_metadata.get('title', 'MISSING'),
                        'merged_metadata_title_length': len(merged_metadata.get('title', '')),
                        'merged_metadata_authors': merged_metadata.get('authors', []),
                        'merged_metadata_year': merged_metadata.get('year', 'MISSING')
                    },
                    'timestamp': int(__import__('time').time() * 1000)
                }
                f.write(json.dumps(log_entry) + '\n')
        except Exception:
            pass
        # #endregion
        
        # Generate target filename with _scan suffix
        daemon.logger.debug(f"Generating filename from metadata - Title: '{merged_metadata['title']}' (length: {len(merged_metadata['title'])})")
        filename_gen = FilenameGenerator()
        target_filename = filename_gen.generate(merged_metadata, is_scan=True) + '.pdf'
        
        # #region agent log
        try:
            with open(log_path, 'a', encoding='utf-8') as f:
                log_entry = {
                    'sessionId': 'debug-session',
                    'runId': 'run1',
                    'hypothesisId': 'B',
                    'location': 'handle_item_selected_pages.py:79',
                    'message': 'Filename generated',
                    'data': {
                        'target_filename': target_filename,
                        'input_metadata_title': merged_metadata.get('title', 'MISSING')
                    },
                    'timestamp': int(__import__('time').time() * 1000)
                }
                f.write(json.dumps(log_entry) + '\n')
        except Exception:
            pass
        # #endregion
        
        daemon.logger.debug(f"Generated filename: {target_filename}")
        
        # Store in context
        ctx['zotero_authors'] = zotero_authors
        ctx['zotero_title'] = zotero_title
        ctx['zotero_year'] = zotero_year
        ctx['zotero_item_type'] = zotero_item_type
        ctx['target_filename'] = target_filename
        # Store merged metadata for _process_selected_item (preserving original extracted metadata in ctx['metadata'])
        ctx['merged_metadata'] = merged_metadata
        
        # Check if titles differ - if so, show filename override page
        metadata = ctx.get('metadata', {})
        metadata_title = metadata.get('title', '').strip()
        if metadata_title and metadata_title != zotero_title:
            # Titles differ - navigate to filename override page
            return NavigationResult.show_page('filename_title_override')
        
        # Titles are the same - prompt for filename editing
        # Prepare metadata for filename editing
        zotero_metadata = {
            'title': zotero_title,
            'authors': zotero_authors,
            'year': zotero_year if zotero_year else 'Unknown',
            'document_type': zotero_item_type
        }
        
        # Prompt for filename editing
        final_filename = daemon._prompt_filename_edit(
            target_filename=target_filename,
            zotero_metadata=zotero_metadata,
            extracted_metadata=metadata
        )
        
        # Update context with final filename
        ctx['target_filename'] = final_filename
        
        # Show PDF comparison if item already has PDF
        has_pdf = ctx.get('has_pdf', False)
        if has_pdf:
            existing_pdf_info = daemon._get_existing_pdf_info(selected_item)
            daemon._display_pdf_comparison(pdf_path, scan_size_mb, existing_pdf_info)
        
        return NavigationResult.show_page('proposed_actions')
    
    def handler_e(ctx):
        """Edit tags - go to EDIT TAGS page."""
        item_key = ctx.get('item_key') or ctx['selected_item'].get('key')
        if not item_key:
            print("❌ No item key found - cannot edit tags")
            print("ℹ️  Please edit this item in Zotero, then process the scan again")
            print("📝 Moving to manual review")
            return NavigationResult.quit_scan(move_to_manual=True)
        
        return NavigationResult.show_page('edit_tags')
    
    def handler_z(ctx):
        """Go back to item selection."""
        print("⬅️  Going back to item selection")
        return NavigationResult.return_to_caller()
    
    def quit_action(ctx):
        """Quit - move to manual review."""
        print("📝 Moving to manual review")
        return NavigationResult.quit_scan(move_to_manual=True)
    
    return Page(
        page_id='review_and_proceed',
        title='REVIEW & PROCEED',
        content=content,
        prompt='\nProceed or edit? [y/e/z]: ',
        valid_inputs=['y', 'e', 'z'],
        handlers={
            'y': handler_y,
            'e': handler_e,
            'z': handler_z
        },
        default='y',
        back_page=None,  # Top level
        quit_action=quit_action
    )


def create_enrichment_review_auto_page(daemon) -> Page:
    """Auto-accept enrichment review page (timeout defaults to apply)."""
    from shared_tools.daemon.enrichment_display import display_enrichment_summary
    from shared_tools.ui.colors import Colors, ColorScheme

    def content(ctx):
        enrich = ctx.get('enrichment') or {}
        status = enrich.get('status')
        reason = enrich.get('reason')
        plan = enrich.get('plan') or {}
        manual_fields = plan.get('manual_fields') or []
        lines = [
            "Online enrichment was found and auto-accepted by match policy.",
            f"Status: {status or '(unknown)'}" + (f" | reason: {reason}" if reason else ""),
            "",
            "  (y/Enter) Apply enrichment and continue",
            ("  (m) Review optional/manual fields (authors/type/conflicts)" if manual_fields else None),
            "  (n) Skip enrichment and continue",
            "  (z) Back to review",
            f"  (timeout) Defaults to apply after {daemon.prompt_timeout}s",
        ]
        # Print diff summary (side-effect is acceptable here for clarity)
        zotero_metadata = enrich.get('zotero_metadata') or {}
        candidate = enrich.get('candidate') or {}
        display_enrichment_summary(zotero_metadata, candidate, plan, heading="ENRICHMENT REVIEW (AUTO-ACCEPT)")
        return [l for l in lines if l]

    def handler_y(ctx):
        enrich = ctx.get('enrichment') or {}
        item_key = ctx.get('item_key')
        plan = enrich.get('plan') or {}
        candidate = enrich.get('candidate') or {}
        # #region agent log
        try:
            import time as _time, json as _json, os as _os
            _zp = getattr(daemon, "zotero_processor", None)
            log_path = r"f:\prog\research-tools\.cursor\debug.log" if _os.name == "nt" else "/mnt/f/prog/research-tools/.cursor/debug.log"
            with open(log_path, "a", encoding="utf-8") as _f:
                _f.write(_json.dumps({
                    "sessionId": "debug-session",
                    "runId": "run-enrich2",
                    "hypothesisId": "A1",
                    "location": "handle_item_selected_pages.py:enrichment_review_auto:handler_y",
                    "message": "about to apply enrichment",
                    "data": {
                        "item_key": item_key,
                        "updates_keys": sorted(list((plan.get("updates") or {}).keys()))[:30],
                        "manual_fields": sorted(list((plan.get("manual_fields") or [])))[:30],
                        "candidate_source": candidate.get("source"),
                        "zotero_processor_type": str(type(_zp)),
                        "has_update_if_missing": hasattr(_zp, "update_item_field_if_missing"),
                        "has_update_field": hasattr(_zp, "update_item_field"),
                    },
                    "timestamp": int(_time.time() * 1000)
                }) + "\n")
        except Exception:
            pass
        # #endregion
        if item_key and plan:
            result = daemon.enrichment_workflow.apply_plan(
                daemon.zotero_processor,
                item_key,
                plan,
                candidate_metadata=candidate,
            )
            applied = result.get('applied', [])
            failed = result.get('failed', [])
            if applied:
                print(Colors.colorize(f"✅ Enrichment applied to Zotero ({item_key}): {', '.join(applied)}", ColorScheme.SUCCESS))
            if failed:
                print(Colors.colorize(f"⚠️  Enrichment failed for fields: {', '.join(failed)}", ColorScheme.ERROR))
        # Prevent stale reuse / re-apply if navigating again
        clear_enrichment_context(ctx)
        return NavigationResult.show_page('review_and_proceed')

    def handler_n(ctx):
        clear_enrichment_context(ctx)
        return NavigationResult.show_page('review_and_proceed')

    def handler_m(ctx):
        # Keep enrichment context; user wants to decide manual/overwrite fields.
        return NavigationResult.show_page('enrichment_review_manual')
    
    def handler_z(ctx):
        clear_enrichment_context(ctx)
        return NavigationResult.show_page('review_and_proceed')

    return Page(
        page_id='enrichment_review_auto',
        title='ENRICHMENT REVIEW',
        content=content,
        prompt='\nApply enrichment? [y/n/m/z]: ',
        valid_inputs=['y', 'n', 'm', 'z'],
        handlers={'y': handler_y, 'n': handler_n, 'm': handler_m, 'z': handler_z},
        default='y',
        timeout_seconds=daemon.prompt_timeout,
        back_page='review_and_proceed',
        quit_action=None,
    )


def create_enrichment_review_manual_page(daemon) -> Page:
    """Manual-review enrichment page (timeout defaults to reject/skip)."""
    from shared_tools.daemon.enrichment_display import display_enrichment_summary
    from shared_tools.ui.colors import Colors, ColorScheme

    def content(ctx):
        enrich = ctx.get('enrichment') or {}
        status = enrich.get('status')
        reason = enrich.get('reason')
        lines = [
            "Online enrichment was found but requires manual review.",
            f"Status: {status or '(unknown)'}" + (f" | reason: {reason}" if reason else ""),
            "",
            "  (a) Apply all suggested fields (fillable + overwrite manual/conflicts)",
            "  (s) Select which fields to apply",
            "  (w) Continue (done with enrichment)",
            "  (n/Enter) Skip enrichment",
            "  (z) Back to review",
            f"  (timeout) Defaults to skip after {daemon.prompt_timeout * 3}s",
        ]
        zotero_metadata = enrich.get('zotero_metadata') or {}
        candidate = enrich.get('candidate') or {}
        plan = enrich.get('plan') or {}
        display_enrichment_summary(zotero_metadata, candidate, plan, heading="ENRICHMENT REVIEW (MANUAL)")
        return lines

    def _apply(ctx, *, selected_fill: List[str], selected_overwrite: List[str]):
        enrich = ctx.get('enrichment') or {}
        item_key = ctx.get('item_key')
        plan = enrich.get('plan') or {}
        candidate = enrich.get('candidate') or {}
        if not item_key or not plan:
            return {"applied": [], "failed": []}

        updates = plan.get('updates') or {}
        subset_plan = {**plan, "updates": {k: updates[k] for k in selected_fill if k in updates}}
        overwrite_set = set(selected_overwrite)
        return daemon.enrichment_workflow.apply_plan(
            daemon.zotero_processor,
            item_key,
            subset_plan,
            overwrite_fields=overwrite_set,
            candidate_metadata=candidate,
        )

    def handler_a(ctx):
        enrich = ctx.get('enrichment') or {}
        plan = enrich.get('plan') or {}
        updates = plan.get('updates') or {}
        manual_fields = plan.get('manual_fields') or []
        result = _apply(ctx, selected_fill=list(updates.keys()), selected_overwrite=list(manual_fields))
        item_key = ctx.get('item_key')
        applied = result.get('applied', [])
        failed = result.get('failed', [])
        if item_key and applied:
            print(Colors.colorize(f"✅ Enrichment applied to Zotero ({item_key}): {', '.join(applied)}", ColorScheme.SUCCESS))
        if item_key and failed:
            print(Colors.colorize(f"⚠️  Enrichment failed for fields: {', '.join(failed)}", ColorScheme.ERROR))
        clear_enrichment_context(ctx)
        return NavigationResult.show_page('review_and_proceed')

    def handler_s(ctx):
        enrich = ctx.get('enrichment') or {}
        plan = enrich.get('plan') or {}
        updates = plan.get('updates') or {}
        manual_fields = plan.get('manual_fields') or []
        fields = list(updates.keys()) + list(manual_fields)
        if not fields:
            print("No selectable enrichment fields.")
            clear_enrichment_context(ctx)
            return NavigationResult.show_page('review_and_proceed')

        print("\nSelectable fields:")
        for i, f in enumerate(fields, start=1):
            kind = "fill" if f in updates else "manual"
            print(f"  [{i}] ({kind}) {f}")
        while True:
            sel = input("Select fields to apply (e.g., 1,3-4), 'a' for all, or Enter to cancel: ").strip()
            if not sel:
                print("Cancelled selection (no changes applied).")
                return NavigationResult.show_page('enrichment_review_manual')
            if sel.lower() in {"u", "up", "b", "back", "z"}:
                print("⬅️  Back to enrichment menu (no changes applied).")
                return NavigationResult.show_page('enrichment_review_manual')
            if sel.lower() in {"a", "all"}:
                idxs = list(range(1, len(fields) + 1))
            else:
                idxs = parse_index_selection(sel, len(fields))
            # #region agent log
            try:
                import os as _os, json as _json, time as _time
                log_path = r"f:\prog\research-tools\.cursor\debug.log" if _os.name == "nt" else "/mnt/f/prog/research-tools/.cursor/debug.log"
                with open(log_path, "a", encoding="utf-8") as _f:
                    _f.write(_json.dumps({
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "ENR_SEL1",
                        "location": "handle_item_selected_pages.py:enrichment_review_manual:handler_s",
                        "message": "Selection parsed",
                        "data": {"sel": sel[:40], "idxs_count": len(idxs) if idxs else 0, "max": len(fields)},
                        "timestamp": int(_time.time() * 1000),
                    }) + "\n")
            except Exception:
                pass
            # #endregion
            if idxs:
                break
            print("⚠️  Invalid selection. Use numbers like '1,3-4' or 'a' for all.")

        chosen = [fields[i - 1] for i in idxs]
        chosen_fill = [f for f in chosen if f in updates]
        chosen_manual = [f for f in chosen if f in manual_fields]
        result = _apply(ctx, selected_fill=chosen_fill, selected_overwrite=chosen_manual)

        item_key = ctx.get('item_key')
        applied = result.get('applied', [])
        failed = result.get('failed', [])
        if item_key and applied:
            print(Colors.colorize(f"✅ Enrichment applied to Zotero ({item_key}): {', '.join(applied)}", ColorScheme.SUCCESS))
        if item_key and failed:
            print(Colors.colorize(f"⚠️  Enrichment failed for fields: {', '.join(failed)}", ColorScheme.ERROR))
        # Keep user on this page so they can apply more fields.
        # Remove applied fields from the remaining plan so the menu shrinks.
        try:
            enrich = ctx.get('enrichment') or {}
            plan = enrich.get('plan') or {}
            updates = dict(plan.get('updates') or {})
            manual_fields = list(plan.get('manual_fields') or [])
            for f in applied:
                if f in updates:
                    updates.pop(f, None)
                if f in manual_fields:
                    manual_fields = [x for x in manual_fields if x != f]
            plan['updates'] = updates
            plan['manual_fields'] = manual_fields
            enrich['plan'] = plan
            ctx['enrichment'] = enrich
        except Exception:
            pass
        # #region agent log
        try:
            import os as _os, json as _json, time as _time
            log_path = r"f:\prog\research-tools\.cursor\debug.log" if _os.name == "nt" else "/mnt/f/prog/research-tools/.cursor/debug.log"
            with open(log_path, "a", encoding="utf-8") as _f:
                _f.write(_json.dumps({
                    "sessionId": "debug-session",
                    "runId": "run1",
                    "hypothesisId": "ENR_LOOP1",
                    "location": "handle_item_selected_pages.py:enrichment_review_manual:handler_s",
                    "message": "Applied subset; staying on manual page",
                    "data": {"applied": applied[:20], "failed": failed[:20]},
                    "timestamp": int(_time.time() * 1000),
                }) + "\n")
        except Exception:
            pass
        # #endregion
        return NavigationResult.show_page('enrichment_review_manual')

    def handler_c(ctx):
        # Done with enrichment; prevent stale reuse later.
        clear_enrichment_context(ctx)
        return NavigationResult.show_page('review_and_proceed')

    def handler_w(ctx):
        # Alias for continue
        return handler_c(ctx)

    def handler_n(ctx):
        clear_enrichment_context(ctx)
        return NavigationResult.show_page('review_and_proceed')
    
    def handler_z(ctx):
        clear_enrichment_context(ctx)
        return NavigationResult.show_page('review_and_proceed')

    return Page(
        page_id='enrichment_review_manual',
        title='ENRICHMENT REVIEW',
        content=content,
        prompt='\nApply enrichment? [a/s/w/n/z]: ',
        valid_inputs=['a', 's', 'w', 'n', 'z'],
        handlers={'a': handler_a, 's': handler_s, 'w': handler_w, 'n': handler_n, 'z': handler_z},
        default='n',
        timeout_seconds=daemon.prompt_timeout * 3,
        back_page='review_and_proceed',
        quit_action=None,
    )


def create_edit_tags_page(daemon) -> Page:
    """Create EDIT TAGS page.
    
    User can edit tags interactively, go back, or move to manual review.
    """
    def content(ctx):
        lines = [
            "You can edit tags for this Zotero item.",
            "  (t) Edit tags interactively",
            "  (z) Go back (don't edit)",
            "  (m) Move to manual review (edit in Zotero directly)"
        ]
        return lines
    
    def handler_t(ctx):
        """Edit tags interactively."""
        daemon = ctx['daemon']
        selected_item = ctx['selected_item']
        item_key = ctx.get('item_key') or selected_item.get('key')
        
        # Get current tags from the item
        current_tags_raw = selected_item.get('tags', [])
        # Convert to dict format for edit_tags_interactively if needed
        current_tags = [{'tag': tag} if isinstance(tag, str) else tag for tag in current_tags_raw]
        
        print("\n✏️  Editing tags...")
        updated_tags = daemon.edit_tags_interactively(current_tags=current_tags)
        
        # Extract tag names from both lists for comparison
        current_tag_names = [tag['tag'] if isinstance(tag, dict) else str(tag) for tag in current_tags]
        updated_tag_names = [tag['tag'] if isinstance(tag, dict) else str(tag) for tag in updated_tags]
        
        # Calculate what to add and remove
        add_tags = [tag for tag in updated_tag_names if tag not in current_tag_names]
        remove_tags = [tag for tag in current_tag_names if tag not in updated_tag_names]
        
        # #region agent log
        try:
            import time as _time, json as _json, os
            log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(_json.dumps({
                    'sessionId': 'debug-session',
                    'runId': 'run1',
                    'hypothesisId': 'T1',
                    'location': 'handle_item_selected_pages.py:handler_t',
                    'message': 'Tag edit delta computed',
                    'data': {
                        'item_key': item_key,
                        'current_count': len(current_tag_names),
                        'updated_count': len(updated_tag_names),
                        'add_count': len(add_tags),
                        'remove_count': len(remove_tags)
                    },
                    'timestamp': int(_time.time() * 1000)
                }) + '\n')
        except Exception:
            pass
        # #endregion

        if add_tags or remove_tags:
            print(f"\n💾 Saving tag changes to Zotero...")
            success = daemon.zotero_processor.update_item_tags(
                item_key,
                add_tags=add_tags if add_tags else None,
                remove_tags=remove_tags if remove_tags else None
            )
            if success:
                print("✅ Tags updated successfully!")
                # Update selected_item with new tags for display
                selected_item['tags'] = updated_tags
            else:
                print("⚠️  Failed to update tags in Zotero")
                retry = input("Continue anyway? [y/N]: ").strip().lower()
                if retry != 'y':
                    return NavigationResult.show_page('review_and_proceed')
        else:
            print("ℹ️  No tag changes to save")
        
        # After editing tags, go to PROCEED_AFTER_EDIT page
        return NavigationResult.show_page('proceed_after_edit')
    
    def handler_z(ctx):
        """Go back to REVIEW & PROCEED."""
        return NavigationResult.show_page('review_and_proceed')
    
    def handler_m(ctx):
        """Move to manual review."""
        print("ℹ️  Please edit this item in Zotero, then process the scan again")
        print("📝 Moving to manual review")
        return NavigationResult.quit_scan(move_to_manual=True)
    
    def quit_action(ctx):
        """Quit - move to manual review."""
        print("📝 Moving to manual review")
        return NavigationResult.quit_scan(move_to_manual=True)
    
    return Page(
        page_id='edit_tags',
        title='🏷️  EDIT TAGS',
        content=content,
        prompt='\nChoose edit option [t/z/m]: ',
        valid_inputs=['t', 'z', 'm'],
        handlers={
            't': handler_t,
            'z': handler_z,
            'm': handler_m
        },
        default=None,
        back_page='review_and_proceed',
        quit_action=quit_action
    )


def create_proceed_after_edit_page(daemon) -> Page:
    """Create PROCEED AFTER EDIT page.
    
    After editing tags, ask if user wants to proceed with PDF attachment.
    """
    def content(ctx):
        lines = [
            "Tag editing completed.",
            "  (y/Enter) Proceed with PDF attachment",
            "  (n) Go back to tag editing"
        ]
        return lines
    
    def handler_y(ctx):
        """Proceed - go to PROPOSED ACTIONS."""
        daemon = ctx['daemon']
        # Prepare metadata (same logic as REVIEW & PROCEED handler_y)
        pdf_path = ctx['pdf_path']
        selected_item = ctx['selected_item']
        
        # Get scan file info
        scan_size_mb = pdf_path.stat().st_size / 1024 / 1024
        ctx['scan_size_mb'] = scan_size_mb
        
        # Extract metadata from Zotero item
        zotero_authors = selected_item.get('authors', [])
        zotero_title = selected_item.get('title', '')
        zotero_year = selected_item.get('year', selected_item.get('date', ''))
        zotero_item_type = selected_item.get('itemType', 'journalArticle')
        
        daemon.logger.debug(f"Extracting metadata from Zotero item - Title: '{zotero_title}' (length: {len(zotero_title)}), Authors: {zotero_authors}, Year: {zotero_year}")
        
        # Validate critical fields - use extracted metadata from context if Zotero item is missing fields
        missing_fields = []
        if not zotero_title:
            missing_fields.append('title')
        if not zotero_authors:
            missing_fields.append('authors')
        
        # Preserve original extracted metadata before we modify anything
        original_extracted_metadata = ctx.get('metadata', {})
        
        # If critical fields missing, use extracted metadata from context (already extracted from PDF)
        if missing_fields:
            extracted_metadata = original_extracted_metadata
            
            # Check if we have useful extracted metadata
            has_extracted_metadata = extracted_metadata and (
                extracted_metadata.get('title') or 
                extracted_metadata.get('authors') or 
                extracted_metadata.get('year')
            )
            
            if has_extracted_metadata:
                # Use extracted metadata to fill in missing fields
                if 'title' in missing_fields and extracted_metadata.get('title'):
                    title_from_extracted = extracted_metadata.get('title', '').strip()
                    if title_from_extracted:
                        zotero_title = title_from_extracted
                        print(f"✓ Using extracted title: {zotero_title}")
                
                if 'authors' in missing_fields and extracted_metadata.get('authors'):
                    authors_from_extracted = extracted_metadata.get('authors', [])
                    if authors_from_extracted:
                        # Handle different author formats: list of strings or list of dicts
                        if isinstance(authors_from_extracted, list):
                            normalized_authors = []
                            for author in authors_from_extracted:
                                if isinstance(author, dict):
                                    # Dict with 'name' field (some API formats)
                                    name = author.get('name', '')
                                    if name:
                                        normalized_authors.append(str(name).strip())
                                    else:
                                        # Try firstName/lastName structure
                                        first = author.get('firstName', '')
                                        last = author.get('lastName', '')
                                        if first and last:
                                            normalized_authors.append(f"{first} {last}".strip())
                                        elif last:
                                            normalized_authors.append(last.strip())
                                elif isinstance(author, str) and author.strip():
                                    normalized_authors.append(author.strip())
                            
                            if normalized_authors:
                                zotero_authors = normalized_authors
                                author_display = ', '.join(normalized_authors[:3])
                                if len(normalized_authors) > 3:
                                    author_display += '...'
                                print(f"✓ Using extracted authors: {author_display}")
                            elif isinstance(authors_from_extracted, str) and authors_from_extracted.strip():
                                zotero_authors = [authors_from_extracted.strip()]
                                print(f"✓ Using extracted author: {authors_from_extracted.strip()}")
                        elif isinstance(authors_from_extracted, str) and authors_from_extracted.strip():
                            zotero_authors = [authors_from_extracted.strip()]
                            print(f"✓ Using extracted author: {authors_from_extracted.strip()}")
                
                if not zotero_year and extracted_metadata.get('year'):
                    year_from_extracted = extracted_metadata.get('year')
                    if year_from_extracted:
                        zotero_year = str(year_from_extracted).strip()
                        print(f"✓ Using extracted year: {zotero_year}")
            else:
                # No useful extracted metadata available - metadata extraction may have failed
                print("⚠️  No extracted metadata available from PDF.")
                print("   Metadata extraction may have failed or PDF may not contain metadata.")
            
            # Re-check if we still have missing fields
            missing_fields = []
            if not zotero_title:
                missing_fields.append('title')
            if not zotero_authors:
                missing_fields.append('authors')
            
            # If still missing after using extracted metadata, use same validation as review_and_proceed
            if missing_fields:
                print(f"⚠️  WARNING: Missing: {', '.join(missing_fields)}")
                print("   Cannot generate proper filename without this information.")
                confirm_anyway = input("Proceed anyway with placeholder values? [y/n]: ").strip().lower()
                if confirm_anyway != 'y':
                    print("⬅️  Going back to tag editing...")
                    return NavigationResult.show_page('edit_tags')
                # Set placeholders
                if 'title' in missing_fields:
                    zotero_title = 'Unknown_Title'
                if 'authors' in missing_fields:
                    zotero_authors = ['Unknown_Author']
        
        # Check for filename title override (set in filename_title_override page or edit_metadata)
        filename_title_override = ctx.get('filename_title_override')
        if not filename_title_override:
            # Also check metadata for override (from edit_metadata_interactively)
            original_extracted_metadata = ctx.get('metadata', {})
            filename_title_override = original_extracted_metadata.get('_filename_title_override')
        
        # Use override title if present, otherwise use Zotero title
        title_for_filename = filename_title_override if filename_title_override else zotero_title
        
        # Build metadata using title for filename (override or Zotero title)
        merged_metadata = {
            'title': title_for_filename,
            'authors': zotero_authors,
            'year': zotero_year if zotero_year else 'Unknown',
            'document_type': zotero_item_type
        }
        
        # Generate target filename with _scan suffix
        filename_gen = FilenameGenerator()
        target_filename = filename_gen.generate(merged_metadata, is_scan=True) + '.pdf'
        
        # Store in context (including full metadata dict for _process_selected_item)
        ctx['zotero_authors'] = zotero_authors
        ctx['zotero_title'] = zotero_title
        ctx['zotero_year'] = zotero_year
        ctx['zotero_item_type'] = zotero_item_type
        ctx['target_filename'] = target_filename
        # Store merged metadata separately, preserving original extracted metadata
        ctx['merged_metadata'] = merged_metadata  # Final metadata for _process_selected_item
        # Keep original extracted metadata in ctx['metadata'] for reference (don't overwrite)
        if 'metadata' not in ctx or not ctx.get('metadata'):
            # Only set if not already present (should already be set from ItemSelectedContext)
            ctx['metadata'] = original_extracted_metadata
        
        # Prompt for filename editing
        # Prepare metadata for filename editing
        zotero_metadata = {
            'title': zotero_title,
            'authors': zotero_authors,
            'year': zotero_year if zotero_year else 'Unknown',
            'document_type': zotero_item_type
        }
        
        # Prompt for filename editing
        final_filename = daemon._prompt_filename_edit(
            target_filename=target_filename,
            zotero_metadata=zotero_metadata,
            extracted_metadata=original_extracted_metadata
        )
        
        # Update context with final filename
        ctx['target_filename'] = final_filename
        
        # Show PDF comparison if item already has PDF
        has_pdf = ctx.get('has_pdf', False)
        if has_pdf:
            existing_pdf_info = daemon._get_existing_pdf_info(selected_item)
            daemon._display_pdf_comparison(pdf_path, scan_size_mb, existing_pdf_info)
        
        return NavigationResult.show_page('proposed_actions')
    
    def handler_n(ctx):
        """Go back to EDIT TAGS."""
        print("⬅️  Going back to tag editing...")
        return NavigationResult.show_page('edit_tags')
    
    def quit_action(ctx):
        """Quit - move to manual review."""
        print("📝 Moving to manual review")
        return NavigationResult.quit_scan(move_to_manual=True)
    
    return Page(
        page_id='proceed_after_edit',
        title='PROCEED WITH PDF ATTACHMENT',
        content=content,
        prompt='\nProceed with PDF attachment? [Y/n]: ',
        valid_inputs=['y', 'n'],
        handlers={
            'y': handler_y,
            'n': handler_n
        },
        default='y',
        back_page='edit_tags',  # Go back to tag editing if user presses 'z'
        quit_action=quit_action
    )


def create_filename_title_override_page(daemon) -> Page:
    """Create FILENAME TITLE OVERRIDE page.
    
    Allows user to choose which title to use for the PDF filename when
    Zotero item title and extracted metadata title differ.
    """
    def content(ctx):
        selected_item = ctx['selected_item']
        metadata = ctx.get('metadata', {})
        
        zotero_title = selected_item.get('title', '').strip()
        metadata_title = metadata.get('title', '').strip()
        
        lines = [
            "📄 FILENAME TITLE",
            "",
            f"Zotero item title: {zotero_title}",
        ]
        
        if metadata_title and metadata_title != zotero_title:
            lines.append(f"Metadata title:     {metadata_title}")
            lines.append("")
            lines.append("The PDF filename can use either title, or a custom title.")
        else:
            lines.append("")
            lines.append("You can use the Zotero title or enter a custom title for the filename.")
        
        # Show filename previews
        filename_gen = FilenameGenerator()
        zotero_authors = selected_item.get('authors', [])
        zotero_year = selected_item.get('year', selected_item.get('date', ''))
        zotero_item_type = selected_item.get('itemType', 'journalArticle')
        
        # Preview with Zotero title
        metadata_zotero = {
            'title': zotero_title,
            'authors': zotero_authors,
            'year': zotero_year if zotero_year else 'Unknown',
            'document_type': zotero_item_type
        }
        filename_zotero = filename_gen.generate(metadata_zotero, is_scan=True) + '.pdf'
        lines.append(f"  With Zotero title:  {filename_zotero}")
        
        if metadata_title and metadata_title != zotero_title:
            # Preview with metadata title
            metadata_meta = {
                'title': metadata_title,
                'authors': zotero_authors,
                'year': zotero_year if zotero_year else 'Unknown',
                'document_type': zotero_item_type
            }
            filename_meta = filename_gen.generate(metadata_meta, is_scan=True) + '.pdf'
            lines.append(f"  With metadata title: {filename_meta}")
        
        lines.extend([
            "",
            "  (Enter) Use Zotero title (default)",
        ])
        
        if metadata_title and metadata_title != zotero_title:
            lines.append("  (m) Use metadata title")
        
        lines.extend([
            "  (c) Enter custom title",
            "  (z) Go back",
            "  (q) Quit - move to manual review"
        ])
        
        return lines
    
    def handler_default(ctx):
        """Use Zotero title (default) - proceed to proposed actions."""
        # Don't set override - will use Zotero title by default
        return NavigationResult.show_page('proposed_actions')
    
    def handler_m(ctx):
        """Use metadata title for filename."""
        daemon = ctx['daemon']
        selected_item = ctx['selected_item']
        metadata = ctx.get('metadata', {})
        
        metadata_title = metadata.get('title', '').strip()
        zotero_title = selected_item.get('title', '').strip()
        
        # Check if metadata title is available and differs from Zotero title
        if not metadata_title:
            print("⚠️  No metadata title available. Using Zotero title instead.")
            return NavigationResult.show_page('proposed_actions')
        
        if metadata_title == zotero_title:
            print("ℹ️  Metadata title is the same as Zotero title. Using Zotero title.")
            return NavigationResult.show_page('proposed_actions')
        
        # Store override in context
        ctx['filename_title_override'] = metadata_title
        
        # Regenerate filename with metadata title
        zotero_authors = selected_item.get('authors', [])
        zotero_year = selected_item.get('year', selected_item.get('date', ''))
        zotero_item_type = selected_item.get('itemType', 'journalArticle')
        
        filename_gen = FilenameGenerator()
        merged_metadata = {
            'title': metadata_title,
            'authors': zotero_authors,
            'year': zotero_year if zotero_year else 'Unknown',
            'document_type': zotero_item_type
        }
        target_filename = filename_gen.generate(merged_metadata, is_scan=True) + '.pdf'
        ctx['target_filename'] = target_filename
        ctx['merged_metadata'] = merged_metadata
        
        print(f"✅ Will use metadata title for filename: {metadata_title}")
        return NavigationResult.show_page('proposed_actions')
    
    def handler_c(ctx):
        """Enter custom title for filename."""
        daemon = ctx['daemon']
        selected_item = ctx['selected_item']
        
        print("\n📝 Enter custom title for PDF filename:")
        custom_title = input("Custom title: ").strip()
        
        if not custom_title:
            print("⚠️  Custom title cannot be empty. Using Zotero title instead.")
            return NavigationResult.show_page('proposed_actions')
        
        # Store override in context
        ctx['filename_title_override'] = custom_title
        
        # Regenerate filename with custom title
        zotero_authors = selected_item.get('authors', [])
        zotero_year = selected_item.get('year', selected_item.get('date', ''))
        zotero_item_type = selected_item.get('itemType', 'journalArticle')
        
        filename_gen = FilenameGenerator()
        merged_metadata = {
            'title': custom_title,
            'authors': zotero_authors,
            'year': zotero_year if zotero_year else 'Unknown',
            'document_type': zotero_item_type
        }
        target_filename = filename_gen.generate(merged_metadata, is_scan=True) + '.pdf'
        ctx['target_filename'] = target_filename
        ctx['merged_metadata'] = merged_metadata
        
        print(f"✅ Will use custom title for filename: {custom_title}")
        return NavigationResult.show_page('proposed_actions')
    
    def quit_action(ctx):
        """Quit - move to manual review."""
        print("📝 Moving to manual review")
        return NavigationResult.quit_scan(move_to_manual=True)
    
    # Create page with consistent navigation: 'z' always means "back", Enter means "use default"
    # Include all possible inputs; 'm' handler will check if metadata title differs
    return Page(
        page_id='filename_title_override',
        title='📄 FILENAME TITLE',
        content=content,
        prompt='\nChoose filename title [Enter/m/c/z/q]: ',
        valid_inputs=['', 'm', 'c', 'z', 'q'],  # '' = Enter key, 'z' = back (standard command)
        handlers={
            '': handler_default,  # Empty string = Enter key = default = Use Zotero title
            'm': handler_m,  # Use metadata title (handler checks if available)
            'c': handler_c   # Custom title
        },
        default='',  # Default is Enter key (empty string) = Use Zotero title
        back_page='review_and_proceed',  # 'z' will use this via standard back command
        quit_action=quit_action
    )


def create_proposed_actions_page(daemon) -> Page:
    """Create PROPOSED ACTIONS page.
    
    Shows what will be done and asks for final confirmation.
    """
    def content(ctx):
        daemon = ctx['daemon']
        pdf_path = ctx['pdf_path']
        scan_size_mb = ctx.get('scan_size_mb', 0)
        target_filename = ctx.get('target_filename', 'unknown.pdf')
        publications_dir = daemon.publications_dir.name
        
        # If the target PDF already exists in publications/, we want to avoid
        # expensive preprocessing and let the user decide whether to skip/replace.
        conflict_exists = False
        try:
            conflict_target_path = daemon.publications_dir / target_filename
            conflict_exists = daemon._pub_exists(conflict_target_path)
        except Exception:
            conflict_exists = False
        
        lines = [
            f"Scan: {pdf_path.name} ({scan_size_mb:.1f} MB)",
            "",
            "Will perform:",
            *(["⚠️ Existing target PDF detected. Next you can choose keep/replace/keep-both."]
              if conflict_exists else []),
            f"  1. Split landscape/two-up pages using 50/50 geometric (fast default)",
            f"  2. Gutter detection + border removal (only if you reject 50/50 in preview)",
            f"  3. Trim leading pages (optional)",
            f"  4. Generate filename: {target_filename}",
            f"  5. Copy to publications: {publications_dir}/",
            f"  6. Attach as linked file in Zotero",
            f"  7. Move scan to: done/",
            "",
            "  (y/Enter) Proceed with all actions",
            "  (z) Go back to review",
            "  (q) Quit - move to manual review"
        ]
        return lines
    
    def handler_y(ctx):
        """Proceed - do PDF preprocessing and go to PDF PREVIEW."""
        daemon = ctx['daemon']
        pdf_path = ctx['pdf_path']
        target_filename = ctx.get('target_filename')

        # Early routing: if the target publications PDF already exists, ask how
        # to handle it *before* preprocessing (preprocessing causes split/prep
        # work and can lead to collisions later).
        if target_filename:
            try:
                conflict_target_path = daemon.publications_dir / target_filename
                if daemon._pub_exists(conflict_target_path):
                    print("\n⚠️  Existing publications PDF detected before preprocessing.")
                    print("    Routing to conflict decision...")
                    return NavigationResult.show_page('pdf_conflict_decision')
            except Exception:
                # If existence check fails, fall back to original preprocessing flow.
                pass
        
        # Step 1: Preprocess PDF with default options
        print("\n" + "="*70)
        print("PDF PREPROCESSING")
        print("="*70)
        processed_pdf, preprocessing_state = daemon._preprocess_pdf_with_options(
            pdf_path,
            # Fast path: avoid gutter detection + border removal for speed.
            # If the 50/50 preview looks wrong, the user can rerun the slower logic from the preview menu.
            border_removal=False,
            split_method='50-50',
            trim_leading=True
        )
        
        # #region agent log
        try:
            import json, os, time
            log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps({
                    'sessionId': 'debug-session',
                    'runId': 'run1',
                    'hypothesisId': 'H4',
                    'location': 'handle_item_selected_pages.py:handler_y',
                    'message': 'After _preprocess_pdf_with_options',
                    'data': {
                        'processed_pdf': str(processed_pdf) if processed_pdf else None,
                        'processed_pdf_is_original': str(processed_pdf) == str(pdf_path) if processed_pdf else False,
                        'original_pdf': str(pdf_path),
                        'split_succeeded': preprocessing_state.get('split_succeeded', False),
                        'split_attempted': preprocessing_state.get('split_attempted', False),
                        'split_method': preprocessing_state.get('split_method', 'none')
                    },
                    'timestamp': int(time.time() * 1000)
                }) + '\n')
        except: pass
        # #endregion
        
        # Store processed PDF and state in context for preview page
        ctx['processed_pdf'] = processed_pdf
        ctx['original_pdf'] = pdf_path
        ctx['preprocessing_state'] = preprocessing_state
        
        # Navigate to PDF preview page
        return NavigationResult.show_page('pdf_preview')
    
    def handler_z(ctx):
        """Go back to REVIEW & PROCEED."""
        print("⬅️  Going back to review...")
        return NavigationResult.show_page('review_and_proceed')
    
    def quit_action(ctx):
        """Quit - move to manual review."""
        print("📝 Moving to manual review")
        return NavigationResult.quit_scan(move_to_manual=True)
    
    return Page(
        page_id='proposed_actions',
        title='PROPOSED ACTIONS:',
        content=content,
        prompt='\nProceed with these actions? [Y/z/q]: ',
        valid_inputs=['y', 'z', 'q'],
        handlers={
            'y': handler_y,
            'z': handler_z
        },
        default='y',
        back_page='review_and_proceed',
        quit_action=quit_action
    )


def create_pdf_conflict_decision_page(daemon) -> Page:
    """Create PDF CONFLICT decision page.
    
    This is shown when the target filename already exists in publications/.
    It lets the user keep existing (skip preprocessing), or proceed with
    replace/keep-both (preprocessing still happens only if needed).
    """
    def _compute_keep_both_filename(ctx) -> str:
        from pathlib import Path
        target_filename = ctx.get('target_filename')
        if not target_filename:
            return target_filename
        
        stem = Path(target_filename).stem
        suffix = Path(target_filename).suffix or ".pdf"
        
        # Keep-both naming convention used elsewhere in this codebase.
        candidates = [
            f"{stem}_scanned2{suffix}",
            f"{stem}_scanned{suffix}",
            f"{stem}_scanned3{suffix}",
        ]
        for cand in candidates:
            try:
                if not daemon._pub_exists(daemon.publications_dir / cand):
                    return cand
            except Exception:
                # If existence check fails, just return the first candidate.
                return candidates[0]
        return candidates[0]

    def _preprocess_then_show_preview(ctx):
        pdf_path = ctx['pdf_path']
        processed_pdf, preprocessing_state = daemon._preprocess_pdf_with_options(
            pdf_path,
            border_removal=False,
            split_method='50-50',
            trim_leading=True
        )

        ctx['processed_pdf'] = processed_pdf
        ctx['original_pdf'] = pdf_path
        ctx['preprocessing_state'] = preprocessing_state
        return NavigationResult.show_page('pdf_preview')

    def content(ctx):
        pdf_path = ctx['pdf_path']
        target_filename = ctx.get('target_filename', 'unknown.pdf')
        lines = [
            "⚠️ Existing publications PDF detected",
            "",
            f"Existing target filename: {target_filename}",
            f"Scan filename:            {pdf_path.name}",
            "",
            "Choose what to do:",
            "  [1] Keep existing PDF (skip preprocessing; move scan to done/)",
            "  [2] Replace existing with scan (preprocess + replace later)",
            "  [3] Keep both (preprocess + attach scan under scanned suffix)",
            "  (z) Go back",
            "  (q) Quit - move to manual review",
        ]
        return lines

    def handler_1(ctx):
        daemon.move_to_done(ctx['pdf_path'])
        print("✅ Kept existing PDF; skipped preprocessing.")
        return NavigationResult.return_to_caller()

    def handler_2(ctx):
        # Store choice for later conflict handling in _process_selected_item.
        ctx['conflict_action'] = 'replace'
        return _preprocess_then_show_preview(ctx)

    def handler_3(ctx):
        ctx['conflict_action'] = 'keep_both'
        ctx['target_filename'] = _compute_keep_both_filename(ctx)
        return _preprocess_then_show_preview(ctx)

    def handler_z(ctx):
        print("⬅️  Going back to proposed actions...")
        return NavigationResult.show_page('proposed_actions')

    def quit_action(ctx):
        print("📝 Moving to manual review")
        return NavigationResult.quit_scan(move_to_manual=True)

    return Page(
        page_id='pdf_conflict_decision',
        title='PDF CONFLICT',
        content=content,
        prompt='\nEnter your choice (timeout defaults to 1): ',
        valid_inputs=['1', '2', '3', 'z', 'q'],
        handlers={
            '1': handler_1,
            '2': handler_2,
            '3': handler_3,
            'z': handler_z
        },
        default='1',
        back_page='proposed_actions',
        quit_action=quit_action
    )


def create_note_prompt_page(daemon) -> Page:
    """Create NOTE PROMPT page.
    
    Asks if user wants to add a handwritten note.
    """
    def content(ctx):
        lines = [
            "You can add a sentence or two from your notes on the paper folder.",
            "  (Enter) Skip - don't add a note",
            "  (y) Add a note",
            "  (z) Cancel and go back"
        ]
        return lines
    
    def handler_enter(ctx):
        """Skip note - process PDF."""
        print("ℹ️  Skipping note...")
        return NavigationResult.process_pdf()
    
    def handler_y(ctx):
        """Add note - go to NOTE INPUT page."""
        return NavigationResult.show_page('note_input')
    
    def handler_z(ctx):
        """Cancel - go back to PDF PREVIEW."""
        print("⬅️  Cancelling note addition")
        return NavigationResult.show_page('pdf_preview')
    
    def quit_action(ctx):
        """Quit - move to manual review."""
        print("📝 Moving to manual review")
        return NavigationResult.quit_scan(move_to_manual=True)
    
    return Page(
        page_id='note_prompt',
        title='WRITE A NOTE',
        content=content,
        prompt='\nAdd a note? [Enter/y/z]: ',
        valid_inputs=['', 'y', 'z'],
        handlers={
            '': handler_enter,  # Enter key
            'y': handler_y,
            'z': handler_z
        },
        default='',  # Enter is default
        back_page='pdf_preview',
        quit_action=quit_action
    )


def create_pdf_preview_page(daemon) -> Page:
    """Create PDF PREVIEW page.
    
    Shows processed PDF preview and allows user to modify preprocessing options.
    """
    def content(ctx):
        daemon = ctx['daemon']
        processed_pdf = ctx.get('processed_pdf')
        preprocessing_state = ctx.get('preprocessing_state', {})
        
        if not processed_pdf:
            return ["❌ Error: No processed PDF found in context"]
        
        # #region agent log
        try:
            import json, os, time
            log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps({
                    'sessionId': 'debug-session',
                    'runId': 'run1',
                    'hypothesisId': 'H4,H5',
                    'location': 'handle_item_selected_pages.py:create_pdf_preview_page',
                    'message': 'PDF preview - before opening in viewer',
                    'data': {
                        'processed_pdf': str(processed_pdf) if processed_pdf else None,
                        'processed_pdf_exists': processed_pdf.exists() if processed_pdf else False,
                        'original_pdf': str(ctx.get('original_pdf', 'N/A')),
                        'split_succeeded': preprocessing_state.get('split_succeeded', False),
                        'split_attempted': preprocessing_state.get('split_attempted', False),
                        'split_method': preprocessing_state.get('split_method', 'none')
                    },
                    'timestamp': int(time.time() * 1000)
                }) + '\n')
        except: pass
        # #endregion
        
        # Open PDF in viewer
        daemon._open_pdf_in_viewer(processed_pdf)
        
        # Build status lines
        border_status = "✓ Applied" if preprocessing_state.get('border_removal', False) else "✗ Not applied"
        split_method = preprocessing_state.get('split_method', 'none')
        split_attempted = preprocessing_state.get('split_attempted', False)
        split_succeeded = preprocessing_state.get('split_succeeded', False)
        
        # Determine split status - must check split_succeeded, not just split_attempted
        if split_method == 'manual' and split_attempted and split_succeeded:
            manual_ratio = preprocessing_state.get('manual_split_ratio')
            if manual_ratio:
                split_status = f"✓ Applied (manual {manual_ratio:.0f}/{100-manual_ratio:.0f})"
            else:
                split_status = "✓ Applied (manual)"
        elif split_method == 'auto' and split_attempted and split_succeeded:
            split_status = "✓ Applied (gutter detection)"
        elif split_method == '50-50' and split_attempted and split_succeeded:
            split_status = "✓ Applied (50/50 geometric)"
        elif split_method != 'none' and split_attempted:
            split_status = f"✗ Attempted ({split_method}) but failed/cancelled"
        elif split_attempted:
            split_status = "✗ Attempted but cancelled"
        else:
            split_status = "✗ Not applied"
        
        trim_status = "✓ Applied" if preprocessing_state.get('trim_leading', False) else "✗ Not applied"
        
        lines = [
            "",
            "Opening processed PDF in viewer...",
            "",
            "Current preprocessing:",
            f"  - Border removal: {border_status}",
            f"  - Split: {split_status}",
            f"  - Trimming: {trim_status}",
            "",
            "Options:",
            "  [1] Accept and proceed to Zotero"
        ]
        
        # Build dynamic options based on current state
        option_num = 1
        
        # Fast-path split (geometric 50/50) is the default.
        # If the preview looks wrong, rerun with gutter detection + border removal.
        if preprocessing_state.get('split_method', 'none') == '50-50':
            option_num += 1
            lines.append(f"  [{option_num}] Improve split (gutter detection + border removal)")
        
        if preprocessing_state.get('border_removal', False):
            option_num += 1
            lines.append(f"  [{option_num}] Drop border removal")
        
        if preprocessing_state.get('split_method', 'none') != 'none':
            option_num += 1
            lines.append(f"  [{option_num}] Drop split")
        
        if preprocessing_state.get('split_method', 'none') == 'auto':
            option_num += 1
            lines.append(f"  [{option_num}] Use 50/50 split instead")
        
        # Show "Add trimming" if not applied, "Drop trimming" if applied
        if preprocessing_state.get('trim_leading', False):
            option_num += 1
            lines.append(f"  [{option_num}] Drop trimming")
        else:
            option_num += 1
            lines.append(f"  [{option_num}] Add trimming")
        
        # Manual split option - always available
        option_num += 1
        manual_split_option_num = option_num
        manual_split_ratio = preprocessing_state.get('manual_split_ratio')
        if manual_split_ratio:
            lines.append(f"  [{option_num}] Split by manual definition ({manual_split_ratio:.0f}/{100-manual_split_ratio:.0f})")
        else:
            lines.append(f"  [{option_num}] Split by manual definition (e.g., 55/45)")
        
        lines.append("  [z] Go back to proposed actions")
        lines.append("  [q] Quit - move to manual review")
        
        return lines
    
    def handler_1(ctx):
        """Accept and proceed."""
        item_key = ctx.get('item_key') or ctx.get('selected_item', {}).get('key')
        # Store final processed PDF and preprocessing_state in context for use in final processing
        ctx['final_processed_pdf'] = ctx.get('processed_pdf')
        ctx['preprocessing_state'] = ctx.get('preprocessing_state', {})  # Ensure it's available
        if item_key:
            return NavigationResult.show_page('note_prompt')
        else:
            return NavigationResult.process_pdf()
    
    def make_handler(option_num):
        """Create a handler for a specific option number."""
        def handler(ctx):
            preprocessing_state = ctx.get('preprocessing_state', {})
            action = _get_pdf_preview_option_action(option_num, preprocessing_state)
            
            if action == 'accept':
                return handler_1(ctx)
            elif action == 'improve_split':
                return _handle_improve_split_gutter_and_borders(ctx, daemon)
            elif action == 'drop_border':
                return _handle_drop_border_removal(ctx, daemon)
            elif action == 'drop_split':
                return _handle_drop_split(ctx, daemon)
            elif action == 'use_5050':
                return _handle_use_5050_split(ctx, daemon)
            elif action == 'drop_trim':
                return _handle_drop_trimming(ctx, daemon)
            elif action == 'add_trim':
                return _handle_add_trimming(ctx, daemon)
            elif action == 'manual_split':
                return _handle_manual_split(ctx, daemon)
            else:
                print("⚠️  Invalid choice.")
                return NavigationResult.show_page('pdf_preview')
        return handler
    
    handler_2 = make_handler(2)
    handler_3 = make_handler(3)
    handler_4 = make_handler(4)
    handler_5 = make_handler(5)
    handler_6 = make_handler(6)
    
    def handler_z(ctx):
        """Go back to PROPOSED ACTIONS."""
        print("⬅️  Going back to proposed actions...")
        return NavigationResult.show_page('proposed_actions')
    
    def quit_action(ctx):
        """Quit - move to manual review."""
        pdf_path = ctx['pdf_path']
        print("📝 Moving to manual review")
        return NavigationResult.quit_scan(move_to_manual=True)
    
    return Page(
        page_id='pdf_preview',
        title='PDF PREVIEW',
        content=content,
        prompt='\nEnter your choice: ',
        valid_inputs=['1', '2', '3', '4', '5', '6', 'z', 'q'],
        handlers={
            '1': handler_1,
            '2': handler_2,
            '3': handler_3,
            '4': handler_4,
            '5': handler_5,
            '6': handler_6,
            'z': handler_z
        },
        default='1',
        back_page='pdf_preview',
        quit_action=quit_action,
        timeout_seconds=daemon.prompt_timeout * 2  # 2x timeout for PDF inspection
    )


def _get_pdf_preview_option_action(option_num: int, preprocessing_state: dict) -> str:
    """Determine what action corresponds to an option number based on current state.
    
    Returns: 'accept', 'drop_border', 'drop_split', 'use_5050', 'drop_trim', 'add_trim', 'manual_split', or None
    """
    if option_num == 1:
        return 'accept'
    
    option_count = 1  # Option 1 is always "Accept"
    
    if preprocessing_state.get('split_method', 'none') == '50-50':
        option_count += 1
        if option_count == option_num:
            return 'improve_split'
    
    if preprocessing_state.get('border_removal', False):
        option_count += 1
        if option_count == option_num:
            return 'drop_border'
    
    if preprocessing_state.get('split_method', 'none') != 'none':
        option_count += 1
        if option_count == option_num:
            return 'drop_split'
    
    if preprocessing_state.get('split_method', 'none') == 'auto':
        option_count += 1
        if option_count == option_num:
            return 'use_5050'
    
    # Handle trimming: "Drop trimming" if applied, "Add trimming" if not applied
    option_count += 1
    if option_count == option_num:
        if preprocessing_state.get('trim_leading', False):
            return 'drop_trim'
        else:
            return 'add_trim'
    
    # Manual split option - always available
    option_count += 1
    if option_count == option_num:
        return 'manual_split'
    
    return None


def _handle_drop_border_removal(ctx, daemon):
    """Handler for dropping border removal - reprocess PDF."""
    original_pdf = ctx['pdf_path']
    preprocessing_state = ctx.get('preprocessing_state', {}).copy()
    preprocessing_state['border_removal'] = False
    print("\n🔄 Restarting preprocessing without border removal...")
    
    processed_pdf, new_state = daemon._preprocess_pdf_with_options(
        original_pdf,
        border_removal=False,
        split_method=preprocessing_state.get('split_method', 'auto'),
        trim_leading=preprocessing_state.get('trim_leading', True)
    )
    
    ctx['processed_pdf'] = processed_pdf
    ctx['preprocessing_state'] = new_state
    # Stay on preview page to show updated result
    return NavigationResult.show_page('pdf_preview')


def _handle_drop_split(ctx, daemon):
    """Handler for dropping split - reprocess PDF."""
    original_pdf = ctx['pdf_path']
    preprocessing_state = ctx.get('preprocessing_state', {}).copy()
    preprocessing_state['split_method'] = 'none'
    print("\n🔄 Restarting preprocessing without split...")
    
    processed_pdf, new_state = daemon._preprocess_pdf_with_options(
        original_pdf,
        border_removal=preprocessing_state.get('border_removal', True),
        split_method='none',
        trim_leading=preprocessing_state.get('trim_leading', True)
    )
    
    ctx['processed_pdf'] = processed_pdf
    ctx['preprocessing_state'] = new_state
    return NavigationResult.show_page('pdf_preview')


def _handle_use_5050_split(ctx, daemon):
    """Handler for using 50/50 split instead - reprocess PDF."""
    original_pdf = ctx['pdf_path']
    preprocessing_state = ctx.get('preprocessing_state', {}).copy()
    print("\n🔄 Restarting preprocessing with 50/50 split...")
    
    processed_pdf, new_state = daemon._preprocess_pdf_with_options(
        original_pdf,
        border_removal=preprocessing_state.get('border_removal', True),
        split_method='50-50',
        trim_leading=preprocessing_state.get('trim_leading', True)
    )
    
    ctx['processed_pdf'] = processed_pdf
    ctx['preprocessing_state'] = new_state
    return NavigationResult.show_page('pdf_preview')


def _handle_improve_split_gutter_and_borders(ctx, daemon):
    """Handler for rerunning split using gutter detection + border removal."""
    original_pdf = ctx['pdf_path']
    preprocessing_state = ctx.get('preprocessing_state', {}).copy()
    print("\n🔄 Improving split (gutter detection + border removal)...")
    
    processed_pdf, new_state = daemon._preprocess_pdf_with_options(
        original_pdf,
        border_removal=True,
        split_method='auto',
        trim_leading=preprocessing_state.get('trim_leading', True)
    )
    
    ctx['processed_pdf'] = processed_pdf
    ctx['preprocessing_state'] = new_state
    return NavigationResult.show_page('pdf_preview')


def _handle_drop_trimming(ctx, daemon):
    """Handler for dropping trimming - reprocess PDF."""
    original_pdf = ctx['pdf_path']
    preprocessing_state = ctx.get('preprocessing_state', {}).copy()
    print("\n🔄 Restarting preprocessing without trimming...")
    
    processed_pdf, new_state = daemon._preprocess_pdf_with_options(
        original_pdf,
        border_removal=preprocessing_state.get('border_removal', True),
        split_method=preprocessing_state.get('split_method', 'auto'),
        trim_leading=False
    )
    
    ctx['processed_pdf'] = processed_pdf
    ctx['preprocessing_state'] = new_state
    return NavigationResult.show_page('pdf_preview')


def _handle_add_trimming(ctx, daemon):
    """Handler for adding trimming - reprocess PDF."""
    original_pdf = ctx['pdf_path']
    preprocessing_state = ctx.get('preprocessing_state', {}).copy()
    print("\n🔄 Restarting preprocessing with trimming...")
    
    processed_pdf, new_state = daemon._preprocess_pdf_with_options(
        original_pdf,
        border_removal=preprocessing_state.get('border_removal', True),
        split_method=preprocessing_state.get('split_method', 'auto'),
        trim_leading=True
    )
    
    ctx['processed_pdf'] = processed_pdf
    ctx['preprocessing_state'] = new_state
    return NavigationResult.show_page('pdf_preview')


def _handle_manual_split(ctx, daemon):
    """Handler for manual split definition - prompt for ratio and perform split."""
    original_pdf = ctx['pdf_path']
    preprocessing_state = ctx.get('preprocessing_state', {}).copy()
    border_detection_stats = preprocessing_state.get('border_detection_stats')
    
    print("\n📐 Manual Split Definition")
    print("=" * 60)
    print("Enter the split ratio as a single number (e.g., 55 for 55/45 split).")
    print("The number represents the percentage for the left page.")
    print("Valid range: 30-70 (to ensure reasonable split)")
    
    while True:
        try:
            ratio_input = input("\nEnter split ratio (30-70, or 'c' to cancel): ").strip().lower()
            
            if ratio_input == 'c':
                print("Cancelled manual split")
                return NavigationResult.show_page('pdf_preview')
            
            ratio = float(ratio_input)
            
            if ratio < 30 or ratio > 70:
                print(f"⚠️  Ratio must be between 30 and 70. You entered {ratio:.1f}")
                continue
            
            break
        except ValueError:
            print("⚠️  Please enter a valid number between 30 and 70")
        except (KeyboardInterrupt, EOFError):
            print("\n❌ Cancelled")
            return NavigationResult.show_page('pdf_preview')
    
    # Get all page widths from PDF for per-page split (handles mixed page sizes)
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(original_pdf))
        if len(doc) == 0:
            print("❌ Error: PDF has no pages")
            doc.close()
            return NavigationResult.show_page('pdf_preview')
        page_widths = [doc[i].rect.width for i in range(len(doc))]
        doc.close()
    except ImportError:
        print("❌ Error: PyMuPDF not available")
        return NavigationResult.show_page('pdf_preview')
    except Exception as e:
        print(f"❌ Error reading PDF: {e}")
        return NavigationResult.show_page('pdf_preview')
    
    # Per-page gutter at requested ratio so mixed page sizes work
    gutter_x_per_page = [w * (ratio / 100) for w in page_widths]
    first_width = page_widths[0]
    first_gutter = gutter_x_per_page[0]
    print(f"📊 Split point: {first_gutter:.1f} (page width: {first_width:.1f}, ratio: {ratio}%)")
    if len(page_widths) > 1:
        print(f"   (per-page split applied to {len(page_widths)} pages)")
    
    # Perform split
    print("\n🔄 Performing manual split...")
    split_path, error_msg = daemon._split_with_custom_gutter(original_pdf, gutter_x_per_page[0], gutter_x_per_page)
    
    if split_path:
        # Update preprocessing state
        preprocessing_state['split_method'] = 'manual'
        preprocessing_state['split_attempted'] = True
        preprocessing_state['manual_split_ratio'] = ratio
        preprocessing_state['border_detection_stats'] = border_detection_stats  # Preserve border stats
        
        ctx['processed_pdf'] = split_path
        ctx['preprocessing_state'] = preprocessing_state
        ctx['original_pdf'] = original_pdf
        
        print(f"✅ Manual split completed: {ratio:.0f}/{100-ratio:.0f}")
        return NavigationResult.show_page('pdf_preview')
    else:
        error_display = f": {error_msg}" if error_msg else ""
        print(f"❌ Manual split failed{error_display}")
        return NavigationResult.show_page('pdf_preview')


def create_note_input_page(daemon) -> Page:
    """Create NOTE INPUT page.
    
    Multi-line note input collection.
    Note: This page uses special handling in NavigationEngine._handle_note_input_page
    """
    def content(ctx):
        lines = [
            "Enter your note (press Enter on a blank line when finished):"
        ]
        return lines
    
    def handler_process_note(ctx):
        """Process the collected note."""
        daemon = ctx['daemon']
        note_lines = ctx.get('_note_lines', [])
        if note_lines:
            note_text = '\n'.join(note_lines)
            item_key = ctx.get('item_key') or ctx['selected_item'].get('key')
            print(f"\n💾 Adding note to Zotero item...")
            if daemon.zotero_processor.add_note_to_item(item_key, note_text):
                print("✅ Note added successfully!")
            else:
                print("⚠️  Failed to add note, continuing...")
        else:
            print("ℹ️  No note text entered, skipping note...")
        
        return NavigationResult.process_pdf()
    
    def quit_action(ctx):
        """Quit - move to manual review."""
        print("📝 Moving to manual review")
        return NavigationResult.quit_scan(move_to_manual=True)
    
    # Note: This page uses special handling in NavigationEngine
    # The engine will collect multi-line input and call handler_process_note
    return Page(
        page_id='note_input',
        title='📝 NOTE INPUT',
        content=content,
        prompt='',  # No prompt - handles multi-line input
        valid_inputs=[],  # Special handling
        handlers={'process': handler_process_note},  # Handler for processed note
        default=None,
        back_page='note_prompt',
        quit_action=quit_action
    )


def create_all_pages(daemon) -> Dict[str, Page]:
    """Create all pages for handle_item_selected flow.
    
    Args:
        daemon: PaperProcessorDaemon instance
        
    Returns:
        Dictionary mapping page_id to Page objects
    """
    return {
        'enrichment_review_auto': create_enrichment_review_auto_page(daemon),
        'enrichment_review_manual': create_enrichment_review_manual_page(daemon),
        'review_and_proceed': create_review_and_proceed_page(daemon),
        'edit_tags': create_edit_tags_page(daemon),
        'proceed_after_edit': create_proceed_after_edit_page(daemon),
        'filename_title_override': create_filename_title_override_page(daemon),
        'proposed_actions': create_proposed_actions_page(daemon),
        'pdf_conflict_decision': create_pdf_conflict_decision_page(daemon),
        'pdf_preview': create_pdf_preview_page(daemon),
        'note_prompt': create_note_prompt_page(daemon),
        'note_input': create_note_input_page(daemon),
    }

