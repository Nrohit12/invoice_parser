from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import redis
from sqlalchemy import text
from app.config import settings
from app.celery_app import celery_app
from app.db.database import engine as db_engine
from app.routers import extraction

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    description="PDF Invoice Extraction API with OCR and UOM Normalization"
)

# Include extraction router
app.include_router(extraction.router)

@app.on_event("startup")
async def startup_event():
    """Initialize database connection on startup"""
    try:
        # Test database connection
        with db_engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        print("✅ Database connection established successfully!")
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        # Don't raise exception to allow app to start even if DB is not ready

# Redis client for health checks
redis_client = redis.Redis(
    host=settings.redis_host,
    port=settings.redis_port,
    db=settings.redis_db,
    password=settings.redis_password,
    decode_responses=True
)

# Use the same engine for health checks
engine = db_engine


class TaskRequest(BaseModel):
    duration: int = 10


class AddRequest(BaseModel):
    x: int
    y: int


class NotificationRequest(BaseModel):
    message: str
    recipient: str


@app.get("/")
async def root():
    return {
        "message": "FastAPI + Celery + Redis Application",
        "version": settings.app_version,
        "status": "running"
    }


@app.get("/ui")
async def upload_ui():
    """
    Serve the HTML UI for uploading PDFs and viewing extraction results.
    """
    return FileResponse("templates/index.html")


@app.get("/health")
async def health_check():
    try:
        # Check Redis connection
        redis_client.ping()
        redis_status = "connected"
    except Exception as e:
        redis_status = f"error: {str(e)}"
    
    try:
        # Check Database connection
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)}"
    
    try:
        # Check Celery connection
        celery_inspect = celery_app.control.inspect()
        active_tasks = celery_inspect.active()
        celery_status = "connected" if active_tasks is not None else "disconnected"
    except Exception as e:
        celery_status = f"error: {str(e)}"
    
    return {
        "api": "healthy",
        "database": db_status,
        "redis": redis_status,
        "celery": celery_status
    }
