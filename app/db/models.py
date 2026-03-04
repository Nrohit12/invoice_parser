"""
Database models for PDF Extraction Pipeline
Stores extraction jobs, line items, and lookup audit trails
"""

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Float, Boolean,
    ForeignKey, JSON, Enum as SQLEnum, Index
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.database import Base
import enum


class JobStatus(str, enum.Enum):
    """Extraction job status"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


class OCRMethod(str, enum.Enum):
    """OCR method used"""
    TESSERACT_LAYOUT = "tesseract_layout"
    TESSERACT_MULTI_PSM = "tesseract_multi_psm"
    TESSERACT_RAW = "tesseract_raw"
    PADDLE_OCR = "paddle_ocr"
    OPENAI_VISION = "openai_vision"


class LookupSource(str, enum.Enum):
    """Source of UOM resolution"""
    EXTRACTED = "extracted"
    PATTERN_MATCHED = "pattern_matched"
    ONLINE_LOOKUP = "online_lookup"
    LLM_INFERRED = "llm_inferred"
    MANUAL = "manual"


class ExtractionJob(Base):
    """
    Main extraction job table
    Tracks PDF processing status and metadata
    """
    __tablename__ = "extraction_jobs"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String(64), unique=True, nullable=False, index=True)
    
    # File information
    file_name = Column(String(255), nullable=False)
    file_path = Column(Text, nullable=False)
    file_size = Column(Integer, nullable=True)
    
    # Processing status
    status = Column(String(20), default=JobStatus.PENDING.value, nullable=False)
    celery_task_id = Column(String(64), nullable=True, index=True)
    
    # Processing metadata
    total_pages = Column(Integer, nullable=True)
    processing_time = Column(Float, nullable=True)
    ocr_method = Column(String(30), nullable=True)
    ocr_confidence = Column(Float, nullable=True)
    
    # Results summary
    total_line_items = Column(Integer, default=0)
    escalation_count = Column(Integer, default=0)
    
    # Error handling
    error_message = Column(Text, nullable=True)
    
    # Options used
    options = Column(JSON, nullable=True)
    
    # Raw OCR text (for debugging)
    raw_ocr_text = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    line_items = relationship("ExtractedLineItem", back_populates="job", cascade="all, delete-orphan")
    
    # Indexes
    __table_args__ = (
        Index('ix_extraction_jobs_status_created', 'status', 'created_at'),
    )

    def __repr__(self):
        return f"<ExtractionJob(job_id={self.job_id}, status={self.status})>"


class ExtractedLineItem(Base):
    """
    Extracted line item with all required fields
    Stores per-line-item results with UOM normalization
    """
    __tablename__ = "extracted_line_items"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String(64), ForeignKey("extraction_jobs.job_id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Core fields (as per requirements)
    supplier_name = Column(String(255), nullable=True)
    item_description = Column(Text, nullable=True)
    manufacturer_part_number = Column(String(100), nullable=True, index=True)
    
    # UOM fields
    original_uom = Column(String(20), nullable=True)
    detected_pack_quantity = Column(Integer, nullable=True)
    canonical_base_uom = Column(String(10), default="EA")
    
    # Pricing
    price_per_base_unit = Column(Float, nullable=True)
    unit_price = Column(Float, nullable=True)
    total_amount = Column(Float, nullable=True)
    quantity = Column(Float, nullable=True)
    
    # Confidence and escalation
    confidence_score = Column(Float, default=0.0)
    escalation_flag = Column(Boolean, default=False)
    escalation_reasons = Column(JSON, nullable=True)
    
    # Additional metadata
    hsn_code = Column(String(20), nullable=True)
    sac_code = Column(String(20), nullable=True)
    raw_line = Column(Text, nullable=True)
    
    # Pack info (JSON for flexibility)
    pack_info = Column(JSON, nullable=True)
    
    # Lookup metadata
    lookup_source = Column(String(30), nullable=True)
    lookup_confidence = Column(Float, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    job = relationship("ExtractionJob", back_populates="line_items")
    
    # Indexes
    __table_args__ = (
        Index('ix_line_items_job_confidence', 'job_id', 'confidence_score'),
        Index('ix_line_items_escalation', 'escalation_flag'),
    )

    def __repr__(self):
        return f"<ExtractedLineItem(id={self.id}, description={self.item_description[:30] if self.item_description else 'N/A'})>"


class LookupAuditLog(Base):
    """
    Audit trail for agentic lookups
    Tracks all lookup attempts for transparency
    """
    __tablename__ = "lookup_audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    line_item_id = Column(Integer, ForeignKey("extracted_line_items.id", ondelete="CASCADE"), nullable=False)
    
    # Lookup details
    lookup_source = Column(String(30), nullable=False)
    lookup_query = Column(Text, nullable=True)
    
    # Results
    success = Column(Boolean, default=False)
    resolved_uom = Column(String(20), nullable=True)
    resolved_pack_quantity = Column(Integer, nullable=True)
    confidence = Column(Float, nullable=True)
    reasoning = Column(Text, nullable=True)
    
    # Error handling
    error_message = Column(Text, nullable=True)
    
    # Raw response (for debugging)
    raw_response = Column(JSON, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<LookupAuditLog(id={self.id}, source={self.lookup_source}, success={self.success})>"


class FileWatcherState(Base):
    """
    Tracks file watcher state for automatic PDF ingestion
    Prevents duplicate processing
    """
    __tablename__ = "file_watcher_state"

    id = Column(Integer, primary_key=True, index=True)
    file_path = Column(Text, unique=True, nullable=False)
    file_hash = Column(String(64), nullable=True)
    
    # Processing status
    processed = Column(Boolean, default=False)
    job_id = Column(String(64), nullable=True)
    
    # Timestamps
    discovered_at = Column(DateTime(timezone=True), server_default=func.now())
    processed_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<FileWatcherState(file_path={self.file_path}, processed={self.processed})>"
