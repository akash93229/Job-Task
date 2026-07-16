import json
from datetime import datetime
from typing import List, Optional
from sqlalchemy.orm import Session
from app import models, schemas

class DuplicateJobError(Exception):
    pass

def create_job(db: Session, job_in: schemas.JobCreate) -> models.Job:
    # Check if a duplicate job already exists in SCHEDULED state
    # We query for same name and run_at, then compare payloads in Python
    existing_jobs = db.query(models.Job).filter(
        models.Job.name == job_in.name,
        models.Job.run_at == job_in.run_at,
        models.Job.status == "SCHEDULED"
    ).all()

    for job in existing_jobs:
        if job.payload == job_in.payload:
            raise DuplicateJobError(
                "A job with the same name, run_at, and payload already exists in SCHEDULED state."
            )

    db_job = models.Job(
        name=job_in.name,
        payload=job_in.payload,
        schedule_type=job_in.schedule_type,
        run_at=job_in.run_at,
        interval_seconds=job_in.interval_seconds,
        max_retries=job_in.max_retries,
        status="SCHEDULED",
        created_at=datetime.utcnow()
    )
    db.add(db_job)
    db.commit()
    db.refresh(db_job)
    return db_job

def get_job(db: Session, job_id: str) -> Optional[models.Job]:
    return db.query(models.Job).filter(models.Job.id == job_id).first()

def list_jobs(
    db: Session,
    status: Optional[str] = None,
    schedule_type: Optional[str] = None,
    sort_by_run_at: Optional[str] = "asc",  # "asc" or "desc"
    run_at_after: Optional[datetime] = None,
    run_at_before: Optional[datetime] = None,
    limit: int = 100,
    offset: int = 0
) -> List[models.Job]:
    query = db.query(models.Job)
    if status:
        query = query.filter(models.Job.status == status)
    if schedule_type:
        query = query.filter(models.Job.schedule_type == schedule_type)
    if run_at_after:
        query = query.filter(models.Job.run_at >= run_at_after)
    if run_at_before:
        query = query.filter(models.Job.run_at <= run_at_before)

    if sort_by_run_at == "desc":
        query = query.order_by(models.Job.run_at.desc())
    else:
        query = query.order_by(models.Job.run_at.asc())

    return query.offset(offset).limit(limit).all()
