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

from shared_tools.extractors.isbn_extractor import ISBNExtractor
from shared_tools.processors.smart_integrated_processor_v3 import SmartIntegratedProcessorV3
from shared_tools.utils.file_manager import FileManager

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

def save_results(results: list, output_file: str = "data/books/book_processing_log.csv"):
    """Save processing results to CSV with error handling"""
    import csv
    
    output_path = Path(output_file)
    
    # Ensure directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Define CSV fieldnames
    fieldnames = ['filename', 'status', 'isbn', 'method', 'confidence', 'attempts', 
                  'processing_time', 'retry_count', 'timestamp', 'error']
    
    # Read existing data if file exists
    existing_data = {}
    if output_path.exists():
        try:
            with open(output_path, 'r', encoding='utf-8', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    existing_data[row['filename']] = row
        except Exception as e:
            logging.warning(f"Could not read existing CSV, backing up and starting fresh: {e}")
            backup_path = output_path.with_suffix('.csv.corrupt')
            output_path.rename(backup_path)
            existing_data = {}
    
    # Update with new results
    for result in results:
        # Ensure all fields are present
        csv_row = {field: result.get(field, '') for field in fieldnames}
        existing_data[result['filename']] = csv_row
    
    # Write updated data to CSV
    with open(output_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in existing_data.values():
            writer.writerow(row)

def format_time(seconds: float) -> str:
    """Format time in human-readable format"""
    if seconds < 60:
        return f"{seconds:.1f}s"
    else:
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}m {secs:.0f}s"

def show_processing_results():
    """Show a summary of successful ISBN extractions"""
    log_file = Path("data/books/book_processing_log.csv")
    if not log_file.exists():
        return
    
    try:
        successful_books = []
        with open(log_file, 'r', encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('status') == 'success' and row.get('isbn'):
                    successful_books.append({
                        'filename': row.get('filename', ''),
                        'isbn': row.get('isbn', ''),
                        'method': row.get('method', ''),
                        'confidence': row.get('confidence', ''),
                        'processing_time': row.get('processing_time', '')
                    })
        
        print(f"\n📚 Books ready for Zotero ({len(successful_books)}):")
        print("-" * 60)
        
        if not successful_books:
            print("   No successful ISBN extractions found.")
        else:
            for i, book in enumerate(successful_books[:10], 1):  # Show first 10
                print(f"{i:2d}. {book['filename']:<30} ISBN: {book['isbn']:<15} Method: {book['method']}")
            
            if len(successful_books) > 10:
                print(f"    ... and {len(successful_books) - 10} more books")
        
    except Exception as e:
        logger.error(f"Error showing processing results: {e}")

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
    
    # Initialize processor (no batch processing)
    processor = SmartIntegratedProcessorV3()
    
    # Show current stats
    stats = file_manager.get_stats()
    print(f"\nCurrent Status:")
    print(f"  Pending photos: {stats['pending']}")
    print(f"  Processed: {stats['total_processed']} (Success: {stats['done']}, Failed: {stats['failed']}, Permanently Failed: {stats['permanently_failed']})")
    
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
        print(f"\n[{i}/{len(photos)}] Processing {photo.name} (image {i} of {len(photos)} images)")
        
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
                    'retry_count': 0,  # Reset retry count on success
                    'timestamp': datetime.now().isoformat()
                }
                results.append(result_data)
                
                file_manager.move_to_done(photo)
                successful += 1
            else:
                # No ISBN found
                print(f"  ❌ No ISBN found after {image_data.attempts} attempts")
                print(f"     Time: {image_data.processing_time:.1f}s")
                
                # Get current retry count from processing log
                processed_files = file_manager._load_processed_files()
                current_retry_count = processed_files.get(photo.name, {}).get('retry_count', 0)
                new_retry_count = current_retry_count + 1
                
                result_data = {
                    'status': 'failed',
                    'isbn': None,
                    'filename': photo.name,
                    'method': 'failed',
                    'error': 'No ISBN detected',
                    'attempts': image_data.attempts,
                    'processing_time': image_data.processing_time,
                    'retry_count': new_retry_count,
                    'timestamp': datetime.now().isoformat()
                }
                results.append(result_data)
                
                file_manager.move_to_failed(photo, new_retry_count)
                
        except Exception as e:
            logger.error(f"Error processing {photo}: {e}")
            print(f"  ❌ Error: {e}")
            
            # Get current retry count for error case
            processed_files = file_manager._load_processed_files()
            current_retry_count = processed_files.get(photo.name, {}).get('retry_count', 0)
            new_retry_count = current_retry_count + 1
            
            file_manager.move_to_failed(photo, new_retry_count)
    
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
    
    # Show final stats
    final_stats = file_manager.get_stats()
    print(f"\nFinal Status:")
    print(f"  Done: {final_stats['done']}")
    print(f"  Failed (retryable): {final_stats['failed']}")
    print(f"  Permanently Failed: {final_stats['permanently_failed']}")
    print(f"\nTiming:")
    print(f"  Total time: {format_time(total_time)}")
    print(f"  Average per photo: {avg_time:.1f}s")
    print(f"  Estimated for 800 books: {format_time(800 * avg_time)}")
    print(f"\nResults saved to: data/books/book_processing_log.csv")
    
    # Show detailed results summary
    show_processing_results()
    
    # Show next steps
    print("\nNext steps:")
    print("1. Review successful extractions in data/books/book_processing_log.csv")
    print("2. Check 'data/books/failed/' and 'data/books/permanently_failed/' for manual review\n of processed images")
    
    # Show performance tips if slow
    if avg_time > 10:
        print("\nPerformance tip: Consider resizing large photos before processing")

if __name__ == "__main__":
    main()
