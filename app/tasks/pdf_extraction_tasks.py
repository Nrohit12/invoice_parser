"""
Celery tasks for PDF extraction and processing
Handles async OCR processing, line item extraction, and agentic lookup
"""

import asyncio
import logging
import time
import traceback
import io
from typing import Dict, Any, List, Optional
from pathlib import Path
from celery import current_task
from PIL import Image
import fitz  # PyMuPDF for PDF processing

from app.celery_app import celery_app
from app.services.ocr_service import OCRService, OCRResult
from app.services.line_item_extractor import LineItemExtractor, LineItemResult
from app.services.agentic_lookup import AgenticLookupService
from app.db.database import get_db, SessionLocal
from app.db.models import ExtractionJob, ExtractedLineItem
from sqlalchemy.orm import Session
from datetime import datetime


@celery_app.task(bind=True)
def process_pdf_extraction(self, job_id: str, pdf_path: str, options: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Main PDF extraction task with full pipeline:
    1. PDF to images conversion
    2. OCR processing with fallbacks
    3. Line item extraction with UOM detection
    4. Agentic lookup for missing UOM
    5. Structured output generation
    
    Args:
        job_id: Unique job identifier
        pdf_path: Path to PDF file
        options: Processing options (enable_agentic_lookup, etc.)
        
    Returns:
        Structured extraction results
    """
    
    logger = logging.getLogger(__name__)
    start_time = time.time()
    
    try:
        # Update task state
        current_task.update_state(
            state="PROGRESS",
            meta={
                "current": 1,
                "total": 6,
                "status": "Starting PDF extraction",
                "job_id": job_id
            }
        )
        
        # Initialize options
        options = options or {}
        enable_agentic_lookup = options.get("enable_agentic_lookup", True)
        supplier_name = options.get("supplier_name")
        
        # Step 1: Convert PDF to images
        current_task.update_state(
            state="PROGRESS",
            meta={
                "current": 2,
                "total": 6,
                "status": "Converting PDF to images",
                "job_id": job_id
            }
        )
        
        images = convert_pdf_to_images(pdf_path)
        if not images:
            raise ValueError("Failed to extract images from PDF")
        
        logger.info(f"Extracted {len(images)} pages from PDF")
        
        # Step 2: OCR Processing
        current_task.update_state(
            state="PROGRESS",
            meta={
                "current": 3,
                "total": 6,
                "status": f"Running OCR on {len(images)} pages",
                "job_id": job_id
            }
        )
        
        ocr_service = OCRService()
        ocr_results = []
        
        for i, image in enumerate(images):
            page_result = ocr_service.extract_text(image)
            ocr_results.append({
                "page": i + 1,
                "text": page_result.text,
                "method": page_result.method.value,
                "confidence": page_result.confidence,
                "processing_time": page_result.processing_time,
                "error": page_result.error
            })
            
            # Update progress for each page
            current_task.update_state(
                state="PROGRESS",
                meta={
                    "current": 3,
                    "total": 6,
                    "status": f"OCR completed for page {i + 1}/{len(images)}",
                    "job_id": job_id
                }
            )
        
        # Combine text from all pages
        full_text = "\n\n--- PAGE BREAK ---\n\n".join([r["text"] for r in ocr_results if r["text"]])
        
        if not full_text.strip():
            raise ValueError("No text extracted from PDF")
        
        # Step 3: Line Item Extraction
        current_task.update_state(
            state="PROGRESS",
            meta={
                "current": 4,
                "total": 6,
                "status": "Extracting line items with UOM detection",
                "job_id": job_id
            }
        )
        
        extractor = LineItemExtractor()
        line_items = extractor.extract_line_items(full_text, supplier_name)
        
        logger.info(f"Extracted {len(line_items)} line items")
        
        # Step 4: Agentic Lookup (if enabled)
        enhanced_items = line_items
        if enable_agentic_lookup and line_items:
            current_task.update_state(
                state="PROGRESS",
                meta={
                    "current": 5,
                    "total": 6,
                    "status": "Running agentic lookup for missing UOM",
                    "job_id": job_id
                }
            )
            
            # Run agentic lookup asynchronously
            enhanced_items = asyncio.run(run_agentic_lookup_batch(line_items))
            
            logger.info(f"Completed agentic lookup for {len(enhanced_items)} items")
        
        # Step 5: Generate structured output
        current_task.update_state(
            state="PROGRESS",
            meta={
                "current": 6,
                "total": 6,
                "status": "Generating structured output",
                "job_id": job_id
            }
        )
        
        # Save to database using proper session management
        db = SessionLocal()
        try:
            # Update extraction job
            job = db.query(ExtractionJob).filter(ExtractionJob.job_id == job_id).first()
            if job:
                job.status = "completed"
                job.processing_time = time.time() - start_time
                job.total_pages = len(images)
                job.total_line_items = len(enhanced_items)
                job.escalation_count = sum(1 for item in enhanced_items if item.escalation_flag)
                job.ocr_method = ocr_results[0]["method"] if ocr_results else None
                job.ocr_confidence = sum(r["confidence"] for r in ocr_results) / len(ocr_results) if ocr_results else 0
                job.completed_at = datetime.utcnow()
                
                # Save line items
                for item in enhanced_items:
                    line_item = ExtractedLineItem(
                        job_id=job_id,
                        supplier_name=item.supplier_name,
                        item_description=item.item_description,
                        manufacturer_part_number=item.manufacturer_part_number,
                        original_uom=item.original_uom,
                        detected_pack_quantity=item.detected_pack_quantity,
                        canonical_base_uom=item.canonical_base_uom,
                        price_per_base_unit=item.price_per_base_unit,
                        confidence_score=item.confidence_score,
                        escalation_flag=item.escalation_flag,
                        escalation_reasons=[r.value for r in item.escalation_reasons] if item.escalation_reasons else [],
                        hsn_code=item.hsn_code,
                        sac_code=item.sac_code,
                        quantity=item.quantity,
                        unit_price=item.unit_price,
                        total_amount=item.total_amount,
                        raw_line=item.raw_line,
                        pack_info={
                            "quantity": item.pack_info.quantity,
                            "unit": item.pack_info.unit.value,
                            "confidence": item.pack_info.confidence,
                            "source": item.pack_info.source.value
                        } if item.pack_info else None
                    )
                    db.add(line_item)
                
                db.commit()
                logger.info(f"Successfully saved job {job_id} with {len(enhanced_items)} line items to database")
            else:
                logger.error(f"Job {job_id} not found in database")
            
        except Exception as e:
            logger.error(f"Failed to save to database: {str(e)}")
            logger.error(traceback.format_exc())
            db.rollback()
        finally:
            db.close()
        
        # Convert to structured format for response
        structured_items = []
        for item in enhanced_items:
            structured_items.append({
                "supplier_name": item.supplier_name,
                "item_description": item.item_description,
                "manufacturer_part_number": item.manufacturer_part_number,
                "original_uom": item.original_uom,
                "detected_pack_quantity": item.detected_pack_quantity,
                "canonical_base_uom": item.canonical_base_uom,
                "price_per_base_unit": item.price_per_base_unit,
                "confidence_score": item.confidence_score,
                "escalation_flag": item.escalation_flag,
                "escalation_reasons": [r.value for r in item.escalation_reasons] if item.escalation_reasons else [],
                
                # Additional metadata
                "hsn_code": item.hsn_code,
                "sac_code": item.sac_code,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "total_amount": item.total_amount,
                "raw_line": item.raw_line,
                "pack_info": {
                    "quantity": item.pack_info.quantity,
                    "unit": item.pack_info.unit.value,
                    "confidence": item.pack_info.confidence,
                    "source": item.pack_info.source.value
                } if item.pack_info else None
            })
        
        processing_time = time.time() - start_time
        
        # Final result
        result = {
            "job_id": job_id,
            "status": "completed",
            "processing_time": processing_time,
            "pdf_path": pdf_path,
            "total_pages": len(images),
            "total_line_items": len(structured_items),
            "escalation_count": sum(1 for item in enhanced_items if item.escalation_flag),
            
            # OCR metadata
            "ocr_results": ocr_results,
            "ocr_summary": {
                "total_pages": len(ocr_results),
                "successful_pages": sum(1 for r in ocr_results if r["text"]),
                "avg_confidence": sum(r["confidence"] for r in ocr_results) / len(ocr_results) if ocr_results else 0,
                "methods_used": list(set(r["method"] for r in ocr_results))
            },
            
            # Extraction results
            "line_items": structured_items,
            
            # Processing options
            "options": options,
            
            # Summary statistics
            "summary": {
                "items_with_uom": sum(1 for item in enhanced_items if item.original_uom),
                "items_with_mpn": sum(1 for item in enhanced_items if item.manufacturer_part_number),
                "items_requiring_escalation": sum(1 for item in enhanced_items if item.escalation_flag),
                "avg_confidence": sum(item.confidence_score for item in enhanced_items) / len(enhanced_items) if enhanced_items else 0,
                "agentic_lookup_used": enable_agentic_lookup
            }
        }
        
        logger.info(f"PDF extraction completed in {processing_time:.2f}s - {len(structured_items)} items extracted")
        
        return result
        
    except Exception as e:
        logger.error(f"PDF extraction failed for job {job_id}: {str(e)}")
        logger.error(traceback.format_exc())
        
        return {
            "job_id": job_id,
            "status": "failed",
            "error": str(e),
            "processing_time": time.time() - start_time,
            "pdf_path": pdf_path
        }


def convert_pdf_to_images(pdf_path: str, dpi: int = 200) -> List[Image.Image]:
    """
    Convert PDF pages to PIL Images
    
    Args:
        pdf_path: Path to PDF file
        dpi: Resolution for conversion
        
    Returns:
        List of PIL Images
    """
    
    images = []
    
    try:
        # Open PDF with PyMuPDF
        pdf_document = fitz.open(pdf_path)
        
        for page_num in range(pdf_document.page_count):
            # Get page
            page = pdf_document[page_num]
            
            # Convert to image
            mat = fitz.Matrix(dpi/72, dpi/72)  # Scale factor for DPI
            pix = page.get_pixmap(matrix=mat)
            
            # Convert to PIL Image
            img_data = pix.tobytes("ppm")
            img = Image.open(io.BytesIO(img_data))
            
            images.append(img)
        
        pdf_document.close()
        
    except Exception as e:
        logging.error(f"Failed to convert PDF to images: {e}")
        return []
    
    return images


async def run_agentic_lookup_batch(line_items: List[LineItemResult]) -> List[LineItemResult]:
    """
    Run agentic lookup on batch of line items
    
    Args:
        line_items: List of line items needing enhancement
        
    Returns:
        Enhanced line items with resolved UOM
    """
    
    lookup_service = AgenticLookupService()
    enhanced_items = []
    
    try:
        # Process items that need UOM resolution
        for item in line_items:
            # Only run lookup if UOM is missing or low confidence
            if (not item.pack_info or 
                item.pack_info.confidence < 0.6 or 
                item.pack_info.unit.value == "UNK"):
                
                enhanced_item = await lookup_service.enhance_line_item(item)
                enhanced_items.append(enhanced_item)
            else:
                enhanced_items.append(item)
        
        return enhanced_items
        
    finally:
        await lookup_service.close()


@celery_app.task(bind=True)
def process_bulk_pdfs(self, job_ids: List[str], pdf_paths: List[str], options: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Process multiple PDFs in batch
    
    Args:
        job_ids: List of job identifiers
        pdf_paths: List of PDF file paths
        options: Processing options
        
    Returns:
        Batch processing results
    """
    
    logger = logging.getLogger(__name__)
    start_time = time.time()
    
    try:
        total_files = len(pdf_paths)
        results = []
        
        for i, (job_id, pdf_path) in enumerate(zip(job_ids, pdf_paths)):
            current_task.update_state(
                state="PROGRESS",
                meta={
                    "current": i + 1,
                    "total": total_files,
                    "status": f"Processing file {i + 1}/{total_files}: {Path(pdf_path).name}",
                    "batch_job_id": f"batch_{int(time.time())}"
                }
            )

            # Process individual PDF synchronously within this task
            # Avoid creating a nested Celery subtask and calling .get() inside a task
            result = process_pdf_extraction.run(job_id, pdf_path, options)
            results.append(result)
            
            logger.info(f"Completed {i + 1}/{total_files}: {job_id}")
        
        # Aggregate results
        successful = sum(1 for r in results if r.get("status") == "completed")
        failed = total_files - successful
        total_items = sum(r.get("total_line_items", 0) for r in results if r.get("status") == "completed")
        
        batch_result = {
            "status": "completed",
            "processing_time": time.time() - start_time,
            "total_files": total_files,
            "successful_files": successful,
            "failed_files": failed,
            "total_line_items": total_items,
            "results": results,
            "summary": {
                "success_rate": successful / total_files if total_files > 0 else 0,
                "avg_items_per_file": total_items / successful if successful > 0 else 0
            }
        }
        
        logger.info(f"Batch processing completed: {successful}/{total_files} files successful")
        
        return batch_result
        
    except Exception as e:
        logger.error(f"Batch processing failed: {str(e)}")
        
        return {
            "status": "failed",
            "error": str(e),
            "processing_time": time.time() - start_time,
            "total_files": len(pdf_paths)
        }
