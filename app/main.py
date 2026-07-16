from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List, Optional
from app import crud, models, schemas
from app.database import engine, get_db

# Create database tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Job Scheduler & Execution Engine API",
    description="Backend API for scheduling and managing jobs with custom execution options.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc: RequestValidationError):
    errors = []
    for err in exc.errors():
        # Get path location for clear output
        loc = " -> ".join(str(x) for x in err.get("loc", []))
        msg = err.get("msg", "Invalid value")
        errors.append(f"{loc}: {msg}")
    return JSONResponse(
        status_code=400,
        content={"detail": "; ".join(errors)},
    )

@app.post("/jobs", response_model=schemas.JobResponse, status_code=201)
def create_job(job_in: schemas.JobCreate, db: Session = Depends(get_db)):
    try:
        return crud.create_job(db=db, job_in=job_in)
    except crud.DuplicateJobError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/jobs", response_model=List[schemas.JobResponse])
def list_jobs(
    status: Optional[str] = Query(None, description="Filter by status (SCHEDULED, RUNNING, COMPLETED, FAILED)"),
    schedule_type: Optional[str] = Query(None, description="Filter by schedule type (one_time, interval)"),
    sort_by_run_at: Optional[str] = Query("asc", pattern="^(asc|desc)$", description="Sort by run_at order (asc or desc)"),
    run_at_after: Optional[datetime] = Query(None, description="Filter jobs scheduled to run after this datetime"),
    run_at_before: Optional[datetime] = Query(None, description="Filter jobs scheduled to run before this datetime"),
    limit: int = Query(100, ge=1, le=1000, description="Pagination limit"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    db: Session = Depends(get_db)
):
    return crud.list_jobs(
        db=db,
        status=status,
        schedule_type=schedule_type,
        sort_by_run_at=sort_by_run_at,
        run_at_after=run_at_after,
        run_at_before=run_at_before,
        limit=limit,
        offset=offset
    )

@app.get("/jobs/{job_id}", response_model=schemas.JobDetailResponse)
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = crud.get_job(db=db, job_id=job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Sort executions by started_at desc to find last execution easily
    sorted_executions = sorted(job.executions, key=lambda e: e.started_at, reverse=True)
    last_exec = sorted_executions[0] if sorted_executions else None
    
    # Calculate next scheduled run time
    # If job status is SCHEDULED, it will run at run_at
    next_run = job.run_at if job.status == "SCHEDULED" else None
    
    # Attempt count is the highest attempt number seen or the total count
    attempt_count = max((e.attempt_number for e in job.executions), default=0)

    # Return JobDetailResponse fields
    return schemas.JobDetailResponse(
        id=job.id,
        name=job.name,
        payload=job.payload,
        schedule_type=job.schedule_type,
        run_at=job.run_at,
        interval_seconds=job.interval_seconds,
        max_retries=job.max_retries,
        status=job.status,
        created_at=job.created_at,
        last_execution=last_exec,
        next_run_at=next_run,
        attempt_count=attempt_count,
        executions=job.executions
    )
