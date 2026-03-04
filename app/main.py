from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import redis
from sqlalchemy import text
from app.config import settings
from app.celery_app import celery_app
from app.tasks.tasks import long_running_task, add_numbers, send_notification
from app.db.database import engine as db_engine

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug
)

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


@app.post("/tasks/long-running")
async def create_long_running_task(task_request: TaskRequest):
    task = long_running_task.delay(task_request.duration)
    return {
        "task_id": task.id,
        "status": "started",
        "message": f"Long running task started with duration {task_request.duration} seconds"
    }


@app.post("/tasks/add")
async def create_add_task(add_request: AddRequest):
    task = add_numbers.delay(add_request.x, add_request.y)
    return {
        "task_id": task.id,
        "status": "started",
        "message": f"Addition task started: {add_request.x} + {add_request.y}"
    }


@app.post("/tasks/notification")
async def create_notification_task(notification_request: NotificationRequest):
    task = send_notification.delay(
        notification_request.message,
        notification_request.recipient
    )
    return {
        "task_id": task.id,
        "status": "started",
        "message": f"Notification task started for {notification_request.recipient}"
    }


@app.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    task = celery_app.AsyncResult(task_id)
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    response = {
        "task_id": task_id,
        "status": task.status,
        "result": task.result
    }
    
    if task.status == "PROGRESS":
        response["progress"] = task.info
    
    return response


@app.delete("/tasks/{task_id}")
async def cancel_task(task_id: str):
    celery_app.control.revoke(task_id, terminate=True)
    return {
        "task_id": task_id,
        "status": "cancelled",
        "message": "Task cancellation requested"
    }


@app.get("/tasks")
async def list_active_tasks():
    inspect = celery_app.control.inspect()
    active_tasks = inspect.active()
    scheduled_tasks = inspect.scheduled()
    
    return {
        "active_tasks": active_tasks,
        "scheduled_tasks": scheduled_tasks
    }