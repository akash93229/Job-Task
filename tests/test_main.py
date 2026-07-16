import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app

# Create a test database
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Override get_db dependency
def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

@pytest.fixture(autouse=True)
def setup_database():
    # Create the database tables
    Base.metadata.create_all(bind=engine)
    yield
    # Drop the database tables after test
    Base.metadata.drop_all(bind=engine)

client = TestClient(app)

def test_create_job_past_run_at():
    # POST /jobs rejects a job with run_at in the past
    past_time = (datetime.utcnow() - timedelta(minutes=1)).isoformat() + "Z"
    payload = {
        "name": "Past Job",
        "payload": {"task": "test"},
        "schedule_type": "one_time",
        "run_at": past_time
    }
    response = client.post("/jobs", json=payload)
    assert response.status_code == 400
    assert "run_at must be a future datetime" in response.json()["detail"]

def test_create_job_invalid_interval_seconds():
    # POST /jobs rejects interval_seconds <= 0 for interval jobs
    future_time = (datetime.utcnow() + timedelta(minutes=5)).isoformat() + "Z"
    payload = {
        "name": "Invalid Interval Job",
        "payload": {"task": "test"},
        "schedule_type": "interval",
        "run_at": future_time,
        "interval_seconds": 0
    }
    response = client.post("/jobs", json=payload)
    assert response.status_code == 400
    assert "interval_seconds must be greater than 0" in response.json()["detail"]

    # Test negative interval_seconds
    payload["interval_seconds"] = -5
    response = client.post("/jobs", json=payload)
    assert response.status_code == 400
    assert "interval_seconds must be greater than 0" in response.json()["detail"]

def test_create_valid_one_time_job():
    # POST /jobs successfully creates a valid one_time job
    future_time = (datetime.utcnow() + timedelta(minutes=5)).isoformat() + "Z"
    payload = {
        "name": "Valid One-time Job",
        "payload": {"task": "test"},
        "schedule_type": "one_time",
        "run_at": future_time
    }
    response = client.post("/jobs", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert data["name"] == "Valid One-time Job"
    assert data["status"] == "SCHEDULED"

def test_get_job_detail_404():
    # GET /jobs/{id} returns 404 for a non-existent job id
    response = client.get("/jobs/non-existent-uuid")
    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found"

def test_list_jobs_filter_by_status():
    # GET /jobs returns a list and supports the status filter
    future_time = (datetime.utcnow() + timedelta(minutes=5)).isoformat() + "Z"
    
    # Create a job
    payload = {
        "name": "List Test Job",
        "payload": {"task": "test"},
        "schedule_type": "one_time",
        "run_at": future_time
    }
    client.post("/jobs", json=payload)
    
    # Fetch list
    response = client.get("/jobs")
    assert response.status_code == 200
    jobs = response.json()
    assert len(jobs) >= 1
    
    # Filter by status SCHEDULED
    response_scheduled = client.get("/jobs?status=SCHEDULED")
    assert response_scheduled.status_code == 200
    assert len(response_scheduled.json()) >= 1
    
    # Filter by status COMPLETED
    response_completed = client.get("/jobs?status=COMPLETED")
    assert response_completed.status_code == 200
    assert len(response_completed.json()) == 0
