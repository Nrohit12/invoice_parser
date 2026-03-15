"""
FastAPI router for PDF extraction endpoints
Handles single and bulk PDF uploads, job status queries, and results retrieval
"""

import os
import uuid
import shutil
from pathlib import Path
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Query, BackgroundTasks
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import ExtractionJob, ExtractedLineItem, JobStatus as DBJobStatus
from app.schemas import (
    ExtractionOptions, JobCreatedResponse, BulkJobCreatedResponse,
    ExtractionJobResponse, LineItemResponse, JobListResponse,
    PackInfo, OCRSummary, ExtractionSummary, ErrorResponse, JobStatus
)
from app.tasks.pdf_extraction_tasks import process_pdf_extraction, process_bulk_pdfs
from app.config import settings


router = APIRouter(prefix="/api/v1/extract", tags=["PDF Extraction"])

# Storage path for uploaded PDFs
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/tmp/pdf_uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def generate_job_id() -> str:
    """Generate unique job ID"""
    return f"job_{uuid.uuid4().hex[:12]}"


def save_upload_file(upload_file: UploadFile, job_id: str) -> Path:
    """Save uploaded file to disk"""
    file_ext = Path(upload_file.filename).suffix or ".pdf"
    file_path = UPLOAD_DIR / f"{job_id}{file_ext}"
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(upload_file.file, buffer)
    
    return file_path


@router.post("/upload", response_model=JobCreatedResponse)
async def upload_pdf(
    file: UploadFile = File(..., description="PDF file to process"),
    enable_agentic_lookup: bool = Query(default=True, description="Enable agentic UOM lookup"),
    supplier_name: Optional[str] = Query(default=None, description="Known supplier name"),
    db: Session = Depends(get_db)
):
    """
    Upload a single PDF for extraction
    
    Returns job_id which can be used to query status and results
    """
    
    # Validate file type
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(
            status_code=400,
            detail="Only PDF files are accepted"
        )
    
    # Generate job ID
    job_id = generate_job_id()
    
    try:
        # Save file
        file_path = save_upload_file(file, job_id)
        file_size = file_path.stat().st_size
        
        # Create job record
        job = ExtractionJob(
            job_id=job_id,
            file_name=file.filename,
            file_path=str(file_path),
            file_size=file_size,
            status=DBJobStatus.PENDING.value,
            options={
                "enable_agentic_lookup": enable_agentic_lookup,
                "supplier_name": supplier_name
            }
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        
        # Submit Celery task
        options = {
            "enable_agentic_lookup": enable_agentic_lookup,
            "supplier_name": supplier_name
        }
        
        task = process_pdf_extraction.delay(job_id, str(file_path), options)
        
        # Update job with task ID
        job.celery_task_id = task.id
        job.status = DBJobStatus.PROCESSING.value
        db.commit()
        
        return JobCreatedResponse(
            job_id=job_id,
            status=JobStatus.PROCESSING,
            message="PDF uploaded and processing started",
            celery_task_id=task.id
        )
        
    except Exception as e:
        # Cleanup on error
        if 'file_path' in locals() and file_path.exists():
            file_path.unlink()
        
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process upload: {str(e)}"
        )


@router.post("/bulk-upload", response_model=BulkJobCreatedResponse)
async def bulk_upload_pdfs(
    files: List[UploadFile] = File(..., description="Multiple PDF files to process"),
    enable_agentic_lookup: bool = Query(default=True, description="Enable agentic UOM lookup"),
    supplier_name: Optional[str] = Query(default=None, description="Known supplier name"),
    db: Session = Depends(get_db)
):
    """
    Upload multiple PDFs for batch extraction
    
    Returns batch_id and list of job_ids for tracking
    """
    
    # Validate all files are PDFs
    for file in files:
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(
                status_code=400,
                detail=f"Only PDF files are accepted. Invalid file: {file.filename}"
            )
    
    batch_id = f"batch_{uuid.uuid4().hex[:8]}"
    job_ids = []
    file_paths = []
    
    try:
        # Save all files and create job records
        for file in files:
            job_id = generate_job_id()
            job_ids.append(job_id)
            
            file_path = save_upload_file(file, job_id)
            file_paths.append(str(file_path))
            
            # Create job record
            job = ExtractionJob(
                job_id=job_id,
                file_name=file.filename,
                file_path=str(file_path),
                file_size=file_path.stat().st_size,
                status=DBJobStatus.PENDING.value,
                options={
                    "enable_agentic_lookup": enable_agentic_lookup,
                    "supplier_name": supplier_name,
                    "batch_id": batch_id
                }
            )
            db.add(job)
        
        db.commit()
        
        # Submit batch Celery task
        options = {
            "enable_agentic_lookup": enable_agentic_lookup,
            "supplier_name": supplier_name
        }
        
        task = process_bulk_pdfs.delay(job_ids, file_paths, options)
        
        # Update all jobs with processing status
        for job_id in job_ids:
            job = db.query(ExtractionJob).filter(ExtractionJob.job_id == job_id).first()
            if job:
                job.status = DBJobStatus.PROCESSING.value
                job.celery_task_id = task.id
        
        db.commit()
        
        return BulkJobCreatedResponse(
            batch_id=batch_id,
            job_ids=job_ids,
            total_files=len(files),
            status="processing",
            message=f"Batch upload started with {len(files)} files"
        )
        
    except Exception as e:
        # Cleanup on error
        for path in file_paths:
            if Path(path).exists():
                Path(path).unlink()
        
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process bulk upload: {str(e)}"
        )


@router.get("/jobs/{job_id}", response_model=ExtractionJobResponse)
async def get_job_status(
    job_id: str,
    include_line_items: bool = Query(default=True, description="Include extracted line items"),
    db: Session = Depends(get_db)
):
    """
    Get extraction job status and results
    
    Returns complete extraction results including all line items
    """
    
    job = db.query(ExtractionJob).filter(ExtractionJob.job_id == job_id).first()
    
    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"Job not found: {job_id}"
        )
    
    # Build response
    response = ExtractionJobResponse(
        job_id=job.job_id,
        status=JobStatus(job.status),
        file_name=job.file_name,
        file_path=job.file_path,
        processing_time=job.processing_time,
        total_pages=job.total_pages,
        total_line_items=job.total_line_items,
        escalation_count=job.escalation_count,
        ocr_method=job.ocr_method,
        ocr_confidence=job.ocr_confidence,
        error_message=job.error_message,
        created_at=job.created_at,
        completed_at=job.completed_at
    )
    
    # Include line items if requested
    if include_line_items and job.status == DBJobStatus.COMPLETED.value:
        line_items = db.query(ExtractedLineItem).filter(
            ExtractedLineItem.job_id == job.job_id
        ).all()
        
        response.line_items = [
            LineItemResponse(
                supplier_name=item.supplier_name,
                item_description=item.item_description,
                manufacturer_part_number=item.manufacturer_part_number,
                original_uom=item.original_uom,
                detected_pack_quantity=item.detected_pack_quantity,
                canonical_base_uom=item.canonical_base_uom,
                price_per_base_unit=item.price_per_base_unit,
                confidence_score=item.confidence_score,
                escalation_flag=item.escalation_flag,
                escalation_reasons=item.escalation_reasons or [],
                hsn_code=item.hsn_code,
                sac_code=item.sac_code,
                quantity=item.quantity,
                unit_price=item.unit_price,
                total_amount=item.total_amount,
                raw_line=item.raw_line,
                pack_info=PackInfo(**item.pack_info) if item.pack_info else None
            )
            for item in line_items
        ]
        
        # Build summary
        if line_items:
            response.summary = ExtractionSummary(
                items_with_uom=sum(1 for item in line_items if item.original_uom),
                items_with_mpn=sum(1 for item in line_items if item.manufacturer_part_number),
                items_requiring_escalation=sum(1 for item in line_items if item.escalation_flag),
                avg_confidence=sum(item.confidence_score for item in line_items) / len(line_items),
                agentic_lookup_used=job.options.get("enable_agentic_lookup", False) if job.options else False
            )
    
    return response


@router.get("/jobs", response_model=JobListResponse)
async def list_jobs(
    status: Optional[str] = Query(default=None, description="Filter by status"),
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db)
):
    """
    List all extraction jobs with pagination
    """
    
    query = db.query(ExtractionJob)
    
    if status:
        query = query.filter(ExtractionJob.status == status)
    
    total = query.count()
    
    jobs = query.order_by(ExtractionJob.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()
    
    return JobListResponse(
        total=total,
        page=page,
        page_size=page_size,
        jobs=[
            ExtractionJobResponse(
                job_id=job.job_id,
                status=JobStatus(job.status),
                file_name=job.file_name,
                processing_time=job.processing_time,
                total_line_items=job.total_line_items,
                escalation_count=job.escalation_count,
                created_at=job.created_at,
                completed_at=job.completed_at
            )
            for job in jobs
        ]
    )


@router.delete("/jobs/{job_id}")
async def delete_job(
    job_id: str,
    db: Session = Depends(get_db)
):
    """
    Delete an extraction job and its results
    """
    
    job = db.query(ExtractionJob).filter(ExtractionJob.job_id == job_id).first()
    
    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"Job not found: {job_id}"
        )
    
    # Delete file if exists
    if job.file_path and Path(job.file_path).exists():
        Path(job.file_path).unlink()
    
    # Delete job (cascade deletes line items)
    db.delete(job)
    db.commit()
    
    return {"message": f"Job {job_id} deleted successfully"}


@router.get("/jobs/{job_id}/line-items", response_model=List[LineItemResponse])
async def get_job_line_items(
    job_id: str,
    escalation_only: bool = Query(default=False, description="Only return items requiring escalation"),
    min_confidence: float = Query(default=0.0, ge=0.0, le=1.0, description="Minimum confidence filter"),
    db: Session = Depends(get_db)
):
    """
    Get line items for a specific job with filtering options
    """
    
    job = db.query(ExtractionJob).filter(ExtractionJob.job_id == job_id).first()
    
    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"Job not found: {job_id}"
        )
    
    query = db.query(ExtractedLineItem).filter(ExtractedLineItem.job_id == job.job_id)
    
    if escalation_only:
        query = query.filter(ExtractedLineItem.escalation_flag == True)
    
    if min_confidence > 0:
        query = query.filter(ExtractedLineItem.confidence_score >= min_confidence)
    
    line_items = query.all()
    
    return [
        LineItemResponse(
            supplier_name=item.supplier_name,
            item_description=item.item_description,
            manufacturer_part_number=item.manufacturer_part_number,
            original_uom=item.original_uom,
            detected_pack_quantity=item.detected_pack_quantity,
            canonical_base_uom=item.canonical_base_uom,
            price_per_base_unit=item.price_per_base_unit,
            confidence_score=item.confidence_score,
            escalation_flag=item.escalation_flag,
            escalation_reasons=item.escalation_reasons or [],
            hsn_code=item.hsn_code,
            sac_code=item.sac_code,
            quantity=item.quantity,
            unit_price=item.unit_price,
            total_amount=item.total_amount,
            raw_line=item.raw_line,
            pack_info=PackInfo(**item.pack_info) if item.pack_info else None
        )
        for item in line_items
    ]
