#!/usr/bin/env python3
"""
Main book processing script with smart integrated processor
"""

import sys
import logging
import json
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.extractors.isbn_extractor import ISBNExtractor
from src.processors.smart_integrated_processor_v3 import SmartIntegratedProcessorV3
from src.utils.file_manager import FileManager

def setup_logging():
    """Set up logging configuration"""
    log_dir = Path("data/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Configure logging with both file and console output
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_dir / f'processing_{datetime.now():%Y%m%d_%H%M%S}.log'),
            logging.StreamHandler()
        ]
    )
    
    # Set specific log levels
    logging.getLogger('src.processors').setLevel(logging.INFO)
    logging.getLogger('src.extractors').setLevel(logging.INFO)

def save_results(results: list, output_file: str = "/mnt/f/prog/research-tools/data/book_processing_log.json"):
    """Save processing results to JSON with error handling"""
    output_path = Path(output_file)
    
    # Load existing data with error handling
    existing_data = {}
    if output_path.exists():
        try:
            with open(output_path, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
        except json.JSONDecodeError as e:
            logging.warning(f"Could not read existing JSON, backing up and starting fresh: {e}")
            # Backup corrupted file
            backup_path = output_path.with_suffix('.json.corrupt')
            output_path.rename(backup_path)
            existing_data = {}
        except Exception as e:
            logging.error(f"Error loading existing data: {e}")
            existing_data = {}
    
    # Add new results
    timestamp = datetime.now().isoformat()
    for result in results:
        # Use filename as key (Zotero script expects this format)
        key = result['filename']
        existing_data[key] = result
    
    # Save updated data with proper encoding
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(existing_data, f, indent=2, ensure_ascii=False)

def format_time(seconds: float) -> str:
    """Format time in human-readable format"""
    if seconds < 60:
        return f"{seconds:.1f}s"
    else:
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}m {secs:.0f}s"

def main():
    """Main processing function"""
    setup_logging()
    logger = logging.getLogger(__name__)
    
    print("\n" + "="*60)
    print("Smart Book ISBN Extraction System")
    print("="*60)
    
    # Initialize components
    print("Initializing components...")
    extractor = ISBNExtractor()
    file_manager = FileManager()
    
    # Get photos to process
    photos = file_manager.get_pending_photos()
    
    # Initialize processor with photo batch for crop detection
    processor = SmartIntegratedProcessorV3(photo_batch=photos)
    
    # Show current stats
    stats = file_manager.get_stats()
    print(f"\nCurrent Status:")
    print(f"  Pending photos: {stats['pending']}")
    print(f"  Processed: {stats['total_processed']} (Success: {stats['done']}, Failed: {stats['failed']})")
    
    if not photos:
        print("\nNo photos to process!")
        print("Place photos in: /mnt/i/FraMobil/Camera/Books/")
        return
    
    print(f"\nProcessing {len(photos)} photos...")
    print("Using intelligent strategy ordering based on image analysis")
    print("-" * 60)
    
    results = []
    successful = 0
    total_time = 0
    
    for i, photo in enumerate(photos, 1):
        print(f"\n[{i}/{len(photos)}] {photo.name}")
        
        try:
            # Process image with smart processor
            image_data = processor.process_photo(photo)
            total_time += image_data.processing_time
            
            # Extract ISBN
            isbn_results = []
            if image_data.barcode:
                # Try barcode data
                isbn_results = extractor.extract_from_text(image_data.barcode)
                source = "barcode"
            elif image_data.ocr_text:
                # Try OCR text
                isbn_results = extractor.extract_from_text(image_data.ocr_text)
                source = "ocr"
            else:
                source = "none"
            
            if isbn_results:
                # Found ISBN(s)
                best_result = max(isbn_results, key=lambda r: r.confidence)
                print(f"  ✅ ISBN: {best_result.isbn}")
                print(f"     Method: {image_data.preprocessing_used} ({image_data.attempts} attempts)")
                print(f"     Time: {image_data.processing_time:.1f}s")
                
                result_data = {
                    'status': 'success',
                    'isbn': best_result.isbn,
                    'filename': photo.name,
                    'method': image_data.preprocessing_used,
                    'confidence': best_result.confidence,
                    'attempts': image_data.attempts,
                    'processing_time': image_data.processing_time,
                    'timestamp': datetime.now().isoformat()
                }
                results.append(result_data)
                
                file_manager.move_to_done(photo)
                successful += 1
            else:
                # No ISBN found
                print(f"  ❌ No ISBN found after {image_data.attempts} attempts")
                print(f"     Time: {image_data.processing_time:.1f}s")
                
                result_data = {
                    'status': 'failed',
                    'isbn': None,
                    'filename': photo.name,
                    'method': 'failed',
                    'error': 'No ISBN detected',
                    'attempts': image_data.attempts,
                    'processing_time': image_data.processing_time,
                    'timestamp': datetime.now().isoformat()
                }
                results.append(result_data)
                
                file_manager.move_to_failed(photo)
                
        except Exception as e:
            logger.error(f"Error processing {photo}: {e}")
            print(f"  ❌ Error: {e}")
            file_manager.move_to_failed(photo)
    
    # Save results
    save_results(results)
    
    # Calculate statistics
    avg_time = total_time / len(photos) if photos else 0
    success_rate = (successful / len(photos) * 100) if photos else 0
    
    # Show summary
    print("\n" + "="*60)
    print("Processing Summary")
    print("="*60)
    print(f"Total processed: {len(photos)}")
    print(f"Successful: {successful} ({success_rate:.1f}%)")
    print(f"Failed: {len(photos) - successful}")
    print(f"\nTiming:")
    print(f"  Total time: {format_time(total_time)}")
    print(f"  Average per photo: {avg_time:.1f}s")
    print(f"  Estimated for 800 books: {format_time(800 * avg_time)}")
    print(f"\nResults saved to: data/book_processing_log.json")
    
    # Show next steps
    if successful > 0:
        print("\nNext steps:")
        print("1. Review successful extractions")
        print("2. Run 'python scripts/active/zotero_api_book_processor_enhanced.py' to add books to Zotero")
        print("3. Check 'failed' folder for manual review")
    
    # Show performance tips if slow
    if avg_time > 10:
        print("\nPerformance tip: Consider resizing large photos before processing")

if __name__ == "__main__":
    main()
