# Job Scheduler & Execution Engine API

A backend system that schedules jobs to run once or on a repeating interval, executes them safely in background workers, and handles failures with automatic retries. Built with FastAPI, SQLAlchemy, and Docker — designed for correctness under concurrency.

---

## Why This Project

Most production systems need tasks that run on a schedule without a human pressing a button — sending nightly reports, purging expired sessions, syncing data from a third-party API, or retrying a failed payment. A job scheduler automates this.

**Correctness is critical.** A job must never execute twice by accident (double-charging a customer, sending duplicate emails). It must recover gracefully from crashes — if a server dies mid-execution the job shouldn't vanish into a black hole. And when a job fails, it should retry with backoff instead of silently disappearing.

This project is conceptually similar to tools like **Cron**, **Celery**, or **Airflow**, but built from scratch to demonstrate a clear understanding of the underlying backend logic: atomic state transitions, crash recovery, and concurrent-safe job claiming.

---

## Key Features

- **Atomic job claiming** — race-condition-free `UPDATE…WHERE status='SCHEDULED'` ensures no two workers ever execute the same job, even with multiple parallel workers
- **Automatic retry logic** — failed jobs are rescheduled with exponential backoff up to a configurable `max_retries` limit
- **Crash recovery** — jobs stuck in `RUNNING` after a worker crash are automatically detected and reset on the next worker startup
- **Duplicate job prevention** — rejects creation of a job with identical `name`, `run_at`, and `payload` if one already exists in `SCHEDULED` state
- **Full REST API** with interactive Swagger documentation at `/docs`
- **One-command Docker startup** — `docker compose up --build -d` brings up the API + worker; workers are horizontally scalable with `--scale`
- **Automated test suite** (pytest) with CI via GitHub Actions on every push to `main`

---

## Tech Stack

| Layer           | Technology                          |
|-----------------|-------------------------------------|
| Language        | Python 3.10                         |
| Web Framework   | FastAPI                             |
| ORM             | SQLAlchemy 2.x                      |
| Validation      | Pydantic v2                         |
| Database        | SQLite (WAL mode)                   |
| Containerization| Docker & Docker Compose             |
| API Docs        | Swagger / OpenAPI (built into FastAPI) |
| Testing         | Pytest + HTTPX                      |
| CI/CD           | GitHub Actions                      |

---

## Project Structure

```
job_scheduler/
├── app/
│   ├── __init__.py            # Package initializer
│   ├── main.py                # FastAPI app, endpoint definitions, startup logic
│   ├── models.py              # SQLAlchemy ORM models (Job, JobExecution)
│   ├── schemas.py             # Pydantic request/response schemas with validation
│   ├── crud.py                # Database operations (create, list, get, duplicate check)
│   ├── database.py            # Engine, session factory, SQLite WAL config
│   └── worker.py              # Background polling loop, atomic claiming, crash recovery
├── tests/
│   └── test_main.py           # Pytest suite covering all API endpoints and edge cases
├── .github/
│   └── workflows/
│       └── python-app.yml     # GitHub Actions CI pipeline
├── Dockerfile                 # Multi-stage Python 3.10 image
├── docker-compose.yml         # API + Worker service definitions with shared SQLite volume
├── requirements.txt           # Production dependencies
├── requirements-dev.txt       # Test dependencies (pytest, httpx)
└── .gitignore                 # Ignores venv, __pycache__, *.db, IDE files
```

---

## Data Models

### `jobs` table

| Column             | Type       | Constraints / Default            |
|--------------------|------------|----------------------------------|
| `id`               | String (UUID) | Primary key, auto-generated   |
| `name`             | String     | Not null                         |
| `payload`          | JSON       | Not null                         |
| `schedule_type`    | String     | `"one_time"` or `"interval"`     |
| `run_at`           | DateTime   | Not null                         |
| `interval_seconds` | Integer    | Nullable (required for interval) |
| `max_retries`      | Integer    | Default `3`                      |
| `status`           | String     | Default `"SCHEDULED"` — one of `SCHEDULED`, `RUNNING`, `COMPLETED`, `FAILED` |
| `created_at`       | DateTime   | Auto-set to creation time        |

### `job_executions` table

| Column           | Type       | Constraints / Default           |
|------------------|------------|---------------------------------|
| `id`             | String (UUID) | Primary key, auto-generated  |
| `job_id`         | String     | Foreign key → `jobs.id` (CASCADE) |
| `attempt_number` | Integer    | Not null                        |
| `started_at`     | DateTime   | Auto-set to execution start     |
| `finished_at`    | DateTime   | Nullable                        |
| `status`         | String     | `"SUCCESS"` or `"FAILED"`       |
| `error_message`  | String     | Nullable                        |

---

## How to Run

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running

### Start the system

```bash
docker compose up --build -d
```

This builds the image, starts the **API server** on port 8000, and launches a **background worker**.

### Access the API

- **Swagger UI:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc:** [http://localhost:8000/redoc](http://localhost:8000/redoc)

### Stop the system

```bash
docker compose down
```

---

## API Endpoints

### `POST /jobs` — Create a new job

**Request:**

```json
{
  "name": "Send Weekly Report",
  "payload": {"report_type": "weekly", "recipients": ["admin@example.com"]},
  "schedule_type": "interval",
  "run_at": "2026-07-17T10:00:00Z",
  "interval_seconds": 604800,
  "max_retries": 3
}
```

**Success Response (201):**

```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "name": "Send Weekly Report",
  "payload": {"report_type": "weekly", "recipients": ["admin@example.com"]},
  "schedule_type": "interval",
  "run_at": "2026-07-17T10:00:00",
  "interval_seconds": 604800,
  "max_retries": 3,
  "status": "SCHEDULED",
  "created_at": "2026-07-16T08:00:00"
}
```

**Error Response (400) — past `run_at`:**

```json
{
  "detail": "body -> run_at: Value error, run_at must be a future datetime"
}
```

---

### `GET /jobs` — List all jobs (with optional filters)

Supports query parameters: `status`, `schedule_type`, `sort_by_run_at` (`asc`/`desc`), `run_at_after`, `run_at_before`, `limit`, `offset`.

**Example:** `GET /jobs?status=SCHEDULED&limit=10`

**Success Response (200):**

```json
[
  {
    "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "name": "Send Weekly Report",
    "payload": {"report_type": "weekly"},
    "schedule_type": "interval",
    "run_at": "2026-07-17T10:00:00",
    "interval_seconds": 604800,
    "max_retries": 3,
    "status": "SCHEDULED",
    "created_at": "2026-07-16T08:00:00"
  }
]
```

---

### `GET /jobs/{job_id}` — Get job details with execution history

**Success Response (200):**

```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "name": "Send Weekly Report",
  "payload": {"report_type": "weekly"},
  "schedule_type": "interval",
  "run_at": "2026-07-17T10:00:00",
  "interval_seconds": 604800,
  "max_retries": 3,
  "status": "SCHEDULED",
  "created_at": "2026-07-16T08:00:00",
  "last_execution": null,
  "next_run_at": "2026-07-17T10:00:00",
  "attempt_count": 0,
  "executions": []
}
```

**Error Response (404):**

```json
{
  "detail": "Job not found"
}
```

---

## How Concurrency Is Handled

### Scaling workers

```bash
docker compose up --scale worker=3 -d
```

This launches 3 independent worker processes, all polling the same database for due jobs.

### Why jobs are never executed twice

Each worker uses an **atomic conditional UPDATE** to claim a job. The key insight: the `WHERE status = 'SCHEDULED'` clause means only one worker's `UPDATE` can succeed — the database engine guarantees atomicity at the row level.

```python
# From worker.py — atomic job claiming
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
    execute_job(db, job)
else:
    # Another worker already claimed it — skip
    continue
```

If Worker A and Worker B both see the same `SCHEDULED` job, only one `UPDATE` will match the `WHERE` condition and return `rowcount == 1`. The other gets `rowcount == 0` and moves on. No locks, no race conditions.

---

## How Execution Durability Is Achieved

### The problem

If a worker crashes (OOM kill, container restart, network drop) while a job is in `RUNNING` state, that job is orphaned — it will never complete and never retry.

### The solution

On every startup, each worker runs a **recovery routine** that finds all jobs stuck in `RUNNING` longer than a timeout threshold (30 seconds) and resets them to `SCHEDULED`:

```python
# From worker.py — crash recovery on startup
def recover_stuck_jobs(db):
    running_jobs = db.query(models.Job).filter(
        models.Job.status == "RUNNING"
    ).all()
    for job in running_jobs:
        latest_exec = db.query(models.JobExecution).filter(
            models.JobExecution.job_id == job.id
        ).order_by(models.JobExecution.started_at.desc()).first()

        if latest_exec:
            elapsed = (datetime.utcnow() - latest_exec.started_at).total_seconds()
            if elapsed > RUNNING_TIMEOUT_SECONDS:
                job.status = "SCHEDULED"
                latest_exec.status = "FAILED"
                latest_exec.error_message = f"Worker crashed (stuck for {elapsed:.1f}s)"
    db.commit()
```

The failed execution is logged, and the job re-enters the scheduling queue for its next attempt.

---

## Edge Cases Handled

| Edge Case | How It's Handled |
|-----------|------------------|
| **Job scheduled in the past** | Pydantic validator rejects `run_at <= now` at creation time with a 400 error |
| **Server restart during RUNNING state** | Worker recovery routine detects stuck jobs on startup and resets them to `SCHEDULED` |
| **Max retries reached** | After `max_retries` failed attempts, the job is permanently marked `FAILED` and no longer retried |
| **Worker crash mid-execution** | Same as server restart — the timeout-based recovery marks the orphaned execution as `FAILED` and re-queues the job |
| **Duplicate job creation** | CRUD layer checks for existing `SCHEDULED` jobs with the same `name`, `run_at`, and `payload`; rejects duplicates with a 400 error |

---

## Running Tests

### Locally (Windows)

```bash
.\venv\Scripts\pytest.exe
```

### Locally (Linux / macOS)

```bash
pytest
```

### CI

Tests run automatically via **GitHub Actions** on every push and pull request to `main`. The pipeline installs dependencies, runs `pytest`, and reports results. See [`.github/workflows/python-app.yml`](.github/workflows/python-app.yml).

---

## Author

Built by **Akash** as part of a backend engineering test task.
