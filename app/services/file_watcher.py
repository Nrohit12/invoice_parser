"""
File Watcher Service for Automatic PDF Ingestion
Monitors input folder and automatically processes new PDFs
"""

import os
import time
import hashlib
import logging
from pathlib import Path
from typing import Optional, Callable
from datetime import datetime
import threading

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent

from app.db.database import SessionLocal
from app.db.models import FileWatcherState, ExtractionJob, JobStatus
from app.tasks.pdf_extraction_tasks import process_pdf_extraction


class PDFFileHandler(FileSystemEventHandler):
    """Handler for PDF file events"""
    
    def __init__(self, callback: Callable[[str], None], logger: logging.Logger):
        self.callback = callback
        self.logger = logger
        self.processing_files = set()
        self._lock = threading.Lock()
    
    def on_created(self, event):
        """Handle new file creation"""
        if event.is_directory:
            return
        
        file_path = event.src_path
        
        # Only process PDF files
        if not file_path.lower().endswith('.pdf'):
            return
        
        # Avoid duplicate processing
        with self._lock:
            if file_path in self.processing_files:
                return
            self.processing_files.add(file_path)
        
        try:
            # Wait for file to be fully written
            self._wait_for_file_ready(file_path)
            
            self.logger.info(f"New PDF detected: {file_path}")
            self.callback(file_path)
            
        except Exception as e:
            self.logger.error(f"Error processing {file_path}: {e}")
        finally:
            with self._lock:
                self.processing_files.discard(file_path)
    
    def _wait_for_file_ready(self, file_path: str, timeout: int = 30):
        """Wait for file to be fully written"""
        start_time = time.time()
        last_size = -1
        
        while time.time() - start_time < timeout:
            try:
                current_size = os.path.getsize(file_path)
                if current_size == last_size and current_size > 0:
                    # File size stable, likely done writing
                    time.sleep(0.5)  # Extra safety margin
                    return
                last_size = current_size
                time.sleep(0.5)
            except OSError:
                time.sleep(0.5)
        
        raise TimeoutError(f"File {file_path} not ready after {timeout}s")


class FileWatcherService:
    """Service for watching directories and auto-processing PDFs"""
    
    def __init__(self, watch_dir: str, options: dict = None):
        self.watch_dir = Path(watch_dir)
        self.options = options or {}
        self.logger = logging.getLogger(__name__)
        self.observer = None
        self._running = False
    
    def _get_file_hash(self, file_path: str) -> str:
        """Calculate MD5 hash of file for deduplication"""
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    
    def _is_already_processed(self, file_path: str) -> bool:
        """Check if file was already processed"""
        db = SessionLocal()
        try:
            state = db.query(FileWatcherState).filter(
                FileWatcherState.file_path == file_path
            ).first()
            
            if state and state.processed:
                return True
            
            # Also check by hash for renamed files
            file_hash = self._get_file_hash(file_path)
            state_by_hash = db.query(FileWatcherState).filter(
                FileWatcherState.file_hash == file_hash,
                FileWatcherState.processed == True
            ).first()
            
            return state_by_hash is not None
            
        finally:
            db.close()
    
    def _record_file_state(self, file_path: str, job_id: str):
        """Record file processing state"""
        db = SessionLocal()
        try:
            file_hash = self._get_file_hash(file_path)
            
            state = FileWatcherState(
                file_path=file_path,
                file_hash=file_hash,
                processed=False,
                job_id=job_id,
                discovered_at=datetime.utcnow()
            )
            db.add(state)
            db.commit()
            
        except Exception as e:
            self.logger.error(f"Failed to record file state: {e}")
            db.rollback()
        finally:
            db.close()
    
    def _mark_file_processed(self, file_path: str):
        """Mark file as processed"""
        db = SessionLocal()
        try:
            state = db.query(FileWatcherState).filter(
                FileWatcherState.file_path == file_path
            ).first()
            
            if state:
                state.processed = True
                state.processed_at = datetime.utcnow()
                db.commit()
                
        except Exception as e:
            self.logger.error(f"Failed to mark file processed: {e}")
            db.rollback()
        finally:
            db.close()
    
    def _process_pdf(self, file_path: str):
        """Process a single PDF file"""
        
        # Check if already processed
        if self._is_already_processed(file_path):
            self.logger.info(f"Skipping already processed file: {file_path}")
            return
        
        # Generate job ID
        import uuid
        job_id = f"watch_{uuid.uuid4().hex[:12]}"
        
        # Record file state
        self._record_file_state(file_path, job_id)
        
        # Create job record
        db = SessionLocal()
        try:
            file_name = Path(file_path).name
            file_size = os.path.getsize(file_path)
            
            job = ExtractionJob(
                job_id=job_id,
                file_name=file_name,
                file_path=file_path,
                file_size=file_size,
                status=JobStatus.PENDING.value,
                options=self.options
            )
            db.add(job)
            db.commit()
            
            self.logger.info(f"Created job {job_id} for {file_name}")
            
        except Exception as e:
            self.logger.error(f"Failed to create job: {e}")
            db.rollback()
            return
        finally:
            db.close()
        
        # Submit Celery task
        try:
            task = process_pdf_extraction.delay(job_id, file_path, self.options)
            
            # Update job with task ID
            db = SessionLocal()
            try:
                job = db.query(ExtractionJob).filter(
                    ExtractionJob.job_id == job_id
                ).first()
                if job:
                    job.celery_task_id = task.id
                    job.status = JobStatus.PROCESSING.value
                    db.commit()
            finally:
                db.close()
            
            self.logger.info(f"Submitted task {task.id} for job {job_id}")
            
        except Exception as e:
            self.logger.error(f"Failed to submit task: {e}")
    
    def process_existing_files(self):
        """Process any existing PDF files in watch directory"""
        if not self.watch_dir.exists():
            self.logger.warning(f"Watch directory does not exist: {self.watch_dir}")
            return
        
        pdf_files = list(self.watch_dir.glob("*.pdf"))
        self.logger.info(f"Found {len(pdf_files)} existing PDF files")
        
        for pdf_file in pdf_files:
            self._process_pdf(str(pdf_file))
    
    def start(self, process_existing: bool = True):
        """Start watching directory"""
        
        # Ensure directory exists
        self.watch_dir.mkdir(parents=True, exist_ok=True)
        
        # Process existing files first
        if process_existing:
            self.process_existing_files()
        
        # Set up file watcher
        handler = PDFFileHandler(self._process_pdf, self.logger)
        self.observer = Observer()
        self.observer.schedule(handler, str(self.watch_dir), recursive=False)
        
        self._running = True
        self.observer.start()
        
        self.logger.info(f"Started watching directory: {self.watch_dir}")
    
    def stop(self):
        """Stop watching directory"""
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self._running = False
            self.logger.info("File watcher stopped")
    
    def is_running(self) -> bool:
        """Check if watcher is running"""
        return self._running


def start_file_watcher(watch_dir: str, options: dict = None) -> FileWatcherService:
    """
    Convenience function to start file watcher
    
    Args:
        watch_dir: Directory to watch for PDFs
        options: Processing options
        
    Returns:
        FileWatcherService instance
    """
    watcher = FileWatcherService(watch_dir, options)
    watcher.start()
    return watcher
