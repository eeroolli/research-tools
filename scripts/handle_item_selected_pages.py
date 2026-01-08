"""Page definitions for handle_item_selected flow.

This module defines all pages in the item selection flow using the page-based
navigation system. Pages are self-contained units with display, input validation,
and navigation handlers.
"""

from typing import Dict, List
from shared_tools.ui.navigation import Page, NavigationResult
from shared_tools.utils.filename_generator import FilenameGenerator


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
        
        # Build metadata using ONLY Zotero data
        merged_metadata = {
            'title': zotero_title,
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
        
        # Show what authors will be used in filename
        if zotero_authors:
            author_display = '_'.join([a.split()[-1] if ' ' in a else a for a in zotero_authors[:2]])
            print(f"📝 Filename will use authors: {author_display}")
            print()
        
        # Show filename preview before confirmation
        print(f"📄 Generated filename: {target_filename}")
        print()
        
        # Show PDF comparison if item already has PDF
        has_pdf = ctx.get('has_pdf', False)
        if has_pdf:
            existing_pdf_info = daemon._get_existing_pdf_info(selected_item)
            daemon._display_pdf_comparison(pdf_path, scan_size_mb, existing_pdf_info)
        
        return NavigationResult.show_page('proposed_actions')
    
    def handler_e(ctx):
        """Edit tags - go to EDIT TAGS page."""
        daemon = ctx['daemon']
        item_key = ctx.get('item_key') or ctx['selected_item'].get('key')
        if not item_key:
            print("❌ No item key found - cannot edit tags")
            print("ℹ️  Please edit this item in Zotero, then process the scan again")
            daemon.move_to_manual_review(ctx['pdf_path'])
            return NavigationResult.quit_scan(move_to_manual=True)
        
        return NavigationResult.show_page('edit_tags')
    
    def handler_z(ctx):
        """Go back to item selection."""
        print("⬅️  Going back to item selection")
        return NavigationResult.return_to_caller()
    
    def quit_action(ctx):
        """Quit - move to manual review."""
        daemon = ctx['daemon']
        daemon.move_to_manual_review(ctx['pdf_path'])
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
        daemon = ctx['daemon']
        print("ℹ️  Please edit this item in Zotero, then process the scan again")
        daemon.move_to_manual_review(ctx['pdf_path'])
        return NavigationResult.quit_scan(move_to_manual=True)
    
    def quit_action(ctx):
        """Quit - move to manual review."""
        daemon = ctx['daemon']
        daemon.move_to_manual_review(ctx['pdf_path'])
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
        
        # Build metadata using ONLY Zotero data
        merged_metadata = {
            'title': zotero_title,
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
        
        # Show what authors will be used in filename
        if zotero_authors:
            author_display = '_'.join([a.split()[-1] if ' ' in a else a for a in zotero_authors[:2]])
            print(f"📝 Filename will use authors: {author_display}")
            print()
        
        # Show filename preview before confirmation
        print(f"📄 Generated filename: {target_filename}")
        print()
        
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
        daemon = ctx['daemon']
        daemon.move_to_manual_review(ctx['pdf_path'])
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
        
        lines = [
            f"Scan: {pdf_path.name} ({scan_size_mb:.1f} MB)",
            "",
            "Will perform:",
            f"  1. Check and remove dark borders (if detected)",
            f"  2. Split landscape/two-up pages (if detected)",
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
        
        # Step 1: Preprocess PDF with default options
        print("\n" + "="*70)
        print("PDF PREPROCESSING")
        print("="*70)
        processed_pdf, preprocessing_state = daemon._preprocess_pdf_with_options(
            pdf_path,
            border_removal=True,
            split_method='auto',
            trim_leading=True
        )
        
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
        daemon = ctx['daemon']
        print("📝 Moving to manual review")
        daemon.move_to_manual_review(ctx['pdf_path'])
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


def create_note_prompt_page(daemon) -> Page:
    """Create NOTE PROMPT page.
    
    Asks if user wants to add a handwritten note.
    """
    def content(ctx):
        lines = [
            "You can add a sentence or two from your notes on the paper folder.",
            "  (Enter) Skip - don't add a note",
            "  (n) Add a note",
            "  (z) Cancel and go back"
        ]
        return lines
    
    def handler_enter(ctx):
        """Skip note - process PDF."""
        print("ℹ️  Skipping note...")
        return NavigationResult.process_pdf()
    
    def handler_n(ctx):
        """Add note - go to NOTE INPUT page."""
        return NavigationResult.show_page('note_input')
    
    def handler_z(ctx):
        """Cancel - go back to PDF PREVIEW."""
        print("⬅️  Cancelling note addition")
        return NavigationResult.show_page('pdf_preview')
    
    def quit_action(ctx):
        """Quit - move to manual review."""
        daemon = ctx['daemon']
        daemon.move_to_manual_review(ctx['pdf_path'])
        return NavigationResult.quit_scan(move_to_manual=True)
    
    return Page(
        page_id='note_prompt',
        title='WRITE A NOTE',
        content=content,
        prompt='\nAdd a note? [Enter/n/z]: ',
        valid_inputs=['', 'n', 'z'],
        handlers={
            '': handler_enter,  # Enter key
            'n': handler_n,
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
        
        # Open PDF in viewer
        daemon._open_pdf_in_viewer(processed_pdf)
        
        # Build status lines
        border_status = "✓ Applied" if preprocessing_state.get('border_removal', False) else "✗ Not applied"
        split_method = preprocessing_state.get('split_method', 'none')
        split_attempted = preprocessing_state.get('split_attempted', False)
        
        # Determine split status
        if split_method == 'auto' and split_attempted:
            split_status = "✓ Applied (gutter detection)"
        elif split_method == '50-50' and split_attempted:
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
            else:
                print("⚠️  Invalid choice.")
                return NavigationResult.show_page('pdf_preview')
        return handler
    
    handler_2 = make_handler(2)
    handler_3 = make_handler(3)
    handler_4 = make_handler(4)
    handler_5 = make_handler(5)
    
    def handler_z(ctx):
        """Go back to PROPOSED ACTIONS."""
        print("⬅️  Going back to proposed actions...")
        return NavigationResult.show_page('proposed_actions')
    
    def quit_action(ctx):
        """Quit - move to manual review."""
        daemon = ctx['daemon']
        pdf_path = ctx['pdf_path']
        print("📝 Moving to manual review")
        daemon.move_to_manual_review(pdf_path)
        return NavigationResult.quit_scan(move_to_manual=True)
    
    return Page(
        page_id='pdf_preview',
        title='PDF PREVIEW',
        content=content,
        prompt='\nEnter your choice: ',
        valid_inputs=['1', '2', '3', '4', '5', 'z', 'q'],
        handlers={
            '1': handler_1,
            '2': handler_2,
            '3': handler_3,
            '4': handler_4,
            '5': handler_5,
            'z': handler_z
        },
        default='1',
        back_page='pdf_preview',
        quit_action=quit_action,
        timeout_seconds=daemon.prompt_timeout * 2  # 2x timeout for PDF inspection
    )


def _get_pdf_preview_option_action(option_num: int, preprocessing_state: dict) -> str:
    """Determine what action corresponds to an option number based on current state.
    
    Returns: 'accept', 'drop_border', 'drop_split', 'use_5050', 'drop_trim', 'add_trim', or None
    """
    if option_num == 1:
        return 'accept'
    
    option_count = 1  # Option 1 is always "Accept"
    
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
        daemon = ctx['daemon']
        daemon.move_to_manual_review(ctx['pdf_path'])
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
        'review_and_proceed': create_review_and_proceed_page(daemon),
        'edit_tags': create_edit_tags_page(daemon),
        'proceed_after_edit': create_proceed_after_edit_page(daemon),
        'proposed_actions': create_proposed_actions_page(daemon),
        'pdf_preview': create_pdf_preview_page(daemon),
        'note_prompt': create_note_prompt_page(daemon),
        'note_input': create_note_input_page(daemon),
    }

