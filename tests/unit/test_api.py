"""Unit tests for FastAPI endpoints with dependency overrides."""

import pytest
import uuid
from datetime import datetime, timezone
from unittest.mock import Mock, AsyncMock, patch
from io import BytesIO

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.api.main import app
from src.api import dependencies
from src.db.models import Job, JobStatus

@pytest.fixture
def sample_job():
    """Create a sample job for testing."""
    job_id = str(uuid.uuid4())
    job = Mock(spec=Job)
    job.id = job_id
    job.status = JobStatus.COMPLETE
    job.ocr_provider = "azure"
    job.phi_provider = "azure"
    job.masking_level = "safe_harbor"
    job.created_at = datetime.now(timezone.utc)
    job.started_at = datetime.now(timezone.utc)
    job.completed_at = datetime.now(timezone.utc)
    job.pages_processed = 5
    job.phi_entities_masked = 10
    job.processing_time_ms = 1234.5
    job.error_message = None
    job.retry_count = 0
    job.input_key = f"input/{job_id}.tiff"
    job.output_key = f"masked/{job_id}.tiff"
    return job


class TestCreateJob:
    """Tests for POST /api/v1/jobs endpoint."""
    
    @pytest.fixture(autouse=True)
    def setup_task_mock(self):
        """Mock Celery task for all tests in this class."""
        with patch('src.api.main.deidentify_document_task') as mock_task:
            self.mock_task = mock_task
            yield
    
    def test_create_job_success(self, client, mock_db_session, mock_phi_storage):
        """Test successful job creation."""
        job_id = str(uuid.uuid4())
        
        # Mock job creation
        mock_job = Mock()
        mock_job.id = job_id
        mock_job.status = JobStatus.PENDING
        mock_job.created_at = datetime.now(timezone.utc)  # Already here
        
        mock_db_session.add = Mock()
        mock_db_session.commit = Mock()
        
        # Fix the refresh to actually set created_at
        def mock_refresh(job):
            job.created_at = datetime.now(timezone.utc)
        
        mock_db_session.refresh = Mock(side_effect=mock_refresh)
        
        # Mock uuid generation
        with patch('uuid.uuid4', return_value=uuid.UUID(job_id)):
            response = client.post(
                "/api/v1/jobs",
                params={"masking_level": "safe_harbor"},
                files={"file": ("test.tiff", b"fake tiff data", "image/tiff")}
            )
        
        assert response.status_code == 201
        data = response.json()
        assert data["job_id"] == job_id
        assert data["status"] == "pending"
        assert "created_at" in data
        
        # Verify storage upload was called
        mock_phi_storage.upload.assert_called_once()
        
        # Verify task was enqueued
        self.mock_task.delay.assert_called_once()
    
    def test_create_job_file_too_large(self, client, mock_settings):
        """Test that files exceeding size limit are rejected."""
        large_file = b"x" * (60 * 1024 * 1024)  # 60MB
        
        response = client.post(
            "/api/v1/jobs",
            params={"masking_level": "safe_harbor"},
            files={"file": ("test.tiff", large_file, "image/tiff")}
        )
        
        assert response.status_code == 413
        assert "File too large" in response.json()["detail"]
    
    def test_create_job_unsupported_file_type(self, client):
        """Test that unsupported file types are rejected."""
        response = client.post(
            "/api/v1/jobs",
            params={"masking_level": "safe_harbor"},
            files={"file": ("test.txt", b"fake data", "text/plain")}
        )
        
        assert response.status_code == 400
        assert "Unsupported file type" in response.json()["detail"]
    
    def test_create_job_storage_failure(self, client, mock_phi_storage):
        """Test handling of storage upload failure."""
        mock_phi_storage.upload = AsyncMock(side_effect=Exception("Storage error"))
        
        response = client.post(
            "/api/v1/jobs",
            params={"masking_level": "safe_harbor"},
            files={"file": ("test.tiff", b"fake data", "image/tiff")}
        )
        
        assert response.status_code == 500
        assert "Failed to upload document" in response.json()["detail"]


class TestGetJobStatus:
    """Tests for GET /api/v1/jobs/{job_id} endpoint."""
    
    def test_get_job_status_success(self, client, mock_db_session, sample_job):
        """Test successful job status retrieval."""
        mock_db_session.get = Mock(return_value=sample_job)
        
        response = client.get(f"/api/v1/jobs/{sample_job.id}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == sample_job.id
        assert data["status"] == "complete"
        assert data["pages_processed"] == 5
        assert data["phi_entities_masked"] == 10
    
    def test_get_job_status_not_found(self, client, mock_db_session):
        """Test 404 when job doesn't exist."""
        job_id = str(uuid.uuid4())
        mock_db_session.get = Mock(return_value=None)
        
        response = client.get(f"/api/v1/jobs/{job_id}")
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]


class TestListJobs:
    """Tests for GET /api/v1/jobs endpoint."""
    
    def test_list_jobs_no_filter(self, client, mock_db_session):
        """Test listing all jobs without filters."""
        mock_jobs = [
            Mock(
                id=str(uuid.uuid4()),
                status=JobStatus.COMPLETE,
                masking_level="safe_harbor",
                created_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
                pages_processed=5
            )
            for _ in range(3)
        ]
        
        # Mock the count query
        count_result = Mock()
        count_result.scalar = Mock(return_value=3)
        
        # Mock the select query
        select_result = Mock()
        select_result.scalars = Mock(return_value=Mock(all=Mock(return_value=mock_jobs)))
        
        mock_db_session.execute = Mock(side_effect=[count_result, select_result])
        
        response = client.get("/api/v1/jobs")
        
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert len(data["jobs"]) == 3
        assert data["page"] == 1
        assert data["page_size"] == 10
    
    def test_list_jobs_with_status_filter(self, client, mock_db_session):
        """Test listing jobs filtered by status."""
        count_result = Mock()
        count_result.scalar = Mock(return_value=0)
        
        select_result = Mock()
        select_result.scalars = Mock(return_value=Mock(all=Mock(return_value=[])))
        
        mock_db_session.execute = Mock(side_effect=[count_result, select_result])
        
        response = client.get("/api/v1/jobs?status=complete")
        
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
    
    def test_list_jobs_pagination(self, client, mock_db_session):
        """Test job listing pagination."""
        count_result = Mock()
        count_result.scalar = Mock(return_value=25)
        
        select_result = Mock()
        select_result.scalars = Mock(return_value=Mock(all=Mock(return_value=[])))
        
        mock_db_session.execute = Mock(side_effect=[count_result, select_result])
        
        response = client.get("/api/v1/jobs?page=2&page_size=10")
        
        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 2
        assert data["page_size"] == 10
        assert data["total"] == 25


class TestDownloadResult:
    """Tests for GET /api/v1/jobs/{job_id}/download endpoint."""
    
    def test_download_success(self, client, mock_db_session, mock_clean_storage, sample_job):
        """Test successful download of masked document."""
        mock_db_session.get = Mock(return_value=sample_job)
        
        response = client.get(f"/api/v1/jobs/{sample_job.id}/download")
        
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/tiff"
        assert "attachment" in response.headers["content-disposition"]
    
    def test_download_job_not_found(self, client, mock_db_session):
        """Test 404 when job doesn't exist."""
        job_id = str(uuid.uuid4())
        mock_db_session.get = Mock(return_value=None)
        
        response = client.get(f"/api/v1/jobs/{job_id}/download")
        
        assert response.status_code == 404
    
    def test_download_job_not_complete(self, client, mock_db_session):
        """Test 400 when job is not yet complete."""
        job_id = str(uuid.uuid4())
        
        mock_job = Mock()
        mock_job.status = JobStatus.PROCESSING
        mock_db_session.get = Mock(return_value=mock_job)
        
        response = client.get(f"/api/v1/jobs/{job_id}/download")
        
        assert response.status_code == 400
        assert "not complete" in response.json()["detail"].lower()
    
    def test_download_file_not_found(self, client, mock_db_session, mock_clean_storage, sample_job):
        """Test 500 when output file doesn't exist in storage."""
        mock_db_session.get = Mock(return_value=sample_job)
        mock_clean_storage.download = AsyncMock(side_effect=FileNotFoundError())
        
        response = client.get(f"/api/v1/jobs/{sample_job.id}/download")
        
        assert response.status_code == 500
        assert "not found" in response.json()["detail"].lower()


class TestHealthCheck:
    """Tests for /health endpoint."""
    
    def test_health_check(self, client):
        """Test health check endpoint."""
        response = client.get("/health")
        
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"