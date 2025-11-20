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
        
        # Generate target filename with _scan suffix
        filename_gen = FilenameGenerator()
        target_filename = filename_gen.generate(merged_metadata, is_scan=True) + '.pdf'
        
        # Store in context
        ctx['zotero_authors'] = zotero_authors
        ctx['zotero_title'] = zotero_title
        ctx['zotero_year'] = zotero_year
        ctx['zotero_item_type'] = zotero_item_type
        ctx['target_filename'] = target_filename
        
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
            "Tags have been updated.",
            "  (y/Enter) Proceed with PDF attachment",
            "  (n) Go back to review"
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
        
        # Store in context
        ctx['zotero_authors'] = zotero_authors
        ctx['zotero_title'] = zotero_title
        ctx['zotero_year'] = zotero_year
        ctx['zotero_item_type'] = zotero_item_type
        ctx['target_filename'] = target_filename
        
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
        """Go back to REVIEW & PROCEED."""
        print("⬅️  Going back...")
        return NavigationResult.show_page('review_and_proceed')
    
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
        back_page='review_and_proceed',
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
            f"  1. Generate filename: {target_filename}",
            f"  2. Copy to publications: {publications_dir}/",
            f"  3. Attach as linked file in Zotero",
            f"  4. Move scan to: done/",
            "",
            "  (y/Enter) Proceed with all actions",
            "  (z) Go back to review",
            "  (q) Quit - move to manual review"
        ]
        return lines
    
    def handler_y(ctx):
        """Proceed - go to NOTE PROMPT."""
        item_key = ctx.get('item_key') or ctx['selected_item'].get('key')
        if item_key:
            # Note prompt will be handled by NOTE_PROMPT_PAGE
            return NavigationResult.show_page('note_prompt')
        else:
            # No item key, skip note and process directly
            return NavigationResult.process_pdf()
    
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
        """Cancel - go back to PROPOSED ACTIONS."""
        print("⬅️  Cancelling note addition")
        return NavigationResult.show_page('proposed_actions')
    
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
        back_page='proposed_actions',
        quit_action=quit_action
    )


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
        'note_prompt': create_note_prompt_page(daemon),
        'note_input': create_note_input_page(daemon),
    }

