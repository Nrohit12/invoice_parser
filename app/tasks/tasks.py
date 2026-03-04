import time
from celery import current_task
from app.celery_app import celery_app


@celery_app.task(bind=True)
def long_running_task(self, duration: int = 10):
    """
    A sample long-running task that updates its progress.
    """
    for i in range(duration):
        time.sleep(1)
        current_task.update_state(
            state="PROGRESS",
            meta={"current": i + 1, "total": duration, "status": f"Processing step {i + 1}"}
        )
    
    return {"status": "Task completed!", "result": f"Processed {duration} steps"}


@celery_app.task
def add_numbers(x: int, y: int):
    """
    A simple task that adds two numbers.
    """
    time.sleep(2)  # Simulate some work
    return {"result": x + y, "message": f"Added {x} + {y}"}


@celery_app.task
def send_notification(message: str, recipient: str):
    """
    A sample notification task.
    """
    time.sleep(1)  # Simulate sending notification
    return {
        "status": "sent",
        "message": message,
        "recipient": recipient,
        "timestamp": time.time()
    }