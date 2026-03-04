# PDF Invoice Extraction Pipeline

An end-to-end system for extracting structured line items from invoice PDFs with OCR, UOM normalization, and agentic lookup capabilities.

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Processing Flow](#processing-flow)
- [Quick Start](#quick-start)
- [CLI Usage](#cli-usage)
- [API Endpoints](#api-endpoints)
- [Output Format](#output-format)
- [Core Components](#core-components)
- [Configuration](#configuration)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)

---

## Features

| Feature | Description |
|---------|-------------|
| **OCR Pipeline** | Multi-method fallback: Tesseract → PaddleOCR → OpenAI Vision |
| **Line Item Extraction** | Structured extraction with regex-based parsing |
| **UOM Normalization** | Handles "25/CS", "PK10", "1000 EA" patterns, normalizes to EA |
| **Agentic Lookup** | LLM-based resolution for missing UOM/pack quantities |
| **Confidence Scoring** | Transparent 0-1 scoring with escalation flags |
| **Async Processing** | Celery + Redis for background PDF processing |
| **File Watcher** | Automatic PDF ingestion from watched directories |
| **REST API** | FastAPI endpoints for upload, status, and results |
| **CLI Interface** | Command-line tool for local processing |
| **Database Persistence** | PostgreSQL storage for jobs and line items |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           PDF INVOICE EXTRACTION PIPELINE                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                   │
│  │   INPUT      │    │   PROCESS    │    │   OUTPUT     │                   │
│  ├──────────────┤    ├──────────────┤    ├──────────────┤                   │
│  │ • PDF Upload │───▶│ • OCR        │───▶│ • JSON       │                   │
│  │ • CLI        │    │ • Extraction │    │ • Database   │                   │
│  │ • File Watch │    │ • Lookup     │    │ • API        │                   │
│  └──────────────┘    └──────────────┘    └──────────────┘                   │
│                                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                              SERVICES LAYER                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐              │
│  │   OCR Service   │  │ Line Extractor  │  │ Agentic Lookup  │              │
│  ├─────────────────┤  ├─────────────────┤  ├─────────────────┤              │
│  │ • Tesseract     │  │ • UOM Detection │  │ • Online Lookup │              │
│  │ • PaddleOCR     │  │ • MPN Extract   │  │ • LLM Inference │              │
│  │ • OpenAI Vision │  │ • Pack Parsing  │  │ • Confidence    │              │
│  │ • Preprocessing │  │ • Normalization │  │ • Escalation    │              │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘              │
│                                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                            INFRASTRUCTURE                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐           │
│  │ FastAPI │  │ Celery  │  │  Redis  │  │Postgres │  │ Flower  │           │
│  │  :8000  │  │ Worker  │  │  :6379  │  │  :5432  │  │  :5555  │           │
│  └─────────┘  └─────────┘  └─────────┘  └─────────┘  └─────────┘           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Project Structure

```
extractor/
├── app/
│   ├── main.py                      # FastAPI application entry point
│   ├── celery_app.py                # Celery configuration
│   ├── config.py                    # Settings and environment config
│   ├── schemas.py                   # Pydantic request/response schemas
│   ├── db/
│   │   ├── database.py              # SQLAlchemy database connection
│   │   └── models.py                # Database models (ExtractionJob, ExtractedLineItem)
│   ├── routers/
│   │   └── extraction.py            # PDF extraction API endpoints
│   ├── services/
│   │   ├── ocr_service.py           # OCR pipeline with fallback chain
│   │   ├── line_item_extractor.py   # Line item & UOM extraction
│   │   ├── agentic_lookup.py        # LLM-based UOM resolution
│   │   └── file_watcher.py          # Automatic PDF ingestion
│   ├── tasks/
│   │   └── pdf_extraction_tasks.py  # Celery async PDF processing
│   └── migrations/                  # Alembic database migrations
├── tests/                           # Comprehensive test suite
│   ├── test_ocr_service.py
│   ├── test_line_item_extractor.py
│   ├── test_agentic_lookup.py
│   └── test_api_endpoints.py
├── cli.py                           # CLI entry point
├── docker-compose.yml               # Docker services orchestration
├── Dockerfile                       # Docker image definition
├── requirements.txt                 # Python dependencies
├── .env.example                     # Environment variables template
└── README.md                        # This documentation
```

---

## Processing Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              EXTRACTION PIPELINE                             │
└─────────────────────────────────────────────────────────────────────────────┘

    ┌─────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
    │  PDF    │────▶│  PDF to     │────▶│    OCR      │────▶│   Line      │
    │  Input  │     │  Images     │     │  Pipeline   │     │  Extraction │
    └─────────┘     └─────────────┘     └─────────────┘     └──────┬──────┘
                                                                    │
                                                                    ▼
    ┌─────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
    │  JSON   │◀────│  Database   │◀────│  Agentic    │◀────│    UOM      │
    │  Output │     │  Storage    │     │  Lookup     │     │  Detection  │
    └─────────┘     └─────────────┘     └─────────────┘     └─────────────┘
```

### Step-by-Step Flow

1. **PDF Input** → PDF uploaded via API, CLI, or file watcher
2. **PDF to Images** → PyMuPDF converts each page to high-DPI image (144 DPI)
3. **OCR Pipeline** → Multi-method fallback extracts text:
   - Tesseract (layout-aware) → Tesseract (multi-PSM) → PaddleOCR → OpenAI Vision
4. **Line Extraction** → Regex patterns identify line items, amounts, quantities
5. **UOM Detection** → Pattern matching for pack expressions ("25/CS", "PK10")
6. **Agentic Lookup** → If UOM missing/uncertain:
   - Online product database lookup (simulated)
   - LLM inference with structured output constraints
7. **Database Storage** → Results persisted to PostgreSQL
8. **JSON Output** → Structured response via API or file

### Agentic Lookup Decision Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    AGENTIC LOOKUP FLOW                          │
└─────────────────────────────────────────────────────────────────┘

    Has UOM with confidence > 0.7?
           │
    ┌──────┴──────┐
    │ YES         │ NO
    ▼             ▼
  ┌─────┐    ┌─────────────────┐
  │SKIP │    │ Online Lookup   │
  │     │    │ (Product DB)    │
  └─────┘    └────────┬────────┘
                      │
              Success with conf > 0.6?
                      │
               ┌──────┴──────┐
               │ YES         │ NO
               ▼             ▼
           ┌─────┐    ┌─────────────────┐
           │DONE │    │ LLM Inference   │
           │     │    │ (gpt-5-nano)         │
           └─────┘    └────────┬────────┘
                               │
                       Confidence > 0.5?
                               │
                        ┌──────┴──────┐
                        │ YES         │ NO
                        ▼             ▼
                    ┌─────┐    ┌─────────────┐
                    │DONE │    │ ESCALATE    │
                    │     │    │ (Flag item) │
                    └─────┘    └─────────────┘
```

### Safety Features

- **No Hallucination**: Low confidence triggers escalation, not guessing
- **Structured LLM Output**: OpenAI function calling with enum constraints
- **Confidence Thresholds**: 
  - Accept if confidence > 0.7
  - Escalate if confidence < 0.5
- **Audit Trail**: All lookup attempts logged for review

---

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Python 3.11+ (for local development)
- Tesseract OCR (for local development without Docker)

### Setup with Docker (Recommended)

1. **Create environment file**
   ```bash
   cp .env.example .env
   ```

2. **Add OpenAI API key (optional, for agentic lookup)**
   ```bash
   echo "OPENAI_API_KEY=your-api-key" >> .env
   ```

3. **Start all services**
   ```bash
   docker-compose up --build
   ```

4. **Access the services**
   - FastAPI API: http://localhost:8000
   - API Documentation: http://localhost:8000/docs
   - Flower (Celery monitoring): http://localhost:5555

### Local Development (Without Docker)

1. **Install system dependencies**
   ```bash
   # macOS
   brew install tesseract postgresql redis
   
   # Ubuntu
   sudo apt-get install tesseract-ocr libtesseract-dev postgresql redis-server
   ```

2. **Install Python dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Start services**
   ```bash
   # Terminal 1: Start FastAPI
   uvicorn app.main:app --reload
   
   # Terminal 2: Start Celery worker
   celery -A app.celery_app worker --loglevel=info
   ```

---

## CLI Usage

The CLI provides a simple interface for local PDF processing without requiring Docker.

### Commands Overview

| Command | Description |
|---------|-------------|
| `process` | Process a single PDF file |
| `batch` | Process all PDFs in a directory |
| `watch` | Watch directory for new PDFs (auto-process) |

### Process Single PDF

```bash
# Basic usage
python cli.py process invoice.pdf

# With output file
python cli.py process invoice.pdf -o output.json

# Verbose mode
python cli.py process invoice.pdf -o output.json -v

# Without agentic lookup
python cli.py process invoice.pdf --no-lookup

# With known supplier
python cli.py process invoice.pdf --supplier "ABC Corp"
```

### Batch Process Directory

```bash
# Process all PDFs in a folder
python cli.py batch ./invoices/ ./output/

# With verbose output
python cli.py batch ./invoices/ ./output/ -v

# Without agentic lookup (faster)
python cli.py batch ./invoices/ ./output/ --no-lookup
```

### Watch Directory for New PDFs

```bash
# Watch and auto-process new PDFs
python cli.py watch ./input_folder/

# With custom output directory
python cli.py watch ./input_folder/ -o ./processed/

# Verbose mode
python cli.py watch ./input_folder/ -v
```

### CLI Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--output` | `-o` | Output JSON file/directory path |
| `--verbose` | `-v` | Enable verbose logging |
| `--no-lookup` | | Disable agentic lookup (faster, less accurate) |
| `--supplier` | | Known supplier name for better extraction |

### Example Output

```bash
$ python cli.py process invoice.pdf -v

2024-03-04 20:00:00 - INFO - Processing: invoice.pdf
2024-03-04 20:00:01 - INFO - Converting PDF to images...
2024-03-04 20:00:02 - INFO - Converted 2 pages
2024-03-04 20:00:02 - INFO - Running OCR...
2024-03-04 20:00:05 - INFO - OCR complete. Total text length: 3456 chars
2024-03-04 20:00:05 - INFO - Extracting line items...
2024-03-04 20:00:06 - INFO - Extracted 15 line items
2024-03-04 20:00:06 - INFO - Running agentic lookup for missing UOM...
2024-03-04 20:00:08 - INFO - Agentic lookup complete

==================================================
EXTRACTION SUMMARY
==================================================
File: invoice.pdf
Pages: 2
Line Items: 15
Items with UOM: 12
Items with MPN: 8
Escalations: 3
Avg Confidence: 0.78
Processing Time: 8.2s
==================================================
```

---

## API Endpoints

### Endpoints Overview

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/extract/upload` | Upload single PDF for extraction |
| `POST` | `/api/v1/extract/bulk-upload` | Upload multiple PDFs |
| `GET` | `/api/v1/extract/jobs/{job_id}` | Get job status and results |
| `GET` | `/api/v1/extract/jobs` | List all jobs |
| `GET` | `/api/v1/extract/jobs/{job_id}/line-items` | Get line items with filters |
| `DELETE` | `/api/v1/extract/jobs/{job_id}` | Delete job |
| `GET` | `/` | API information |
| `GET` | `/health` | Health check for all services |

### Upload PDF

```bash
curl -X POST "http://localhost:8000/api/v1/extract/upload" \
     -F "file=@invoice.pdf" \
     -F "enable_agentic_lookup=true" \
     -F "supplier_name=ABC Corp"
```

**Response:**
```json
{
  "job_id": "job_a1b2c3d4e5f6",
  "status": "processing",
  "message": "PDF uploaded successfully. Processing started.",
  "created_at": "2024-03-04T20:00:00Z"
}
```

### Check Job Status

```bash
curl "http://localhost:8000/api/v1/extract/jobs/job_a1b2c3d4e5f6"
```

**Response:**
```json
{
  "job_id": "job_a1b2c3d4e5f6",
  "status": "completed",
  "file_name": "invoice.pdf",
  "total_pages": 2,
  "total_line_items": 15,
  "escalation_count": 3,
  "processing_time": 8.2,
  "created_at": "2024-03-04T20:00:00Z",
  "completed_at": "2024-03-04T20:00:08Z"
}
```

### Get Line Items

```bash
# All line items
curl "http://localhost:8000/api/v1/extract/jobs/job_a1b2c3d4e5f6/line-items"

# Only escalated items
curl "http://localhost:8000/api/v1/extract/jobs/job_a1b2c3d4e5f6/line-items?escalation_only=true"

# Filter by minimum confidence
curl "http://localhost:8000/api/v1/extract/jobs/job_a1b2c3d4e5f6/line-items?min_confidence=0.7"
```

### List All Jobs

```bash
# All jobs
curl "http://localhost:8000/api/v1/extract/jobs"

# Filter by status
curl "http://localhost:8000/api/v1/extract/jobs?status=completed"

# Pagination
curl "http://localhost:8000/api/v1/extract/jobs?skip=0&limit=10"
```

### Delete Job

```bash
curl -X DELETE "http://localhost:8000/api/v1/extract/jobs/job_a1b2c3d4e5f6"
```

### Health Check

```bash
curl "http://localhost:8000/health"
```

**Response:**
```json
{
  "status": "healthy",
  "database": "connected",
  "redis": "connected",
  "celery": "connected"
}
```

---

## Output Format

### Line Item Schema

Each extracted line item includes the following fields:

```json
{
  "supplier_name": "ABC Corp",
  "item_description": "Widget Pro 2000 - Industrial Grade",
  "manufacturer_part_number": "WP-2000-X",
  "original_uom": "CS",
  "detected_pack_quantity": 25,
  "canonical_base_uom": "EA",
  "price_per_base_unit": 4.50,
  "confidence_score": 0.92,
  "escalation_flag": false,
  "escalation_reasons": [],
  "hsn_code": "84719000",
  "sac_code": null,
  "quantity": 10,
  "unit_price": 112.50,
  "total_amount": 1125.00,
  "raw_line": "10 CS Widget Pro 2000 WP-2000-X @ 112.50 = 1125.00",
  "pack_info": {
    "quantity": 25,
    "unit": "CS",
    "confidence": 0.95,
    "source": "pattern_matched"
  }
}
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| `supplier_name` | string | Extracted and normalized supplier name |
| `item_description` | string | Cleaned item description |
| `manufacturer_part_number` | string | MPN if extractable, null otherwise |
| `original_uom` | string | Original UOM as found in document |
| `detected_pack_quantity` | integer | Number of base units per pack |
| `canonical_base_uom` | string | Always "EA" (each) - normalized base unit |
| `price_per_base_unit` | float | Calculated price per single unit |
| `confidence_score` | float | Overall confidence (0.0 - 1.0) |
| `escalation_flag` | boolean | True if requires human review |
| `escalation_reasons` | array | List of reasons for escalation |
| `hsn_code` | string | HSN code if detected |
| `sac_code` | string | SAC code if detected |
| `quantity` | float | Quantity ordered |
| `unit_price` | float | Unit price as stated on invoice |
| `total_amount` | float | Total line amount |
| `raw_line` | string | Raw OCR text for debugging |
| `pack_info` | object | Detailed pack information |

### Escalation Reasons

| Reason | Description |
|--------|-------------|
| `missing_uom` | No UOM detected in line item |
| `ambiguous_pack` | Multiple possible pack interpretations |
| `low_confidence` | Overall confidence below threshold |
| `conflicting_data` | Inconsistent values detected |
| `unknown_supplier` | Supplier not recognized |
| `invalid_price` | Price calculation doesn't match |

---

## Core Components

### OCR Pipeline

The OCR service uses a multi-method fallback chain for robust text extraction:

```
┌─────────────────────────────────────────────────────────────────┐
│                       OCR FALLBACK CHAIN                        │
└─────────────────────────────────────────────────────────────────┘

  ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
  │ 1. Tesseract    │────▶│ 2. Tesseract    │────▶│ 3. PaddleOCR    │
  │    Layout-aware │     │    Multi-PSM    │     │    (if avail)   │
  └─────────────────┘     └─────────────────┘     └─────────────────┘
           │                      │                       │
           │ conf > 0.7?          │ conf > 0.6?           │ conf > 0.5?
           │                      │                       │
           ▼                      ▼                       ▼
       ┌──────┐              ┌──────┐               ┌──────┐
       │ DONE │              │ DONE │               │ DONE │
       └──────┘              └──────┘               └──────┘
                                                         │
                                                         │ NO
                                                         ▼
                              ┌─────────────────┐     ┌─────────────────┐
                              │ 5. Tesseract    │◀────│ 4. OpenAI       │
                              │    Raw          │     │    Vision       │
                              └─────────────────┘     └─────────────────┘
```

**Methods:**
1. **Tesseract Layout-aware** - Best for structured invoices with tables
2. **Tesseract Multi-PSM** - Tries multiple page segmentation modes
3. **PaddleOCR** - Alternative engine, good for mixed layouts
4. **OpenAI Vision** - gpt-5-nano Vision for difficult documents (requires API key)
5. **Tesseract Raw** - Minimal preprocessing fallback

### UOM Normalization

Handles various pack expressions and normalizes to canonical base unit "EA":

| Pattern | Example | Interpretation |
|---------|---------|----------------|
| `{qty}/{uom}` | `25/CS` | 25 units per case |
| `{uom}{qty}` | `PK10` | Pack of 10 |
| `{qty} {uom}` | `1000 EA` | 1000 each |
| `{uom}/{qty}` | `BX/100` | Box of 100 |
| `{uom}` | `DZ` | Dozen (12 units) |

**Supported UOM Codes:**

| Code | Full Name | Base Units |
|------|-----------|------------|
| EA | Each | 1 |
| CS | Case | Variable |
| PK | Pack | Variable |
| BX | Box | Variable |
| DZ | Dozen | 12 |
| PR | Pair | 2 |
| SET | Set | Variable |
| RL | Roll | Variable |
| SH | Sheet | 1 |
| M | Meter | 1 |
| KG | Kilogram | 1 |
| L | Liter | 1 |

### Agentic Lookup Service

When UOM is missing or uncertain, the agentic lookup service attempts resolution:

**Lookup Methods:**
1. **Online Product Database** - Simulated lookup based on MPN/description patterns
2. **LLM Inference** - gpt-5-nano with structured output constraints

**LLM Prompt Structure:**
```
Analyze this invoice line item and determine the unit of measure (UOM) and pack quantity:

Item Description: {description}
Part Number: {mpn}
Supplier: {supplier}

Instructions:
1. Determine the most likely unit of measure (EA, CS, PK, BX, DZ, etc.)
2. Estimate pack quantity (how many base units per pack)
3. Provide confidence score (0.0-1.0) based on available information
4. If uncertain, use lower confidence and explain why
5. Do NOT hallucinate - if information is insufficient, use low confidence
```

**Safety Features:**
- **No Hallucination**: Low confidence triggers escalation, not guessing
- **Structured Output**: OpenAI function calling with enum constraints
- **Confidence Thresholds**: Accept > 0.7, Escalate < 0.5
- **Audit Trail**: All lookup attempts logged for review

---

## Testing

### Run Test Suite

```bash
# All tests
pytest tests/ -v

# With coverage report
pytest tests/ --cov=app --cov-report=html

# Specific test file
pytest tests/test_line_item_extractor.py -v

# Run tests in Docker
docker exec fastapi_api pytest tests/ -v
```

### Test Files

| File | Coverage |
|------|----------|
| `test_ocr_service.py` | OCR pipeline, preprocessing, fallback chain |
| `test_line_item_extractor.py` | UOM detection, MPN extraction, normalization |
| `test_agentic_lookup.py` | Online lookup, LLM inference, escalation |
| `test_api_endpoints.py` | API routes, request/response validation |

### End-to-End Testing

```bash
# 1. Start services
docker-compose up -d

# 2. Upload a PDF
JOB_ID=$(curl -s -X POST "http://localhost:8000/api/v1/extract/upload" \
     -F "file=@invoice.pdf" | jq -r '.job_id')

# 3. Wait for processing
sleep 10

# 4. Check status
curl -s "http://localhost:8000/api/v1/extract/jobs/$JOB_ID" | jq '.status'

# 5. Get line items
curl -s "http://localhost:8000/api/v1/extract/jobs/$JOB_ID/line-items" | jq '.'
```

---

## Configuration

### Environment Variables

All configuration is managed through `.env` file:

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://postgres:postgres@postgres:5432/fastapi_db` |
| `REDIS_HOST` | Redis host | `redis` |
| `REDIS_PORT` | Redis port | `6379` |
| `CELERY_BROKER_URL` | Celery broker URL | `redis://redis:6379/0` |
| `CELERY_RESULT_BACKEND` | Celery result backend | `redis://redis:6379/0` |
| `OPENAI_API_KEY` | OpenAI API key (optional) | - |
| `API_HOST` | FastAPI host | `0.0.0.0` |
| `API_PORT` | FastAPI port | `8000` |
| `DEBUG` | Debug mode | `True` |

---

## Services

### PostgreSQL Database
- **Image**: postgres:15-alpine
- **Port**: 5432
- **Database**: fastapi_db
- **User**: postgres
- **Password**: postgres (configurable via .env)

### Redis
- **Image**: redis:7-alpine
- **Port**: 6379
- **Persistence**: Enabled with appendonly mode

### FastAPI Application
- **Port**: 8000
- **Auto-reload**: Enabled in development
- **Health checks**: Database, Redis, and Celery connectivity

### Celery Worker
- **Tasks**: Background job processing
- **Broker**: Redis
- **Result Backend**: Redis

### Flower
- **Port**: 5555
- **Purpose**: Celery task monitoring and management

## Local Development

### Without Docker

1. **Install PostgreSQL and Redis locally**
   ```bash
   # macOS
   brew install postgresql redis
   brew services start postgresql
   brew services start redis
   
   # Ubuntu
   sudo apt-get install postgresql postgresql-contrib redis-server
   sudo systemctl start postgresql
   sudo systemctl start redis
   ```

2. **Create database**
   ```bash
   createdb fastapi_db
   ```

3. **Install Python dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Update .env file for local development**
   ```env
   DATABASE_URL=postgresql://postgres:postgres@localhost:5432/fastapi_db
   REDIS_HOST=localhost
   CELERY_BROKER_URL=redis://localhost:6379/0
   CELERY_RESULT_BACKEND=redis://localhost:6379/0
   ```

5. **Initialize database**
   ```bash
   python app/init_db.py
   ```

6. **Start the services**
   ```bash
   # Terminal 1: Start FastAPI
   uvicorn app.main:app --reload
   
   # Terminal 2: Start Celery worker
   celery -A app.celery_app worker --loglevel=info
   
   # Terminal 3: Start Flower (optional)
   celery -A app.celery_app flower
   ```

## Configuration

All configuration is managed through environment variables defined in `.env`:

### Database Settings
- `POSTGRES_USER`: Database user
- `POSTGRES_PASSWORD`: Database password
- `POSTGRES_DB`: Database name
- `POSTGRES_HOST`: Database host
- `POSTGRES_PORT`: Database port
- `DATABASE_URL`: Complete database connection string

### Redis Settings
- `REDIS_HOST`: Redis host
- `REDIS_PORT`: Redis port
- `REDIS_DB`: Redis database number
- `REDIS_PASSWORD`: Redis password (optional)

### Celery Settings
- `CELERY_BROKER_URL`: Message broker URL
- `CELERY_RESULT_BACKEND`: Result backend URL

### API Settings
- `API_HOST`: FastAPI host
- `API_PORT`: FastAPI port
- `DEBUG`: Debug mode

### App Settings
- `APP_NAME`: Application name
- `APP_VERSION`: Application version

## Monitoring

- **Health Endpoint**: Use `/health` to check all service connectivity
- **Flower Dashboard**: Access at http://localhost:5555 to monitor Celery tasks
- **Logs**: View container logs with `docker-compose logs [service_name]`
- **Database**: Connect directly to PostgreSQL on port 5432

## Database

The setup includes a basic SQLAlchemy model (`TaskResult`) for storing task results. Database schema is managed using **Alembic migrations**.

### Database Migrations

The project uses Alembic for database schema management. Migrations are automatically run when the application starts via Docker Compose.

#### Migration Commands

**Create a new migration:**
```bash
# Using the migration script
python migrate.py create "Description of changes"

# Or using Alembic directly
alembic -c app/migrations/alembic.ini revision --autogenerate -m "Description of changes"
```

**Run migrations:**
```bash
# Using the migration script
python migrate.py

# Or using Alembic directly
alembic -c app/migrations/alembic.ini upgrade head
```

**Check migration status:**
```bash
alembic -c app/migrations/alembic.ini current
alembic -c app/migrations/alembic.ini history
```

### Database Schema

The extraction pipeline uses the following tables:

```sql
-- Extraction Jobs
CREATE TABLE extraction_jobs (
    id SERIAL PRIMARY KEY,
    job_id VARCHAR(64) UNIQUE NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    file_path TEXT NOT NULL,
    status VARCHAR(20) NOT NULL,  -- pending, processing, completed, failed
    celery_task_id VARCHAR(64),
    total_pages INTEGER,
    processing_time FLOAT,
    ocr_method VARCHAR(30),
    ocr_confidence FLOAT,
    total_line_items INTEGER,
    escalation_count INTEGER,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE
);

-- Extracted Line Items
CREATE TABLE extracted_line_items (
    id SERIAL PRIMARY KEY,
    job_id VARCHAR(64) REFERENCES extraction_jobs(job_id) ON DELETE CASCADE,
    supplier_name VARCHAR(255),
    item_description TEXT,
    manufacturer_part_number VARCHAR(100),
    original_uom VARCHAR(20),
    detected_pack_quantity INTEGER,
    canonical_base_uom VARCHAR(10) DEFAULT 'EA',
    price_per_base_unit FLOAT,
    unit_price FLOAT,
    total_amount FLOAT,
    quantity FLOAT,
    confidence_score FLOAT,
    escalation_flag BOOLEAN DEFAULT FALSE,
    escalation_reasons JSON,
    hsn_code VARCHAR(20),
    sac_code VARCHAR(20),
    raw_line TEXT,
    pack_info JSON,
    lookup_source VARCHAR(30),
    lookup_confidence FLOAT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

---

## Scaling

To scale Celery workers:
```bash
docker-compose up --scale celery_worker=3
```

To scale the API:
```bash
docker-compose up --scale api=2
```

## Stopping Services

```bash
docker-compose down
```

To remove volumes as well:
```bash
docker-compose down -v
```

## Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| **Database connection failed** | Check PostgreSQL is running: `docker-compose ps postgres` |
| **Redis connection failed** | Check Redis is running: `docker-compose ps redis` |
| **Celery tasks stuck** | Restart worker: `docker-compose restart celery_worker` |
| **OCR returns empty text** | Verify Tesseract installed: `tesseract --version` |
| **OpenAI lookup fails** | Check `OPENAI_API_KEY` in `.env` |
| **Job stays "processing"** | Check Celery logs: `docker-compose logs celery_worker` |

### Debugging Commands

```bash
# Check all service status
docker-compose ps

# View API logs
docker-compose logs -f api

# View Celery worker logs
docker-compose logs -f celery_worker

# Check database connection
docker exec fastapi_postgres psql -U postgres -d fastapi_db -c "SELECT 1"

# Check Redis connection
docker exec fastapi_redis redis-cli ping

# Restart all services
docker-compose restart
```

### OCR Issues

1. **Poor OCR quality**:
   - Ensure PDF is not password-protected
   - Check image DPI (should be 144+)
   - Try different OCR methods via API

2. **Tesseract not found**:
   ```bash
   # Install Tesseract
   # macOS
   brew install tesseract
   
   # Ubuntu
   sudo apt-get install tesseract-ocr
   ```

3. **PaddleOCR import error**:
   ```bash
   pip install paddleocr paddlepaddle
   ```

### Line Item Extraction Issues

1. **No line items extracted**:
   - Check OCR text quality in job details
   - Verify PDF contains tabular data
   - Try with `--verbose` flag for debugging

2. **Wrong UOM detected**:
   - Check raw_line field for OCR errors
   - Consider adding supplier-specific patterns

---

## Adding New Tasks

1. Define your task in `app/tasks/tasks.py`:
   ```python
   @celery_app.task
   def my_new_task(param1, param2):
       # Your task logic here
       return {"result": "success"}
   ```

2. Add an endpoint in `app/main.py` to trigger the task:
   ```python
   @app.post("/tasks/my-new-task")
   async def create_my_new_task(request: MyTaskRequest):
       task = my_new_task.delay(request.param1, request.param2)
       return {"task_id": task.id, "status": "started"}
   ```

3. Restart the services to load the new task.

## Docker Services

The application consists of the following services:

1. **migrate**: Runs database migrations before other services start
2. **api**: FastAPI application server
3. **celery_worker**: Background task processor
4. **celery_flower**: Task monitoring dashboard
5. **postgres**: PostgreSQL database
6. **redis**: Message broker and cache

### Service Dependencies

```
postgres (healthy) → migrate (completed) → api, celery_worker
redis (healthy) → api, celery_worker, celery_flower
```

## Security Considerations

- Change default passwords in production
- Use environment-specific .env files
- Implement proper authentication and authorization
- Use SSL/TLS for database connections in production
- Regularly update dependencies for security patches
- Never commit `.env` files with real API keys to version control

---

## License

MIT License - See LICENSE file for details.

---

## Summary

This PDF Invoice Extraction Pipeline provides:

- **Robust OCR** with multi-method fallback chain
- **Intelligent UOM detection** with pattern matching and normalization
- **Agentic lookup** for missing information with LLM support
- **Safe escalation** when confidence is low
- **Multiple interfaces**: CLI, REST API, and file watcher
- **Production-ready** with Docker, async processing, and database persistence

For questions or issues, check the Troubleshooting section or open an issue.
