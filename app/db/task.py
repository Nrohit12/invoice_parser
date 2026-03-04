from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func
from app.db.database import Base

class TaskResult(Base):
    """Model to store task results in database"""
    __tablename__ = "task_results"
    
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String, unique=True, index=True, nullable=False)
    task_name = Column(String, nullable=False)
    status = Column(String, nullable=False)
    result = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<TaskResult(id={self.id}, task_id={self.task_id}, task_name={self.task_name})>"