import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.database import Base

class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    payload = Column(JSON, nullable=False)
    schedule_type = Column(String, nullable=False)  # "one_time", "interval"
    run_at = Column(DateTime, nullable=False)
    interval_seconds = Column(Integer, nullable=True)
    max_retries = Column(Integer, nullable=False, default=3)
    status = Column(String, nullable=False, default="SCHEDULED")  # "SCHEDULED", "RUNNING", "COMPLETED", "FAILED"
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    executions = relationship("JobExecution", back_populates="job", cascade="all, delete-orphan")

class JobExecution(Base):
    __tablename__ = "job_executions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    attempt_number = Column(Integer, nullable=False)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String, nullable=False)  # "SUCCESS", "FAILED"
    error_message = Column(String, nullable=True)

    # Relationships
    job = relationship("Job", back_populates="executions")
