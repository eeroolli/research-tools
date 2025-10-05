# Enhanced Zotero Book Processor Features

## Overview

The enhanced Zotero book processor now includes advanced features for managing books in your Zotero library with multi-digit input, smart tag groups, and intelligent item handling.

## New Features

### 1. Multi-Digit Input System

You can now combine multiple actions in a single input:

- **Single digit**: `1` = Add keep tags
- **Multiple digits**: `17` = Add keep tags + Update metadata
- **Complex combinations**: `123` = Add keep tags + Add give away tags + Add political tags

### 2. Tag Groups

Predefined tag groups for different purposes:

- **Group 1 (Keep)**: `Eero har`, `personal`, `owned`
- **Group 2 (Give Away)**: `Eero hadde`, `gitt bort`, `donated`
- **Group 3 (Political)**: `political behavior`, `party preference`, `voting`
- **Group 4 (Academic)**: `academic`, `research`, `scholarly`
- **Group 5 (Fiction)**: `fiction`, `novel`, `literature`
- **Group 6 (Nonfiction)**: `nonfiction`, `non-fiction`, `educational`

### 3. Enhanced Menu System

The new menu shows:
- Clear action descriptions
- Multi-digit input examples
- Destructive action warnings
- Book status (existing vs new)

### 4. Smart Item Handling

- **Existing items**: Show differences, allow updates, tag management
- **New items**: Add with selected tags, then allow additional actions
- **Metadata comparison**: See differences between Zotero and online data

### 5. Action System

Available actions:
1. **Add keep tags** - Mark book as personal/owned
2. **Add give away tags** - Mark book for donation
3. **Add political tags** - Add political topic tags
4. **Add academic tags** - Add research/scholarly tags
5. **Add fiction tags** - Add literature tags
6. **Add nonfiction tags** - Add educational tags
7. **Update metadata** - Update all metadata fields
8. **Remove item** - Delete from Zotero (with confirmation)
9. **Show differences** - Compare Zotero vs online metadata

## Configuration

### Config Files

The system uses a two-tier configuration:

1. **`config.conf`** (public, on GitHub) - Default settings
2. **`config.personal.conf`** (private, NOT on GitHub) - Personal overrides

### Configuration Sections

#### TAG_GROUPS
```ini
[TAG_GROUPS]
group1_keep = Eero har,personal,owned
group2_give_away = Eero hadde,gitt bort,donated
group3_political = political behavior,party preference,voting
```

#### ACTIONS
```ini
[ACTIONS]
action1 = add_keep_tags:Add tags for keeping the book
action2 = add_give_away_tags:Add tags for giving away the book
action7 = update_metadata:Update all metadata fields
```

#### MENU_OPTIONS
```ini
[MENU_OPTIONS]
show_metadata_tags = true
show_differences = true
allow_multi_digit = true
confirm_destructive_actions = true
```

## Usage Examples

### Basic Usage

```bash
python scripts/add_or_remove_books_zotero.py
```

### Multi-Digit Input Examples

- `1` - Add keep tags only
- `17` - Add keep tags + update metadata
- `123` - Add keep tags + give away tags + political tags
- `q` - Quit

### Workflow Examples

#### For Existing Books
1. Book found in Zotero
2. Show enhanced menu with current status
3. User enters `17` (keep tags + update metadata)
4. System adds keep tags and updates metadata
5. Ask if user wants more actions

#### For New Books
1. Book not in Zotero
2. Get online metadata
3. Show enhanced menu
4. User enters `1` (add keep tags)
5. System adds book to Zotero with keep tags
6. Ask if user wants more actions

## Advanced Features

### Difference Detection

When comparing Zotero items with online metadata:

- **Field comparison**: Title, author, publisher, date, etc.
- **Tag comparison**: Shows tags only in Zotero vs online
- **Creator comparison**: Author information differences
- **Visual indicators**: ⚠️ Different, ➕ Additional, ➖ Missing

### Smart Tag Management

- **Duplicate prevention**: Won't add tags that already exist
- **Metadata integration**: Combines personal tags with online metadata tags
- **Batch processing**: Remembers previous tag selections

### Safety Features

- **Destructive action confirmation**: Requires confirmation for item removal
- **Error handling**: Graceful failure with detailed error messages
- **Logging**: Comprehensive logging of all actions taken

## Testing

Run the test suite to verify functionality:

```bash
python test_enhanced_zotero.py
```

This will test:
- Configuration loading
- Multi-digit input parsing
- Enhanced menu display
- Tag group management

## Migration from Legacy System

The enhanced system is backward compatible:

- Existing configuration files still work
- Legacy menu options are still available
- All previous functionality is preserved
- New features are opt-in through configuration

## Troubleshooting

### Common Issues

1. **Configuration not loading**: Check file paths and permissions
2. **Actions not working**: Verify action numbers in configuration
3. **Tags not applying**: Check tag group definitions
4. **API errors**: Verify Zotero credentials

### Debug Mode

Enable debug output by setting environment variable:
```bash
export DEBUG=1
python scripts/add_or_remove_books_zotero.py
```

## Future Enhancements

Planned features:
- Custom tag group definitions
- Batch processing improvements
- Advanced metadata comparison
- Integration with other library systems
- Automated tag suggestions based on content analysis
