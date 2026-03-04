#!/usr/bin/env python3
"""
CLI Entry Point for PDF Invoice Extraction Pipeline
Supports single PDF processing, batch directory processing, and file watching
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

# Add app to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from app.services.ocr_service import OCRService
from app.services.line_item_extractor import LineItemExtractor, LineItemResult
from app.services.agentic_lookup import AgenticLookupService

# Try to import PDF processing
try:
    import fitz  # PyMuPDF
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False
    print("Warning: PyMuPDF not installed. Install with: pip install PyMuPDF")

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("Warning: Pillow not installed. Install with: pip install Pillow")


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure logging based on verbosity"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    return logging.getLogger(__name__)


def pdf_to_images(pdf_path: str) -> List[Image.Image]:
    """Convert PDF pages to PIL Images"""
    if not PDF_AVAILABLE:
        raise ImportError("PyMuPDF is required for PDF processing")
    
    images = []
    doc = fitz.open(pdf_path)
    
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        # Higher DPI for better OCR
        mat = fitz.Matrix(2.0, 2.0)  # 2x zoom = ~144 DPI
        pix = page.get_pixmap(matrix=mat)
        
        # Convert to PIL Image
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        images.append(img)
    
    doc.close()
    return images


def line_item_to_dict(item: LineItemResult) -> Dict[str, Any]:
    """Convert LineItemResult to JSON-serializable dict"""
    result = {
        "supplier_name": item.supplier_name,
        "item_description": item.item_description,
        "manufacturer_part_number": item.manufacturer_part_number,
        "original_uom": item.original_uom,
        "detected_pack_quantity": item.detected_pack_quantity,
        "canonical_base_uom": item.canonical_base_uom,
        "price_per_base_unit": item.price_per_base_unit,
        "confidence_score": item.confidence_score,
        "escalation_flag": item.escalation_flag,
        "escalation_reasons": [str(r.value) if hasattr(r, 'value') else str(r) for r in item.escalation_reasons],
        "hsn_code": item.hsn_code,
        "sac_code": item.sac_code,
        "quantity": item.quantity,
        "unit_price": item.unit_price,
        "total_amount": item.total_amount,
        "raw_line": item.raw_line,
    }
    
    if item.pack_info:
        result["pack_info"] = {
            "quantity": item.pack_info.quantity,
            "unit": item.pack_info.unit.value if hasattr(item.pack_info.unit, 'value') else str(item.pack_info.unit),
            "confidence": item.pack_info.confidence,
            "source": item.pack_info.source.value if hasattr(item.pack_info.source, 'value') else str(item.pack_info.source),
        }
    else:
        result["pack_info"] = None
    
    return result


async def process_single_pdf(
    pdf_path: str,
    output_path: Optional[str] = None,
    supplier_name: Optional[str] = None,
    enable_lookup: bool = True,
    verbose: bool = False
) -> Dict[str, Any]:
    """
    Process a single PDF file and extract line items
    
    Args:
        pdf_path: Path to PDF file
        output_path: Optional output JSON file path
        supplier_name: Known supplier name (optional)
        enable_lookup: Enable agentic lookup for missing UOM
        verbose: Verbose output
        
    Returns:
        Extraction results dictionary
    """
    logger = setup_logging(verbose)
    start_time = time.time()
    
    logger.info(f"Processing: {pdf_path}")
    
    # Validate file exists
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")
    
    # Initialize services
    ocr_service = OCRService()
    extractor = LineItemExtractor()
    lookup_service = AgenticLookupService() if enable_lookup else None
    
    try:
        # Step 1: Convert PDF to images
        logger.info("Converting PDF to images...")
        images = pdf_to_images(pdf_path)
        logger.info(f"Converted {len(images)} pages")
        
        # Step 2: OCR each page
        logger.info("Running OCR...")
        all_text = []
        ocr_results = []
        
        for i, img in enumerate(images):
            logger.debug(f"Processing page {i + 1}/{len(images)}")
            result = ocr_service.extract_text(img)
            all_text.append(result.text)
            ocr_results.append({
                "page": i + 1,
                "method": result.method.value,
                "confidence": result.confidence,
                "text_length": len(result.text)
            })
            logger.debug(f"Page {i + 1}: {result.method.value}, confidence: {result.confidence:.2f}")
        
        combined_text = "\n\n".join(all_text)
        logger.info(f"OCR complete. Total text length: {len(combined_text)} chars")
        
        # Step 3: Extract line items
        logger.info("Extracting line items...")
        line_items = extractor.extract_line_items(combined_text, supplier_name)
        logger.info(f"Extracted {len(line_items)} line items")
        
        # Step 4: Agentic lookup for missing UOM
        if enable_lookup and lookup_service:
            logger.info("Running agentic lookup for missing UOM...")
            enhanced_items = []
            for item in line_items:
                if item.escalation_flag or not item.pack_info:
                    logger.debug(f"Looking up: {item.item_description[:50] if item.item_description else 'N/A'}...")
                    enhanced_item = await lookup_service.enhance_line_item(item)
                    enhanced_items.append(enhanced_item)
                else:
                    enhanced_items.append(item)
            line_items = enhanced_items
            logger.info("Agentic lookup complete")
        
        # Build result
        processing_time = time.time() - start_time
        
        result = {
            "file_name": os.path.basename(pdf_path),
            "file_path": pdf_path,
            "processed_at": datetime.now().isoformat(),
            "processing_time_seconds": round(processing_time, 2),
            "total_pages": len(images),
            "ocr_summary": {
                "total_pages": len(images),
                "avg_confidence": sum(r["confidence"] for r in ocr_results) / len(ocr_results) if ocr_results else 0,
                "methods_used": list(set(r["method"] for r in ocr_results)),
                "page_details": ocr_results
            },
            "extraction_summary": {
                "total_line_items": len(line_items),
                "items_with_uom": sum(1 for item in line_items if item.original_uom),
                "items_with_mpn": sum(1 for item in line_items if item.manufacturer_part_number),
                "items_requiring_escalation": sum(1 for item in line_items if item.escalation_flag),
                "avg_confidence": sum(item.confidence_score for item in line_items) / len(line_items) if line_items else 0,
                "agentic_lookup_used": enable_lookup
            },
            "line_items": [line_item_to_dict(item) for item in line_items]
        }
        
        # Save output if path provided
        if output_path:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            logger.info(f"Results saved to: {output_path}")
        
        # Print summary
        logger.info(f"\n{'='*50}")
        logger.info(f"EXTRACTION SUMMARY")
        logger.info(f"{'='*50}")
        logger.info(f"File: {result['file_name']}")
        logger.info(f"Pages: {result['total_pages']}")
        logger.info(f"Line Items: {result['extraction_summary']['total_line_items']}")
        logger.info(f"Items with UOM: {result['extraction_summary']['items_with_uom']}")
        logger.info(f"Items with MPN: {result['extraction_summary']['items_with_mpn']}")
        logger.info(f"Escalations: {result['extraction_summary']['items_requiring_escalation']}")
        logger.info(f"Avg Confidence: {result['extraction_summary']['avg_confidence']:.2f}")
        logger.info(f"Processing Time: {result['processing_time_seconds']}s")
        logger.info(f"{'='*50}\n")
        
        return result
        
    finally:
        # Cleanup
        if lookup_service:
            await lookup_service.close()


async def process_batch(
    input_dir: str,
    output_dir: str,
    supplier_name: Optional[str] = None,
    enable_lookup: bool = True,
    verbose: bool = False
) -> Dict[str, Any]:
    """
    Process all PDFs in a directory
    
    Args:
        input_dir: Directory containing PDF files
        output_dir: Directory for output JSON files
        supplier_name: Known supplier name (optional)
        enable_lookup: Enable agentic lookup
        verbose: Verbose output
        
    Returns:
        Batch processing summary
    """
    logger = setup_logging(verbose)
    
    # Validate directories
    if not os.path.isdir(input_dir):
        raise NotADirectoryError(f"Input directory not found: {input_dir}")
    
    os.makedirs(output_dir, exist_ok=True)
    
    # Find all PDFs
    pdf_files = list(Path(input_dir).glob("*.pdf")) + list(Path(input_dir).glob("*.PDF"))
    
    if not pdf_files:
        logger.warning(f"No PDF files found in: {input_dir}")
        return {"processed": 0, "failed": 0, "results": []}
    
    logger.info(f"Found {len(pdf_files)} PDF files to process")
    
    results = []
    failed = []
    
    for i, pdf_path in enumerate(pdf_files):
        logger.info(f"\n[{i + 1}/{len(pdf_files)}] Processing: {pdf_path.name}")
        
        output_path = os.path.join(output_dir, f"{pdf_path.stem}.json")
        
        try:
            result = await process_single_pdf(
                str(pdf_path),
                output_path,
                supplier_name,
                enable_lookup,
                verbose
            )
            results.append({
                "file": pdf_path.name,
                "status": "success",
                "line_items": result["extraction_summary"]["total_line_items"],
                "escalations": result["extraction_summary"]["items_requiring_escalation"]
            })
        except Exception as e:
            logger.error(f"Failed to process {pdf_path.name}: {e}")
            failed.append({
                "file": pdf_path.name,
                "status": "failed",
                "error": str(e)
            })
    
    # Summary
    summary = {
        "input_directory": input_dir,
        "output_directory": output_dir,
        "total_files": len(pdf_files),
        "processed": len(results),
        "failed": len(failed),
        "results": results,
        "failures": failed
    }
    
    # Save batch summary
    summary_path = os.path.join(output_dir, "_batch_summary.json")
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2)
    
    logger.info(f"\n{'='*50}")
    logger.info(f"BATCH PROCESSING COMPLETE")
    logger.info(f"{'='*50}")
    logger.info(f"Total: {len(pdf_files)}, Success: {len(results)}, Failed: {len(failed)}")
    logger.info(f"Summary saved to: {summary_path}")
    logger.info(f"{'='*50}\n")
    
    return summary


def watch_directory(
    watch_dir: str,
    output_dir: Optional[str] = None,
    supplier_name: Optional[str] = None,
    enable_lookup: bool = True,
    verbose: bool = False
):
    """
    Watch a directory for new PDFs and process them automatically
    
    Args:
        watch_dir: Directory to watch for new PDFs
        output_dir: Directory for output JSON files (default: same as watch_dir)
        supplier_name: Known supplier name (optional)
        enable_lookup: Enable agentic lookup
        verbose: Verbose output
    """
    logger = setup_logging(verbose)
    
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        logger.error("watchdog is required for file watching. Install with: pip install watchdog")
        sys.exit(1)
    
    if not os.path.isdir(watch_dir):
        raise NotADirectoryError(f"Watch directory not found: {watch_dir}")
    
    output_dir = output_dir or watch_dir
    os.makedirs(output_dir, exist_ok=True)
    
    processed_files = set()
    
    class PDFHandler(FileSystemEventHandler):
        def on_created(self, event):
            if event.is_directory:
                return
            
            file_path = event.src_path
            if not file_path.lower().endswith('.pdf'):
                return
            
            if file_path in processed_files:
                return
            
            processed_files.add(file_path)
            
            # Wait for file to be fully written
            time.sleep(1)
            
            logger.info(f"New PDF detected: {file_path}")
            
            output_path = os.path.join(
                output_dir, 
                f"{Path(file_path).stem}.json"
            )
            
            try:
                asyncio.run(process_single_pdf(
                    file_path,
                    output_path,
                    supplier_name,
                    enable_lookup,
                    verbose
                ))
            except Exception as e:
                logger.error(f"Failed to process {file_path}: {e}")
    
    event_handler = PDFHandler()
    observer = Observer()
    observer.schedule(event_handler, watch_dir, recursive=False)
    observer.start()
    
    logger.info(f"\n{'='*50}")
    logger.info(f"FILE WATCHER STARTED")
    logger.info(f"{'='*50}")
    logger.info(f"Watching: {watch_dir}")
    logger.info(f"Output: {output_dir}")
    logger.info(f"Agentic Lookup: {'Enabled' if enable_lookup else 'Disabled'}")
    logger.info(f"Press Ctrl+C to stop")
    logger.info(f"{'='*50}\n")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        logger.info("\nFile watcher stopped")
    
    observer.join()


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="PDF Invoice Extraction Pipeline CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process single PDF
  python cli.py process invoice.pdf -o output.json -v
  
  # Batch process directory
  python cli.py batch ./invoices/ ./output/
  
  # Watch directory for new PDFs
  python cli.py watch ./input_folder/ -o ./output/
  
  # Process without agentic lookup
  python cli.py process invoice.pdf --no-lookup
  
  # Specify supplier name
  python cli.py process invoice.pdf --supplier "ABC Corp"
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Process command
    process_parser = subparsers.add_parser("process", help="Process a single PDF file")
    process_parser.add_argument("pdf_path", help="Path to PDF file")
    process_parser.add_argument("-o", "--output", help="Output JSON file path")
    process_parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    process_parser.add_argument("--no-lookup", action="store_true", help="Disable agentic lookup")
    process_parser.add_argument("--supplier", help="Known supplier name")
    
    # Batch command
    batch_parser = subparsers.add_parser("batch", help="Process all PDFs in a directory")
    batch_parser.add_argument("input_dir", help="Input directory containing PDFs")
    batch_parser.add_argument("output_dir", help="Output directory for JSON files")
    batch_parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    batch_parser.add_argument("--no-lookup", action="store_true", help="Disable agentic lookup")
    batch_parser.add_argument("--supplier", help="Known supplier name")
    
    # Watch command
    watch_parser = subparsers.add_parser("watch", help="Watch directory for new PDFs")
    watch_parser.add_argument("watch_dir", help="Directory to watch for new PDFs")
    watch_parser.add_argument("-o", "--output", help="Output directory for JSON files")
    watch_parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    watch_parser.add_argument("--no-lookup", action="store_true", help="Disable agentic lookup")
    watch_parser.add_argument("--supplier", help="Known supplier name")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    try:
        if args.command == "process":
            asyncio.run(process_single_pdf(
                args.pdf_path,
                args.output,
                args.supplier,
                not args.no_lookup,
                args.verbose
            ))
        
        elif args.command == "batch":
            asyncio.run(process_batch(
                args.input_dir,
                args.output_dir,
                args.supplier,
                not args.no_lookup,
                args.verbose
            ))
        
        elif args.command == "watch":
            watch_directory(
                args.watch_dir,
                args.output,
                args.supplier,
                not args.no_lookup,
                args.verbose
            )
    
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except NotADirectoryError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nOperation cancelled")
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
