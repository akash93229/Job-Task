"""
CONCURRENCY STRATEGY: Atomic Conditional Update Pattern
=======================================================
Each worker claims a job using an atomic conditional UPDATE:
    UPDATE jobs SET status = 'RUNNING' WHERE id = :job_id AND status = 'SCHEDULED'

Only the worker whose UPDATE returns rowcount == 1 proceeds to execute.
All others get rowcount == 0 and skip — no locks, no race conditions.

SQLite WAL mode + busy timeout handles concurrent writes from multiple workers.
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
RUNNING_TIMEOUT_SECONDS = 30.0


def recover_stuck_jobs(db):
    """
    On startup: find jobs stuck in RUNNING longer than RUNNING_TIMEOUT_SECONDS
    and reset them to SCHEDULED so they can be retried.
    """
    print("Running worker crash recovery routine...")
    try:
        running_jobs = db.query(models.Job).filter(models.Job.status == "RUNNING").all()
        for job in running_jobs:
            latest_exec = (
                db.query(models.JobExecution)
                .filter(models.JobExecution.job_id == job.id)
                .order_by(models.JobExecution.started_at.desc())
                .first()
            )

            if latest_exec:
                elapsed = (datetime.utcnow() - latest_exec.started_at).total_seconds()
                if elapsed > RUNNING_TIMEOUT_SECONDS:
                    job.status = "SCHEDULED"
                    job.run_at = datetime.utcnow()
                    latest_exec.status = "FAILED"
                    latest_exec.finished_at = datetime.utcnow()
                    latest_exec.error_message = (
                        f"Worker crashed or timed out (stuck in RUNNING for {elapsed:.1f}s)"
                    )
                    print(f"Recovered stuck job {job.id} ('{job.name}'). Resetting to SCHEDULED.")
            else:
                # RUNNING with no execution record — unexpected, reset safely
                job.status = "SCHEDULED"
                job.run_at = datetime.utcnow()
                print(f"Recovered job {job.id} ('{job.name}') with no execution record. Resetting to SCHEDULED.")

        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Error during recovery routine: {e}")


def execute_job(db, job):
    """
    Execute a claimed job. Creates a JobExecution record BEFORE work starts (crash durability),
    then updates it to SUCCESS or FAILED after completion.
    Handles retry scheduling with exponential backoff and permanent failure after max_retries.
    """
    # Determine attempt number from existing execution records
    attempt_number = (
        db.query(models.JobExecution)
        .filter(models.JobExecution.job_id == job.id)
        .count()
    ) + 1

    print(f"[{job.id}] Attempt #{attempt_number} starting...")

    # Write execution record BEFORE doing any work — this is what makes crash recovery
    # possible. If the worker dies mid-sleep, recover_stuck_jobs() will find this record,
    # check started_at elapsed time, and reset the job back to SCHEDULED.
    execution = models.JobExecution(
        id=str(uuid.uuid4()),
        job_id=job.id,
        attempt_number=attempt_number,
        started_at=datetime.utcnow(),
        finished_at=None,
        status="FAILED",          # default pessimistic — updated to SUCCESS on completion
        error_message="Worker crash or incomplete execution"
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)

    # Simulate execution: sleep 1-3 seconds (spec requirement)
    simulated_duration = random.uniform(1.0, 3.0)
    time.sleep(simulated_duration)

    # Simulate success/failure: 70% success, 30% failure (spec requirement)
    success = random.random() < 0.70

    # Update the execution record with final result
    execution.finished_at = datetime.utcnow()
    execution.status = "SUCCESS" if success else "FAILED"
    execution.error_message = (
        None if success else "Simulated random execution failure (30% probability)"
    )

    try:
        if success:
            print(f"[{job.id}] Attempt #{attempt_number} succeeded.")
            if job.schedule_type == "interval":
                # Reschedule interval job for next run
                job.status = "SCHEDULED"
                job.run_at = datetime.utcnow() + timedelta(seconds=job.interval_seconds)
                print(f"[{job.id}] Rescheduled interval job to run at {job.run_at}")
            else:
                job.status = "COMPLETED"
        else:
            print(f"[{job.id}] Attempt #{attempt_number} failed.")
            retries_made = attempt_number - 1
            if retries_made < job.max_retries:
                # Exponential backoff: 5s * attempt_number
                backoff_delay = 5 * attempt_number
                job.status = "SCHEDULED"
                job.run_at = datetime.utcnow() + timedelta(seconds=backoff_delay)
                print(
                    f"[{job.id}] {job.max_retries - retries_made} retries remaining. "
                    f"Rescheduled with {backoff_delay}s backoff."
                )
            else:
                # Max retries exhausted — permanently failed, never retried again
                job.status = "FAILED"
                print(f"[{job.id}] Max retries ({job.max_retries}) reached. Marked permanently FAILED.")

        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[{job.id}] Error finalizing job state: {e}")


def poll_and_execute():
    """
    Poll for due jobs and atomically claim + execute one per cycle.
    """
    db = SessionLocal()
    try:
        # Fetch due SCHEDULED jobs
        due_jobs = (
            db.query(models.Job)
            .filter(
                models.Job.status == "SCHEDULED",
                models.Job.run_at <= datetime.utcnow()
            )
            .order_by(models.Job.run_at.asc())
            .limit(10)
            .all()
        )

        for job in due_jobs:
            # Atomic claim: only one worker's UPDATE will match WHERE status='SCHEDULED'
            stmt = (
                update(models.Job)
                .where(models.Job.id == job.id)
                .where(models.Job.status == "SCHEDULED")
                .values(status="RUNNING")
            )
            result = db.execute(stmt)
            db.commit()

            if result.rowcount > 0:
                # This worker claimed it — safe to execute
                db.refresh(job)
                execute_job(db, job)
                break  # One job per poll cycle
            else:
                # Another worker claimed it first — skip
                continue

    except Exception as e:
        print(f"Error in polling loop: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    print("Background Execution Engine started.")

    # Crash recovery on every startup
    startup_db = SessionLocal()
    recover_stuck_jobs(startup_db)
    startup_db.close()

    # Main polling loop
    while True:
        poll_and_execute()
        time.sleep(POLL_INTERVAL)
