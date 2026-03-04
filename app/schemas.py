"""
Pydantic schemas for API request/response validation
Defines structured output format for line items and extraction results
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class JobStatus(str, Enum):
    """Extraction job status"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


class UOMType(str, Enum):
    """Standard Unit of Measure types"""
    EACH = "EA"
    CASE = "CS"
    PACK = "PK"
    BOX = "BX"
    DOZEN = "DZ"
    PAIR = "PR"
    SET = "SET"
    ROLL = "RL"
    SHEET = "SH"
    METER = "M"
    KILOGRAM = "KG"
    LITER = "L"
    UNKNOWN = "UNK"


class LookupSource(str, Enum):
    """Source of UOM resolution"""
    EXTRACTED = "extracted"
    PATTERN_MATCHED = "pattern_matched"
    ONLINE_LOOKUP = "online_lookup"
    LLM_INFERRED = "llm_inferred"
    MANUAL = "manual"


class EscalationReason(str, Enum):
    """Reasons for escalation"""
    MISSING_UOM = "missing_uom"
    AMBIGUOUS_PACK = "ambiguous_pack"
    LOW_CONFIDENCE = "low_confidence"
    CONFLICTING_DATA = "conflicting_data"
    UNKNOWN_SUPPLIER = "unknown_supplier"
    INVALID_PRICE = "invalid_price"


# ============================================
# REQUEST SCHEMAS
# ============================================

class ExtractionOptions(BaseModel):
    """Options for PDF extraction"""
    enable_agentic_lookup: bool = Field(default=True, description="Enable agentic lookup for missing UOM")
    supplier_name: Optional[str] = Field(default=None, description="Known supplier name")
    confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0, description="Minimum confidence threshold")
    escalate_missing_uom: bool = Field(default=True, description="Escalate items with missing UOM")


class PDFUploadRequest(BaseModel):
    """Request for single PDF upload"""
    options: Optional[ExtractionOptions] = None


class BulkUploadRequest(BaseModel):
    """Request for bulk PDF upload"""
    options: Optional[ExtractionOptions] = None


# ============================================
# RESPONSE SCHEMAS
# ============================================

class PackInfo(BaseModel):
    """Pack quantity information"""
    quantity: int = Field(description="Number of base units per pack")
    unit: str = Field(description="Unit of measure code")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in pack detection")
    source: str = Field(description="Source of pack information")


class LineItemResponse(BaseModel):
    """
    Structured line item output as per requirements
    Each line item includes all required fields
    """
    # Core fields (as per requirements)
    supplier_name: Optional[str] = Field(default=None, description="Extracted + normalized supplier name")
    item_description: Optional[str] = Field(default=None, description="Cleaned item description")
    manufacturer_part_number: Optional[str] = Field(default=None, description="MPN if extractable, otherwise null")
    original_uom: Optional[str] = Field(default=None, description="Original UOM if present")
    detected_pack_quantity: Optional[int] = Field(default=None, description="Detected pack quantity if applicable")
    canonical_base_uom: str = Field(default="EA", description="Normalized to EA (each)")
    price_per_base_unit: Optional[float] = Field(default=None, description="Price per base unit")
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Overall confidence score")
    escalation_flag: bool = Field(default=False, description="True if requires human review")
    
    # Additional metadata
    escalation_reasons: List[str] = Field(default_factory=list, description="Reasons for escalation")
    hsn_code: Optional[str] = Field(default=None, description="HSN code if detected")
    sac_code: Optional[str] = Field(default=None, description="SAC code if detected")
    quantity: Optional[float] = Field(default=None, description="Quantity ordered")
    unit_price: Optional[float] = Field(default=None, description="Unit price as stated")
    total_amount: Optional[float] = Field(default=None, description="Total line amount")
    raw_line: Optional[str] = Field(default=None, description="Raw OCR line for debugging")
    pack_info: Optional[PackInfo] = Field(default=None, description="Detailed pack information")

    class Config:
        from_attributes = True


class OCRSummary(BaseModel):
    """OCR processing summary"""
    total_pages: int
    successful_pages: int
    avg_confidence: float
    methods_used: List[str]


class ExtractionSummary(BaseModel):
    """Extraction results summary"""
    items_with_uom: int
    items_with_mpn: int
    items_requiring_escalation: int
    avg_confidence: float
    agentic_lookup_used: bool


class ExtractionJobResponse(BaseModel):
    """
    Complete extraction job response
    Returned when querying job status
    """
    job_id: str = Field(description="Unique job identifier")
    status: JobStatus = Field(description="Current job status")
    
    # File info
    file_name: Optional[str] = None
    file_path: Optional[str] = None
    
    # Processing metadata
    processing_time: Optional[float] = Field(default=None, description="Processing time in seconds")
    total_pages: Optional[int] = None
    total_line_items: int = 0
    escalation_count: int = 0
    
    # OCR info
    ocr_method: Optional[str] = None
    ocr_confidence: Optional[float] = None
    ocr_summary: Optional[OCRSummary] = None
    
    # Results
    line_items: List[LineItemResponse] = Field(default_factory=list)
    summary: Optional[ExtractionSummary] = None
    
    # Error handling
    error_message: Optional[str] = None
    
    # Timestamps
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class JobCreatedResponse(BaseModel):
    """Response when job is created"""
    job_id: str
    status: JobStatus = JobStatus.PENDING
    message: str = "Job created successfully"
    celery_task_id: Optional[str] = None


class BulkJobCreatedResponse(BaseModel):
    """Response when bulk jobs are created"""
    batch_id: str
    job_ids: List[str]
    total_files: int
    status: str = "processing"
    message: str = "Bulk jobs created successfully"


class JobListResponse(BaseModel):
    """Response for listing jobs"""
    total: int
    page: int
    page_size: int
    jobs: List[ExtractionJobResponse]


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    version: str
    services: Dict[str, str]


class ErrorResponse(BaseModel):
    """Standard error response"""
    error: str
    detail: Optional[str] = None
    job_id: Optional[str] = None
