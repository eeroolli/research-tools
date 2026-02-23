#!/usr/bin/env python3
"""
File Renaming Utility for PaddleOCR Output

Renames OCR'd PDF files based on detected language and orientation.
Adds language prefix (EN_, NO_, etc.) and _double suffix if landscape/two-up.
"""

import sys
import argparse
from pathlib import Path
from typing import Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def map_language_to_prefix(lang_code: Optional[str]) -> str:
    """Map language code to filename prefix.
    
    Args:
        lang_code: Language code (en, no, sv, fi, de) or None
        
    Returns:
        Filename prefix (EN_, NO_, SE_, FI_, DE_) or empty string
    """
    if not lang_code:
        return ""
    
    prefix_map = {
        'en': 'EN_',
        'no': 'NO_',
        'sv': 'SE_',  # Swedish -> SE_ (matches daemon convention)
        'fi': 'FI_',
        'de': 'DE_'
    }
    
    return prefix_map.get(lang_code.lower(), '')


def rename_pdf_with_metadata(
    pdf_path: Path,
    language: Optional[str] = None,
    is_two_up: bool = False,
    output_dir: Optional[Path] = None
) -> Path:
    """Rename PDF file with language prefix and orientation suffix.
    
    Args:
        pdf_path: Path to PDF file
        language: Language code (en, no, sv, fi, de) or None
        is_two_up: Whether PDF has two-up (landscape) pages
        output_dir: Optional output directory (if None, renames in place)
        
    Returns:
        Path to renamed file
    """
    # Get base filename (remove existing prefixes/suffixes)
    original_name = pdf_path.stem
    
    # Remove existing language prefixes
    for prefix in ['EN_', 'NO_', 'SE_', 'FI_', 'DE_']:
        if original_name.upper().startswith(prefix):
            original_name = original_name[len(prefix):]
            break
    
    # Remove existing _double suffix
    if original_name.lower().endswith('_double'):
        original_name = original_name[:-7]
    
    # Add language prefix
    lang_prefix = map_language_to_prefix(language)
    new_name = f"{lang_prefix}{original_name}"
    
    # Add orientation suffix
    if is_two_up:
        new_name += "_double"
    
    new_name += ".pdf"
    
    # Determine output path
    if output_dir:
        output_path = output_dir / new_name
    else:
        output_path = pdf_path.parent / new_name
    
    # Rename file
    if pdf_path != output_path:
        pdf_path.rename(output_path)
        print(f"Renamed: {pdf_path.name} → {output_path.name}")
    
    return output_path


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Rename OCR'd PDF files with language prefix and orientation suffix"
    )
    parser.add_argument(
        'pdf_path',
        type=Path,
        help='Path to PDF file'
    )
    parser.add_argument(
        '--language', '-l',
        type=str,
        default=None,
        help='Language code (en, no, sv, fi, de)'
    )
    parser.add_argument(
        '--two-up', '-t',
        action='store_true',
        help='Mark as two-up (landscape) pages'
    )
    parser.add_argument(
        '--output-dir', '-o',
        type=Path,
        default=None,
        help='Output directory (if not specified, renames in place)'
    )
    
    args = parser.parse_args()
    
    if not args.pdf_path.exists():
        print(f"Error: File not found: {args.pdf_path}")
        return 1
    
    if not args.pdf_path.suffix.lower() == '.pdf':
        print(f"Error: File must be a PDF: {args.pdf_path}")
        return 1
    
    # Rename file
    new_path = rename_pdf_with_metadata(
        args.pdf_path,
        language=args.language,
        is_two_up=args.two_up,
        output_dir=args.output_dir
    )
    
    print(f"✅ File renamed: {new_path}")
    return 0


if __name__ == '__main__':
    sys.exit(main())

