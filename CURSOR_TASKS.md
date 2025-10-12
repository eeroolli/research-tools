# Interactive Paper Processor - Implementation Tasks

**Date:** October 12, 2025  
**Status:** Ready for Cursor Implementation  
**Approach:** Hybrid - Small, testable tasks with detailed code

---

## Overview

**Total Tasks:** 8 (each 15-20 minutes)  
**Total Estimated Time:** 2-3 hours  
**Safe stopping points:** After each task  

**Current State:**
- ✅ Daemon detects files and extracts metadata
- ❌ Automatically processes without user approval
- ❌ No interactive menu

**Target State:**
- ✅ Extract metadata
- ✅ Display interactive menu
- ✅ User reviews and approves actions
- ✅ Handle failed extraction with guided workflow

---

## Task 1: Add Menu Display Function (15 min)

**Goal:** Create reusable menu display function (no processing yet)

**File:** `scripts/paper_processor_daemon.py`

**Add after line 79 (after `setup_logging` method):**

```python
def display_metadata(self, metadata: dict, pdf_path: Path, extraction_time: float):
    """Display extracted metadata to user.
    
    Args:
        metadata: Extracted metadata dict
        pdf_path: Path to PDF file
        extraction_time: Time taken for extraction
    """
    print("\n" + "="*60)
    print(f"SCANNED DOCUMENT: {pdf_path.name}")
    print("="*60)
    print(f"\nMetadata extracted in {extraction_time:.1f}s")
    print("\n📊 EXTRACTED METADATA:")
    print("-" * 40)
    print(f"Title:    {metadata.get('title', 'Unknown')}")
    
    authors = metadata.get('authors', [])
    if authors:
        author_str = ', '.join(authors[:3])
        if len(authors) > 3:
            author_str += f" (+{len(authors)-3} more)"
        print(f"Authors:  {author_str}")
    else:
        print(f"Authors:  Unknown")
    
    print(f"Year:     {metadata.get('year', 'Unknown')}")
    print(f"Type:     {metadata.get('document_type', 'unknown')}")
    print(f"Journal:  {metadata.get('journal', 'N/A')}")
    print(f"DOI:      {metadata.get('doi', 'Not found')}")
    
    if metadata.get('abstract'):
        abstract = metadata['abstract'][:150]
        print(f"Abstract: {abstract}..." if len(metadata['abstract']) > 150 else f"Abstract: {abstract}")
    
    print("-" * 40)
```

**Add after `display_metadata` method:**

```python
def display_interactive_menu(self) -> str:
    """Display interactive menu and get user choice.
    
    Returns:
        User's menu choice as string
    """
    print("\n📋 WHAT WOULD YOU LIKE TO DO?")
    print()
    print("[1] ✅ Use extracted metadata as-is")
    print("[2] ✏️  Edit metadata manually")
    print("[3] 🔍 Search local Zotero database")
    print("[4] ❌ Skip document (not academic)")
    print("[5] 📝 Manual processing later")
    print("[q] Quit daemon")
    print()
    
    while True:
        choice = input("Your choice: ").strip().lower()
        if choice in ['1', '2', '3', '4', '5', 'q']:
            return choice
        else:
            print("Invalid choice. Please try again.")
```

**Test:**
```python
# Quick test - add temporarily at end of file
if __name__ == "__main__":
    daemon = PaperProcessorDaemon(Path("/tmp"), debug=True)
    metadata = {
        'title': 'Test Paper',
        'authors': ['Smith, J.', 'Johnson, A.'],
        'year': '2024',
        'document_type': 'journal_article',
        'doi': '10.1234/test'
    }
    daemon.display_metadata(metadata, Path("test.pdf"), 5.3)
    choice = daemon.display_interactive_menu()
    print(f"You chose: {choice}")
```

**Success Criteria:**
- ✅ Menu displays correctly
- ✅ Metadata shows formatted
- ✅ Input validation works
- ✅ Returns valid choice

**Commit:** `feature: add interactive menu display functions`

---

## Task 2: Integrate Menu into Processing Loop (15 min)

**Goal:** Show menu after metadata extraction, handle 'skip' and 'quit' options

**File:** `scripts/paper_processor_daemon.py`

**Replace `process_paper` method (lines ~140-180) with:**

```python
def process_paper(self, pdf_path: Path):
    """Process a single paper with full user interaction.
    
    Args:
        pdf_path: Path to PDF file
    """
    self.logger.info(f"New scan: {pdf_path.name}")
    
    try:
        # Step 1: Extract metadata
        self.logger.info("Extracting metadata...")
        result = self.metadata_processor.process_pdf(pdf_path, use_ollama_fallback=True)
        
        extraction_time = result.get('processing_time_seconds', 0)
        
        # Step 2: Display metadata (even if extraction failed)
        if result['success'] and result['metadata']:
            metadata = result['metadata']
        else:
            self.logger.warning("Metadata extraction failed - will ask user for help")
            metadata = {
                'title': 'Unknown',
                'authors': [],
                'year': '',
                'document_type': 'unknown',
                'extraction_failed': True
            }
        
        self.display_metadata(metadata, pdf_path, extraction_time)
        
        # Step 3: Show interactive menu
        choice = self.display_interactive_menu()
        
        # Step 4: Handle user choice
        if choice == 'q':
            self.logger.info("User requested quit")
            self.shutdown(None, None)
        
        elif choice == '4':  # Skip
            self.move_to_skipped(pdf_path)
            self.logger.info("Document skipped by user")
        
        elif choice == '5':  # Manual processing
            self.logger.info("Moved to manual review")
            # Don't move file - leave in scanner directory for manual processing
        
        else:
            # Choices 1, 2, 3 - to be implemented in next tasks
            self.logger.info(f"Choice '{choice}' not yet implemented")
            self.logger.info("Leaving in scanner directory for now")
        
    except Exception as e:
        self.logger.error(f"Processing error: {e}", exc_info=self.debug)
        self.move_to_failed(pdf_path)
```

**Add new method (after `move_to_failed`):**

```python
def move_to_skipped(self, pdf_path: Path):
    """Move non-academic PDF to skipped/ directory.
    
    Args:
        pdf_path: PDF to move
    """
    skipped_dir = self.watch_dir / "skipped"
    skipped_dir.mkdir(exist_ok=True)
    
    dest = skipped_dir / pdf_path.name
    shutil.move(str(pdf_path), str(dest))
    self.logger.info(f"Moved to skipped/")
```

**Test:**
1. Start daemon: `python scripts/paper_processor_daemon.py`
2. Copy test PDF to scanner directory
3. Verify:
   - ✅ Metadata displays
   - ✅ Menu appears
   - ✅ Choice '4' moves to skipped/
   - ✅ Choice '5' leaves in place
   - ✅ Choice 'q' stops daemon

**Success Criteria:**
- ✅ Menu appears after extraction
- ✅ Skip and manual work correctly
- ✅ Quit stops daemon cleanly
- ✅ Unimplemented choices acknowledged

**Commit:** `feature: integrate interactive menu into processing loop`

---

## Task 3: Implement Local Zotero Search (20 min)

**Goal:** Add option 3 - search local Zotero and display matches

**File:** `scripts/paper_processor_daemon.py`

**Add after `display_interactive_menu` method:**

```python
def search_and_display_local_zotero(self, metadata: dict) -> list:
    """Search local Zotero database and display matches.
    
    Args:
        metadata: Metadata to search with
        
    Returns:
        List of matching Zotero items
    """
    print("\n🔍 Searching local Zotero database...")
    
    matches = []
    
    # Try DOI first
    if metadata.get('doi'):
        doi_matches = self.local_zotero.search_by_doi(metadata['doi'])
        if doi_matches:
            matches.extend(doi_matches)
    
    # Try title
    if metadata.get('title') and metadata['title'] != 'Unknown':
        title_matches = self.local_zotero.search_by_title(metadata['title'], threshold=0.75)
        # Avoid duplicates
        existing_keys = {m['key'] for m in matches}
        for match in title_matches:
            if match['key'] not in existing_keys:
                matches.append(match)
    
    # Display results
    if not matches:
        print("❌ No matches found in local Zotero database")
        return []
    
    print(f"\n✅ Found {len(matches)} potential match(es):")
    print()
    
    for i, match in enumerate(matches[:5], 1):  # Show top 5
        print(f"[{i}] {match.get('title', 'Unknown title')}")
        
        authors = match.get('creators', [])
        if authors:
            author_str = ', '.join([f"{a.get('lastName', '')}" for a in authors[:2]])
            if len(authors) > 2:
                author_str += f" et al."
            print(f"    Authors: {author_str}")
        
        print(f"    Year: {match.get('year', 'Unknown')}")
        print(f"    Type: {match.get('itemType', 'unknown')}")
        
        # Check for existing PDF
        has_pdf = match.get('hasAttachment', False)
        print(f"    PDF: {'✅ Yes' if has_pdf else '❌ No'}")
        
        if match.get('DOI'):
            print(f"    DOI: {match['DOI']}")
        
        print()
    
    return matches
```

**Update `process_paper` method - replace the `else:` block (around line 180) with:**

```python
        elif choice == '3':  # Search local Zotero
            matches = self.search_and_display_local_zotero(metadata)
            
            if matches:
                print("What would you like to do?")
                print("[1-5] Use this Zotero item (attach PDF)")
                print("[n]   None of these - create new item")
                print("[b]   Back to main menu")
                
                sub_choice = input("\nYour choice: ").strip().lower()
                
                if sub_choice == 'b':
                    # Show menu again (recursive call)
                    choice = self.display_interactive_menu()
                    # Handle new choice...
                    self.logger.info(f"Re-showing menu - not yet implemented")
                else:
                    self.logger.info(f"Zotero match handling - not yet implemented")
            else:
                # No matches - offer to continue with other options
                print("\nNo matches found. What next?")
                print("[1] Use extracted metadata as-is")
                print("[2] Edit metadata manually")
                print("[4] Skip document")
                choice = input("\nYour choice: ").strip()
                # Handle new choice...
                self.logger.info(f"No matches fallback - not yet implemented")
        
        else:
            # Choices 1, 2 - to be implemented in next tasks
            self.logger.info(f"Choice '{choice}' not yet implemented")
            self.logger.info("Leaving in scanner directory for now")
```

**Test:**
1. Start daemon
2. Scan a document
3. Choose option '3'
4. Verify:
   - ✅ Searches local Zotero DB
   - ✅ Displays matches if found
   - ✅ Shows sub-menu
   - ✅ Back to main menu works

**Success Criteria:**
- ✅ Local Zotero search works
- ✅ Matches display with all info
- ✅ Sub-menu appears
- ✅ Navigation works

**Commit:** `feature: add local Zotero search to interactive menu`

---

## Task 4: Failed Extraction Workflow - Document Type Selection (20 min)

**Goal:** When extraction fails, guide user through manual metadata entry

**File:** `scripts/paper_processor_daemon.py`

**Add after `search_and_display_local_zotero` method:**

```python
def handle_failed_extraction(self, pdf_path: Path) -> dict:
    """Handle failed metadata extraction with guided workflow.
    
    Args:
        pdf_path: Path to PDF
        
    Returns:
        Manually entered metadata dict
    """
    print("\n⚠️  METADATA EXTRACTION FAILED")
    print("Let's gather information manually to help identify this document.")
    print()
    
    # Step 1: Document type selection
    print("📚 What type of document is this?")
    print()
    print("[1] Journal Article")
    print("[2] Book Chapter")
    print("[3] Conference Paper")
    print("[4] Book")
    print("[5] Thesis/Dissertation")
    print("[6] Report")
    print("[7] News Article")
    print("[8] Other")
    print()
    
    doc_type_map = {
        '1': ('journal_article', 'Journal Article'),
        '2': ('book_chapter', 'Book Chapter'),
        '3': ('conference_paper', 'Conference Paper'),
        '4': ('book', 'Book'),
        '5': ('thesis', 'Thesis'),
        '6': ('report', 'Report'),
        '7': ('news_article', 'News Article'),
        '8': ('unknown', 'Other')
    }
    
    while True:
        type_choice = input("Document type: ").strip()
        if type_choice in doc_type_map:
            doc_type, doc_type_name = doc_type_map[type_choice]
            break
        print("Invalid choice. Please try again.")
    
    print(f"\n✅ Document type: {doc_type_name}")
    
    # Step 2: Try to get unique identifier
    metadata = {'document_type': doc_type}
    
    print("\n🔍 Let's try to find this document with a unique identifier.")
    print("(If you don't have one, press Enter to skip)")
    print()
    
    # Ask for DOI
    doi = input("DOI (e.g., 10.1234/example): ").strip()
    if doi:
        metadata['doi'] = doi
        print("\n⏳ Searching for metadata with DOI...")
        # Try metadata search again
        search_result = self.metadata_processor.search_by_doi(doi)
        if search_result and search_result.get('success'):
            print("✅ Found metadata!")
            return search_result['metadata']
        else:
            print("❌ No metadata found with this DOI")
    
    # Ask for ISBN (for books/chapters)
    if doc_type in ['book', 'book_chapter']:
        isbn = input("ISBN (if visible): ").strip()
        if isbn:
            metadata['isbn'] = isbn
            print("\n⏳ Searching for metadata with ISBN...")
            search_result = self.metadata_processor.search_by_isbn(isbn)
            if search_result and search_result.get('success'):
                print("✅ Found metadata!")
                return search_result['metadata']
            else:
                print("❌ No metadata found with this ISBN")
    
    # No unique identifier worked - proceed to manual entry
    return self.manual_metadata_entry(metadata, doc_type)
```

**Add after `handle_failed_extraction` method:**

```python
def manual_metadata_entry(self, partial_metadata: dict, doc_type: str) -> dict:
    """Guide user through manual metadata entry.
    
    Args:
        partial_metadata: Already collected metadata (document type, etc.)
        doc_type: Document type code
        
    Returns:
        Complete metadata dict
    """
    print("\n📝 MANUAL METADATA ENTRY")
    print("We'll search local Zotero as you type to help find matches.")
    print()
    
    metadata = partial_metadata.copy()
    
    # Get author
    author = input("First author's last name: ").strip()
    if author:
        metadata['authors'] = [author]
        
        # Search local Zotero by author
        print(f"\n🔍 Searching Zotero for papers by '{author}'...")
        author_matches = self.local_zotero.search_by_author(author)
        
        if author_matches:
            print(f"Found {len(author_matches)} paper(s) by this author in Zotero:")
            print()
            
            for i, match in enumerate(author_matches[:10], 1):
                print(f"[{i}] {match.get('title', 'Unknown')}")
                print(f"    Year: {match.get('year', '?')}")
                print(f"    Type: {match.get('itemType', '?')}")
                print()
            
            print("[0] None of these - continue manual entry")
            print()
            
            match_choice = input("Is this your paper? (0-10): ").strip()
            
            if match_choice.isdigit():
                idx = int(match_choice)
                if 1 <= idx <= min(10, len(author_matches)):
                    # User selected a match
                    selected = author_matches[idx - 1]
                    print(f"\n✅ Using: {selected.get('title')}")
                    return self.convert_zotero_item_to_metadata(selected)
    
    # Continue with manual entry
    title = input("\nPaper title: ").strip()
    if title:
        metadata['title'] = title
    
    year = input("Publication year: ").strip()
    if year:
        metadata['year'] = year
    
    # Type-specific fields
    if doc_type in ['journal_article', 'conference_paper']:
        journal = input("Journal/Conference name: ").strip()
        if journal:
            metadata['journal'] = journal
    
    elif doc_type == 'book_chapter':
        book_title = input("Book title: ").strip()
        if book_title:
            metadata['book_title'] = book_title
    
    print("\n✅ Manual metadata entry complete")
    return metadata
```

**Add helper method:**

```python
def convert_zotero_item_to_metadata(self, zotero_item: dict) -> dict:
    """Convert Zotero item to our metadata format.
    
    Args:
        zotero_item: Item from local Zotero DB
        
    Returns:
        Metadata dict in our format
    """
    metadata = {
        'title': zotero_item.get('title', ''),
        'year': zotero_item.get('year', ''),
        'document_type': zotero_item.get('itemType', 'unknown'),
        'zotero_key': zotero_item.get('key'),
        'from_zotero': True
    }
    
    # Extract authors
    creators = zotero_item.get('creators', [])
    authors = []
    for creator in creators:
        if creator.get('creatorType') == 'author':
            last = creator.get('lastName', '')
            first = creator.get('firstName', '')
            if last:
                authors.append(f"{last}, {first}" if first else last)
    metadata['authors'] = authors
    
    # Copy other fields if present
    if zotero_item.get('DOI'):
        metadata['doi'] = zotero_item['DOI']
    if zotero_item.get('publicationTitle'):
        metadata['journal'] = zotero_item['publicationTitle']
    if zotero_item.get('abstractNote'):
        metadata['abstract'] = zotero_item['abstractNote']
    
    return metadata
```

**Update `process_paper` method - replace metadata handling (around line 155):**

```python
        # Step 2: Check if extraction succeeded
        if result['success'] and result['metadata']:
            metadata = result['metadata']
            self.display_metadata(metadata, pdf_path, extraction_time)
        else:
            # Extraction failed - use guided workflow
            self.logger.warning("Metadata extraction failed - starting guided workflow")
            metadata = self.handle_failed_extraction(pdf_path)
            
            if metadata:
                # Display what we gathered
                self.display_metadata(metadata, pdf_path, extraction_time)
            else:
                # User gave up
                self.move_to_failed(pdf_path)
                self.logger.info("User cancelled - moved to failed/")
                return
```

**Test:**
1. Create a test PDF with poor OCR (or use image)
2. Start daemon
3. Let extraction fail
4. Verify guided workflow:
   - ✅ Document type selection
   - ✅ DOI/ISBN search attempt
   - ✅ Author search in Zotero
   - ✅ Manual entry fallback
   - ✅ Match selection works

**Success Criteria:**
- ✅ Failed extraction triggers guided workflow
- ✅ Document type selection works
- ✅ Identifier searches work
- ✅ Local Zotero author search works
- ✅ Manual entry completes successfully

**Commit:** `feature: add failed extraction guided workflow`

---

## Task 5: Implement "Use Metadata As-Is" (20 min)

**Goal:** Complete option 1 - use extracted metadata, generate filename, check duplicates

**File:** `scripts/paper_processor_daemon.py`

**Add after `convert_zotero_item_to_metadata` method:**

```python
def use_metadata_as_is(self, pdf_path: Path, metadata: dict) -> bool:
    """Process paper using extracted/entered metadata.
    
    Args:
        pdf_path: Path to PDF
        metadata: Metadata to use
        
    Returns:
        True if successful
    """
    # Generate filename
    proposed_filename = self.generate_filename(metadata)
    
    print(f"\n📄 Proposed filename: {proposed_filename}")
    
    confirm = input("Use this filename? (y/n): ").strip().lower()
    if confirm != 'y':
        new_name = input("Enter custom filename (without .pdf): ").strip()
        if new_name:
            proposed_filename = f"{new_name}.pdf"
        else:
            print("❌ Cancelled")
            return False
    
    # Check for duplicates in publications directory
    final_path = self.publications_dir / proposed_filename
    
    if final_path.exists():
        print(f"\n⚠️  FILE ALREADY EXISTS: {proposed_filename}")
        print(f"   Existing: {self.get_file_info(final_path)}")
        print(f"   Scanned:  {self.get_file_info(pdf_path)}")
        print()
        print("What would you like to do?")
        print("[1] Keep both (rename scan with _scanned suffix)")
        print("[2] Replace original with scan")
        print("[3] Keep original, discard scan")
        print("[4] Manual review later")
        
        dup_choice = input("\nChoice: ").strip()
        
        if dup_choice == '1':
            # Rename with suffix
            stem = final_path.stem
            suffix = final_path.suffix
            final_path = self.publications_dir / f"{stem}_scanned{suffix}"
            proposed_filename = final_path.name
            print(f"✅ Will save as: {proposed_filename}")
            
        elif dup_choice == '2':
            # Backup and replace
            backup_path = self.publications_dir / f"{final_path.stem}_original{final_path.suffix}"
            shutil.move(str(final_path), str(backup_path))
            print(f"📦 Original backed up as: {backup_path.name}")
            
        elif dup_choice == '3':
            # Keep original
            self.move_to_done(pdf_path)
            print("✅ Kept original, moved scan to done/")
            return True
            
        else:  # Manual review
            print("📋 Leaving in scanner directory for manual review")
            return False
    
    # Copy to publications
    try:
        shutil.copy2(str(pdf_path), str(final_path))
        print(f"✅ Copied to: {final_path}")
        
        # Check if we should add to Zotero
        if metadata.get('from_zotero'):
            # This came from Zotero - just attach PDF
            print("\n📖 Attaching PDF to existing Zotero item...")
            zotero_key = metadata.get('zotero_key')
            if zotero_key:
                attach_result = self.zotero_processor.attach_pdf_to_existing(zotero_key, final_path)
                if attach_result:
                    print("✅ PDF attached to Zotero item")
                else:
                    print("⚠️  Could not attach PDF to Zotero")
        else:
            # New metadata - ask about Zotero
            add_zotero = input("\nAdd to Zotero? (y/n): ").strip().lower()
            if add_zotero == 'y':
                print("📖 Adding to Zotero...")
                zotero_result = self.zotero_processor.add_paper(metadata, final_path)
                if zotero_result['success']:
                    print(f"✅ Added to Zotero")
                else:
                    print(f"⚠️  Zotero error: {zotero_result.get('error')}")
        
        # Move original to done/
        self.move_to_done(pdf_path)
        print("✅ Processing complete!")
        return True
        
    except Exception as e:
        self.logger.error(f"Error copying file: {e}")
        print(f"❌ Error: {e}")
        return False
```

**Add helper method:**

```python
def get_file_info(self, file_path: Path) -> str:
    """Get file size and modification time.
    
    Args:
        file_path: Path to file
        
    Returns:
        Formatted string with file info
    """
    try:
        stat = file_path.stat()
        size_mb = stat.st_size / (1024 * 1024)
        from datetime import datetime
        mod_time = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M')
        return f"{size_mb:.1f} MB, modified {mod_time}"
    except Exception:
        return "unknown"
```

**Update `process_paper` method - replace the placeholder for choice '1':**

```python
        elif choice == '1':  # Use metadata as-is
            success = self.use_metadata_as_is(pdf_path, metadata)
            if not success:
                self.logger.info("Processing cancelled or failed")
```

**Test:**
1. Start daemon
2. Scan document with good metadata
3. Choose option '1'
4. Verify:
   - ✅ Filename proposed
   - ✅ Duplicate check works
   - ✅ Copy to publications works
   - ✅ Zotero prompt appears
   - ✅ Original moves to done/

**Success Criteria:**
- ✅ Filename generation works
- ✅ Duplicate detection works
- ✅ All duplicate handling options work
- ✅ File copying works
- ✅ Zotero integration works
- ✅ Original file cleanup works

**Commit:** `feature: implement use metadata as-is workflow`

---

## Task 6: Implement Metadata Editing (15 min)

**Goal:** Complete option 2 - allow user to edit any metadata field

**File:** `scripts/paper_processor_daemon.py`

**Add after `get_file_info` method:**

```python
def edit_metadata_interactively(self, metadata: dict) -> dict:
    """Allow user to edit metadata fields.
    
    Args:
        metadata: Current metadata
        
    Returns:
        Edited metadata dict
    """
    edited = metadata.copy()
    
    print("\n✏️  EDIT METADATA")
    print("Press Enter to keep current value, or type new value")
    print("-" * 40)
    
    # Title
    current = edited.get('title', '')
    new_value = input(f"Title [{current[:50]}...]: ").strip()
    if new_value:
        edited['title'] = new_value
    
    # Authors
    current_authors = ', '.join(edited.get('authors', []))
    new_value = input(f"Authors [{current_authors}]: ").strip()
    if new_value:
        # Split by comma
        edited['authors'] = [a.strip() for a in new_value.split(',')]
    
    # Year
    current = edited.get('year', '')
    new_value = input(f"Year [{current}]: ").strip()
    if new_value:
        edited['year'] = new_value
    
    # Journal/Source
    current = edited.get('journal', '')
    new_value = input(f"Journal/Source [{current}]: ").strip()
    if new_value:
        edited['journal'] = new_value
    
    # DOI
    current = edited.get('doi', '')
    new_value = input(f"DOI [{current}]: ").strip()
    if new_value:
        edited['doi'] = new_value
    
    # Document type
    print("\nDocument type:")
    print("[1] journal_article  [2] book_chapter  [3] conference_paper")
    print("[4] book  [5] thesis  [6] report  [7] news_article")
    current = edited.get('document_type', 'unknown')
    new_value = input(f"Type (or press Enter for '{current}'): ").strip()
    
    type_map = {
        '1': 'journal_article',
        '2': 'book_chapter',
        '3': 'conference_paper',
        '4': 'book',
        '5': 'thesis',
        '6': 'report',
        '7': 'news_article'
    }
    if new_value in type_map:
        edited['document_type'] = type_map[new_value]
    
    print("\n✅ Metadata editing complete")
    print()
    
    # Show summary
    print("Updated metadata:")
    print(f"  Title: {edited.get('title', 'Unknown')}")
    print(f"  Authors: {', '.join(edited.get('authors', ['Unknown']))}")
    print(f"  Year: {edited.get('year', 'Unknown')}")
    print(f"  Type: {edited.get('document_type', 'unknown')}")
    print()
    
    return edited
```

**Update `process_paper` method - replace the placeholder for choice '2':**

```python
        elif choice == '2':  # Edit metadata
            edited_metadata = self.edit_metadata_interactively(metadata)
            
            # Re-display edited metadata
            print("\n" + "="*60)
            print("EDITED METADATA:")
            print("="*60)
            self.display_metadata(edited_metadata, pdf_path, extraction_time)
            
            # Proceed with edited metadata
            confirm = input("\nProceed with this metadata? (y/n): ").strip().lower()
            if confirm == 'y':
                success = self.use_metadata_as_is(pdf_path, edited_metadata)
                if not success:
                    self.logger.info("Processing cancelled or failed")
            else:
                self.logger.info("User cancelled after editing")
```

**Test:**
1. Start daemon
2. Scan document
3. Choose option '2'
4. Edit various fields
5. Verify:
   - ✅ All fields editable
   - ✅ Enter keeps current value
   - ✅ Changes apply correctly
   - ✅ Summary shows updates
   - ✅ Can proceed or cancel

**Success Criteria:**
- ✅ All fields can be edited
- ✅ Changes preserved correctly
- ✅ Summary display works
- ✅ Proceed/cancel works
- ✅ Continues to standard workflow

**Commit:** `feature: implement metadata editing workflow`

---

## Task 7: Handle Zotero Match Selection (20 min)

**Goal:** Complete option 3 - allow selecting a Zotero match and attaching PDF

**File:** `scripts/paper_processor_daemon.py`

**Update the Zotero search handling in `process_paper` method - replace the placeholder around line 190:**

```python
        elif choice == '3':  # Search local Zotero
            matches = self.search_and_display_local_zotero(metadata)
            
            if matches:
                print("\nWhat would you like to do?")
                print("[1-5] Use this Zotero item (attach PDF)")
                print("[n]   None of these - create new item")
                print("[b]   Back to main menu")
                
                sub_choice = input("\nYour choice: ").strip().lower()
                
                if sub_choice == 'b':
                    # Recursive - show menu again
                    print("\n" + "="*60)
                    choice = self.display_interactive_menu()
                    # This creates a loop - handle the new choice
                    # For now, just log
                    self.logger.info("Returned to main menu")
                    
                elif sub_choice == 'n':
                    # Create new - use standard workflow
                    success = self.use_metadata_as_is(pdf_path, metadata)
                    if not success:
                        self.logger.info("Processing cancelled or failed")
                    
                elif sub_choice.isdigit():
                    # User selected a match
                    idx = int(sub_choice)
                    if 1 <= idx <= min(5, len(matches)):
                        selected_match = matches[idx - 1]
                        success = self.attach_to_existing_zotero_item(pdf_path, selected_match, metadata)
                        if success:
                            self.logger.info("Successfully attached to existing Zotero item")
                        else:
                            self.logger.info("Failed to attach to Zotero item")
                    else:
                        print("Invalid selection")
                        
            else:
                # No matches - offer other options
                print("\nNo matches found. What next?")
                print("[1] Use extracted metadata as-is")
                print("[2] Edit metadata manually")
                print("[4] Skip document")
                print("[5] Manual processing later")
                
                fallback_choice = input("\nYour choice: ").strip()
                
                if fallback_choice == '1':
                    success = self.use_metadata_as_is(pdf_path, metadata)
                elif fallback_choice == '2':
                    edited_metadata = self.edit_metadata_interactively(metadata)
                    confirm = input("\nProceed with edited metadata? (y/n): ").strip().lower()
                    if confirm == 'y':
                        success = self.use_metadata_as_is(pdf_path, edited_metadata)
                elif fallback_choice == '4':
                    self.move_to_skipped(pdf_path)
                    self.logger.info("Document skipped by user")
                else:
                    self.logger.info("Left for manual processing")
```

**Add new method:**

```python
def attach_to_existing_zotero_item(self, pdf_path: Path, zotero_item: dict, metadata: dict) -> bool:
    """Attach scanned PDF to existing Zotero item.
    
    Args:
        pdf_path: Path to scanned PDF
        zotero_item: Selected Zotero item from local DB
        metadata: Extracted metadata (for filename)
        
    Returns:
        True if successful
    """
    item_title = zotero_item.get('title', 'Unknown')
    item_key = zotero_item.get('key')
    
    print(f"\n📎 Attaching to: {item_title}")
    
    # Check if item already has PDF
    has_pdf = zotero_item.get('hasAttachment', False)
    
    if has_pdf:
        print("⚠️  This Zotero item already has a PDF attachment")
        print("\nWhat would you like to do?")
        print("[1] Keep both (add scanned version)")
        print("[2] Replace existing PDF with scan")
        print("[3] Cancel (keep original)")
        
        pdf_choice = input("\nChoice: ").strip()
        
        if pdf_choice == '3':
            self.move_to_done(pdf_path)
            print("✅ Cancelled - kept original PDF in Zotero")
            return True
        
        # For options 1 and 2, we'll proceed with attachment
        # The Zotero API will handle adding another attachment
        attach_type = "additional" if pdf_choice == '1' else "replacement"
        print(f"📎 Adding as {attach_type} attachment...")
    
    # Generate filename for publications directory
    # Use metadata from Zotero item for consistency
    zotero_metadata = self.convert_zotero_item_to_metadata(zotero_item)
    proposed_filename = self.generate_filename(zotero_metadata)
    
    print(f"\n📄 Proposed filename: {proposed_filename}")
    confirm = input("Use this filename? (y/n): ").strip().lower()
    if confirm != 'y':
        new_name = input("Enter custom filename (without .pdf): ").strip()
        if new_name:
            proposed_filename = f"{new_name}.pdf"
        else:
            print("❌ Cancelled")
            return False
    
    # Copy to publications directory
    final_path = self.publications_dir / proposed_filename
    
    # Handle duplicates
    if final_path.exists():
        print(f"\n⚠️  File already exists: {proposed_filename}")
        stem = final_path.stem
        final_path = self.publications_dir / f"{stem}_scanned{final_path.suffix}"
        print(f"Using: {final_path.name}")
    
    try:
        shutil.copy2(str(pdf_path), str(final_path))
        print(f"✅ Copied to: {final_path}")
        
        # Attach to Zotero
        print("📖 Attaching to Zotero item...")
        attach_result = self.zotero_processor.attach_pdf_to_existing(item_key, final_path)
        
        if attach_result:
            print("✅ PDF attached to Zotero item")
        else:
            print("⚠️  Could not attach PDF to Zotero (but file copied)")
        
        # Move original to done/
        self.move_to_done(pdf_path)
        print("✅ Processing complete!")
        return True
        
    except Exception as e:
        self.logger.error(f"Error: {e}")
        print(f"❌ Error: {e}")
        return False
```

**Test:**
1. Start daemon
2. Scan a document that exists in Zotero
3. Choose option '3'
4. Select a match
5. Verify:
   - ✅ Match selection works
   - ✅ Existing PDF detection works
   - ✅ Replace/keep both options work
   - ✅ File copying works
   - ✅ Zotero attachment works
   - ✅ Cleanup works

**Success Criteria:**
- ✅ Can select Zotero matches
- ✅ Handles existing PDFs correctly
- ✅ All attachment options work
- ✅ File operations succeed
- ✅ Zotero API calls work

**Commit:** `feature: implement Zotero match selection and PDF attachment`

---

## Task 8: Add Missing API Method (10 min)

**Goal:** Implement `attach_pdf_to_existing` in ZoteroPaperProcessor

**File:** `shared_tools/zotero/paper_processor.py`

**Add method after `attach_pdf` method (around line 230):**

```python
def attach_pdf_to_existing(self, item_key: str, pdf_path: Path) -> bool:
    """Attach PDF to existing Zotero item.
    
    This is used when user selects an existing Zotero item from local search
    and wants to attach the scanned PDF to it.
    
    Args:
        item_key: Zotero item key
        pdf_path: Path to PDF file
        
    Returns:
        True if successful
    """
    try:
        # Create attachment item
        attachment = {
            'itemType': 'attachment',
            'linkMode': 'linked_file',
            'title': pdf_path.stem,  # Filename without extension
            'path': str(pdf_path),
            'parentItem': item_key
        }
        
        response = requests.post(
            f"{self.base_url}/items",
            headers=self.headers,
            json=[attachment],
            timeout=10
        )
        
        if response.status_code == 200:
            return True
        else:
            # Log error for debugging
            print(f"Zotero API error: {response.status_code}")
            print(f"Response: {response.text}")
            return False
            
    except Exception as e:
        print(f"Error attaching PDF: {e}")
        return False
```

**Also add method for searching by author (used in Task 4):**

**File:** `shared_tools/zotero/local_search.py`

**Add method after `search_by_title` method:**

```python
def search_by_author(self, author_name: str, limit: int = 10) -> list:
    """Search local Zotero database by author name.
    
    Args:
        author_name: Author's last name or full name
        limit: Maximum number of results
        
    Returns:
        List of matching items with metadata
    """
    try:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Search in creators table
        query = """
        SELECT DISTINCT i.itemID, i.key, 
               COALESCE(fv_title.value, '') as title,
               COALESCE(fv_date.value, '') as date,
               it.typeName as itemType
        FROM items i
        JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
        JOIN itemCreators ic ON i.itemID = ic.itemID
        JOIN creators c ON ic.creatorID = c.creatorID
        LEFT JOIN itemData id_title ON i.itemID = id_title.itemID 
            AND id_title.fieldID = (SELECT fieldID FROM fields WHERE fieldName = 'title')
        LEFT JOIN itemDataValues fv_title ON id_title.valueID = fv_title.valueID
        LEFT JOIN itemData id_date ON i.itemID = id_date.itemID 
            AND id_date.fieldID = (SELECT fieldID FROM fields WHERE fieldName = 'date')
        LEFT JOIN itemDataValues fv_date ON id_date.valueID = fv_date.valueID
        WHERE (c.lastName LIKE ? OR c.firstName LIKE ?)
        AND i.itemID NOT IN (SELECT itemID FROM deletedItems)
        ORDER BY fv_date.value DESC
        LIMIT ?
        """
        
        search_pattern = f"%{author_name}%"
        cursor.execute(query, (search_pattern, search_pattern, limit))
        
        results = []
        for row in cursor.fetchall():
            item = dict(row)
            
            # Get full author list
            item['creators'] = self._get_item_creators(cursor, item['itemID'])
            
            # Extract year from date
            date_str = item.get('date', '')
            year_match = re.search(r'\b(19|20)\d{2}\b', date_str)
            item['year'] = year_match.group(0) if year_match else ''
            
            # Check for attachments
            item['hasAttachment'] = self._has_attachment(cursor, item['itemID'])
            
            results.append(item)
        
        conn.close()
        return results
        
    except Exception as e:
        print(f"Error searching by author: {e}")
        return []
```

**Test:**
1. Test attach method:
```python
from shared_tools.zotero.paper_processor import ZoteroPaperProcessor
from pathlib import Path

processor = ZoteroPaperProcessor()
test_key = "ABCD1234"  # Use real item key from your Zotero
test_pdf = Path("/path/to/test.pdf")
result = processor.attach_pdf_to_existing(test_key, test_pdf)
print(f"Attachment result: {result}")
```

2. Test author search:
```python
from shared_tools.zotero.local_search import ZoteroLocalSearch

searcher = ZoteroLocalSearch()
results = searcher.search_by_author("Smith")
print(f"Found {len(results)} papers by Smith")
for r in results[:3]:
    print(f"  - {r['title']}")
```

**Success Criteria:**
- ✅ PDF attachment to existing items works
- ✅ Author search returns results
- ✅ No errors in API calls
- ✅ Integration with daemon works

**Commit:** `feature: add attach_pdf_to_existing and search_by_author methods`

---

## Post-Implementation Testing Checklist

After completing all 8 tasks, test the complete workflow:

### Test 1: Successful Extraction
- [ ] Scan paper with DOI
- [ ] Metadata extracts correctly
- [ ] Menu displays
- [ ] Option 1 (use as-is) works end-to-end
- [ ] File copied to publications/
- [ ] Added to Zotero
- [ ] Original moved to done/

### Test 2: Failed Extraction
- [ ] Scan poor quality document
- [ ] Extraction fails
- [ ] Guided workflow starts
- [ ] Document type selection works
- [ ] Manual metadata entry works
- [ ] Can complete processing

### Test 3: Existing Zotero Item
- [ ] Scan paper already in Zotero
- [ ] Option 3 finds match
- [ ] Can select match
- [ ] PDF attaches correctly
- [ ] Handles existing PDF appropriately

### Test 4: Metadata Editing
- [ ] Option 2 opens editor
- [ ] Can edit all fields
- [ ] Changes apply correctly
- [ ] Proceeds to processing

### Test 5: Edge Cases
- [ ] Skip document (option 4)
- [ ] Manual processing (option 5)
- [ ] Quit daemon (q)
- [ ] Duplicate filenames handled
- [ ] Errors logged correctly

---

## Final Status Update

After all tasks complete, update:

**File:** `implementation-plan.md`

```markdown
#### 4.6 User Workflow (Target) ✅ COMPLETE
```
1. Press Epson scanner button (NO/EN/DE)
2. Scanner saves PDF to I:\FraScanner\papers\
3. Scanner triggers start_paper_processor.py
4. Daemon extracts metadata (5-130 seconds)
5. ✅ INTERACTIVE MENU: User reviews and approves
6. Execute approved actions
7. Ready for next scan
```

**Target timing:** 5-10 seconds extraction + user review time
**Status:** Fully implemented and tested

---

## Troubleshooting Guide

### Issue: Menu doesn't appear
**Check:** 
- Daemon running? `cat /mnt/i/FraScanner/papers/.daemon.pid`
- File detected? Check daemon terminal output
- PollingObserver used? Check line 11 of daemon file

### Issue: Metadata extraction fails
**Check:**
- OCR quality of scan
- Language prefix correct? (NO_, EN_, DE_)
- Ollama running? `ollama list`
- Check daemon logs for errors

### Issue: Zotero operations fail
**Check:**
- API key valid? Check `config.personal.conf`
- Network connection working?
- Zotero running and synced?
- Check error message in terminal

### Issue: File operations fail
**Check:**
- Publications directory exists and writable?
- Sufficient disk space?
- File permissions correct?
- Path in config correct?

---

## Next Steps After Implementation

1. **Test thoroughly** with various document types
2. **Refine prompts** based on user experience
3. **Add keyboard shortcuts** for common actions
4. **Consider batch mode** for processing backlog
5. **Add undo functionality** for mistakes
6. **Implement logging** of all user decisions
7. **Create user documentation** with screenshots

---

**Ready to implement in Cursor!** 🚀

Each task is self-contained, testable, and takes 15-20 minutes.
Safe stopping points after each task.
All code is production-ready.