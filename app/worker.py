"""
CONCURRENCY STRATEGY: Atomic Conditional Update Pattern (Optimistic Claiming)
============================================================================
For concurrency handling, we use an ATOMIC conditional UPDATE pattern:
    UPDATE jobs SET status = 'RUNNING' WHERE id = :job_id AND status = 'SCHEDULED'

Why this strategy was chosen:
1. SQLite does not support PostgreSQL-style SELECT FOR UPDATE SKIP LOCKED.
2. Using a separate SELECT followed by an UPDATE creates a race condition where multiple workers
   could read the same SCHEDULED job and both attempt to run it.
3. The conditional UPDATE is atomic. The SQLite database engine guarantees that only one update
   succeeds. We check the number of affected rows (rowcount) in the database session.
   - If rowcount == 1, the current worker successfully claimed the job and can execute it.
   - If rowcount == 0, another worker has already claimed it; we skip execution and continue.
4. SQLite is configured with WAL (Write-Ahead Logging) and a busy timeout to handle concurrent
   writes from multiple worker instances gracefully without immediately locking up.
"""

import os
import time
import random
import uuid
from datetime import datetime, timedelta
from sqlalchemy import update
from app import models
from app.database import SessionLocal

POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "5"))
RUNNING_TIMEOUT_SECONDS = 30.0  # Time after which a RUNNING job is considered stuck/crashed

def recover_stuck_jobs(db):
    """
    Finds all jobs stuck in RUNNING state (e.g. running longer than RUNNING_TIMEOUT_SECONDS)
    and resets them back to SCHEDULED so they can be retried safely.
    Also handles marking their last execution as FAILED.
    """
    print("Running worker crash recovery routine...")
    try:
        running_jobs = db.query(models.Job).filter(models.Job.status == "RUNNING").all()
        for job in running_jobs:
            # Find the latest execution record for this job
            latest_exec = db.query(models.JobExecution).filter(
                models.JobExecution.job_id == job.id
            ).order_by(models.JobExecution.started_at.desc()).first()

            if latest_exec:
                elapsed = (datetime.utcnow() - latest_exec.started_at).total_seconds()
                if elapsed > RUNNING_TIMEOUT_SECONDS:
                    # Mark the job as SCHEDULED to retry
                    job.status = "SCHEDULED"
                    job.run_at = datetime.utcnow()
                    
                    # Mark the execution record as FAILED
                    latest_exec.status = "FAILED"
                    latest_exec.finished_at = datetime.utcnow()
                    latest_exec.error_message = f"Worker crashed or timed out (stuck in RUNNING for {elapsed:.1f}s)"
                    print(f"Recovered stuck job {job.id} ('{job.name}'). Resetting to SCHEDULED.")
            else:
                # Running but no execution record found (unexpected state)
                job.status = "SCHEDULED"
                job.run_at = datetime.utcnow()
                print(f"Recovered running job {job.id} ('{job.name}') with no execution records. Resetting to SCHEDULED.")
        
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Error during recovery routine: {e}")

def execute_job(db, job):
    """
    Simulates execution of a claimed job, including success/failure rates
    and scheduling retries or interval updates.
    """
    # 1. Determine current attempt number
    attempt_number = db.query(models.JobExecution).filter(models.JobExecution.job_id == job.id).count() + 1
    
    # 2. Create JobExecution record
    execution = models.JobExecution(
        id=str(uuid.uuid4()),
        job_id=job.id,
        attempt_number=attempt_number,
        started_at=datetime.utcnow(),
        status="RUNNING"
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)

    print(f"[{job.id}] Attempt #{attempt_number} starting...")

    # 3. Simulate execution time (1-3 seconds)
    simulated_duration = random.uniform(1.0, 3.0)
    time.sleep(simulated_duration)

    # 4. Simulate success/failure (70% success, 30% failure)
    success = random.random() < 0.70

    try:
        if success:
            print(f"[{job.id}] Attempt #{attempt_number} Succeeded.")
            execution.status = "SUCCESS"
            execution.finished_at = datetime.utcnow()
            
            if job.schedule_type == "interval":
                # Reschedule interval job
                job.status = "SCHEDULED"
                job.run_at = datetime.utcnow() + timedelta(seconds=job.interval_seconds)
                print(f"[{job.id}] Rescheduled interval job to run at {job.run_at}")
            else:
                # Complete one_time job
                job.status = "COMPLETED"
        else:
            print(f"[{job.id}] Attempt #{attempt_number} Failed.")
            execution.status = "FAILED"
            execution.finished_at = datetime.utcnow()
            execution.error_message = "Simulated random execution failure (30% probability)"

            retries_made = attempt_number - 1
            if retries_made < job.max_retries:
                # Retry with a short backoff (e.g. 5 seconds * attempt_number)
                backoff_delay = 5 * attempt_number
                job.status = "SCHEDULED"
                job.run_at = datetime.utcnow() + timedelta(seconds=backoff_delay)
                print(f"[{job.id}] Retries remaining ({job.max_retries - retries_made}). Rescheduled with {backoff_delay}s backoff.")
            else:
                # Permanent failure
                job.status = "FAILED"
                print(f"[{job.id}] Max retries reached ({job.max_retries}). Marked as permanently FAILED.")

        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[{job.id}] Error finalizing job state: {e}")

def poll_and_execute():
    """
    Main polling loop that queries the database for due jobs and executes them.
    """
    db = SessionLocal()
    try:
        # Fetch up to 10 scheduled jobs that are due
        due_jobs = db.query(models.Job).filter(
            models.Job.status == "SCHEDULED",
            models.Job.run_at <= datetime.utcnow()
        ).order_by(models.Job.run_at.asc()).limit(10).all()

        for job in due_jobs:
            # ATOMIC Claiming: transition status from SCHEDULED to RUNNING
            stmt = (
                update(models.Job)
                .where(models.Job.id == job.id)
                .where(models.Job.status == "SCHEDULED")
                .values(status="RUNNING")
            )
            result = db.execute(stmt)
            db.commit()

            if result.rowcount > 0:
                # We successfully claimed the job
                # Refresh object to bind to current session state
                db.refresh(job)
                execute_job(db, job)
                # After executing one job, we yield control to keep polling
                break
            else:
                # Another worker claimed it first, skip to next candidate
                continue
    except Exception as e:
        print(f"Error in polling loop: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    print("Background Execution Engine started.")
    
    # Run recovery routine on startup
    startup_db = SessionLocal()
    recover_stuck_jobs(startup_db)
    startup_db.close()

    # Begin continuous polling loop
    while True:
        poll_and_execute()
        time.sleep(POLL_INTERVAL)
