"""Integration tests for FastAPI with real database and storage."""

import pytest
import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.api.main import app
from src.db.models import Job, JobStatus, Base
from src.db.session import DatabaseSessionManager
from src.storage.local import LocalStorageBackend


@pytest.fixture
def test_client(sync_db_manager, temp_storage_dirs):
    """TestClient with real DB and storage, mocked Celery."""
    phi_dir, clean_dir = temp_storage_dirs
    
    from src.api import dependencies
    from unittest.mock import Mock, patch
    
    # Mock settings
    mock_general_settings = Mock()
    mock_general_settings.MAX_FILE_SIZE_MB = 50
    
    mock_provider_settings = Mock()
    mock_provider_settings.OCR_PROVIDER = "azure"
    mock_provider_settings.PHI_PROVIDER = "azure"
    
    # Override dependency functions
    def override_get_db():
        with sync_db_manager.get_sync_session() as session:
            yield session
    
    def override_phi_storage():
        return LocalStorageBackend(base_path=phi_dir)
    
    def override_clean_storage():
        return LocalStorageBackend(base_path=clean_dir)
    
    app.dependency_overrides[dependencies.get_db_session] = override_get_db
    app.dependency_overrides[dependencies.get_phi_storage] = override_phi_storage
    app.dependency_overrides[dependencies.get_clean_storage] = override_clean_storage
    app.dependency_overrides[dependencies.get_general_settings] = lambda: mock_general_settings
    app.dependency_overrides[dependencies.get_provider_settings] = lambda: mock_provider_settings
    app.dependency_overrides[dependencies.verify_authentication] = lambda: True
    
    # Mock Celery task
    with patch('src.api.main.deidentify_document_task') as mock_task:
        mock_task.delay = Mock(return_value=None)
        
        client = TestClient(app)
        yield client, sync_db_manager, phi_dir, clean_dir
    
    app.dependency_overrides.clear()


class TestAPIIntegration:
    """Integration tests with real database and storage."""
    
    def test_create_and_retrieve_job(self, test_client, sample_tiff_bytes):
        """Test creating a job and retrieving its status."""
        client, sync_db_manager, phi_dir, clean_dir = test_client
        
        # Create job
        response = client.post(
            "/api/v1/jobs",
            params={"masking_level": "safe_harbor"},
            files={"file": ("test.tiff", sample_tiff_bytes, "image/tiff")}
        )
        
        assert response.status_code == 201
        job_data = response.json()
        job_id = job_data["job_id"]
        
        # Verify job in database
        with sync_db_manager.get_sync_session() as session:
            job = session.get(Job, job_id)
            assert job is not None
            assert job.status == JobStatus.PENDING
            assert job.ocr_provider == "azure"  # Default from settings
            assert job.phi_provider == "azure"
            assert job.masking_level == "safe_harbor"
        
        # Retrieve job status
        response = client.get(f"/api/v1/jobs/{job_id}")
        assert response.status_code == 200
        status_data = response.json()
        assert status_data["job_id"] == job_id
        assert status_data["status"] == "pending"
    
    def test_list_jobs(self, test_client, sample_tiff_bytes):
        """Test listing jobs with pagination."""
        client, sync_db_manager, phi_dir, clean_dir = test_client
        
        # Create multiple jobs
        job_ids = []
        for i in range(3):
            response = client.post(
                "/api/v1/jobs",
                params={"masking_level": "safe_harbor"},
                files={"file": (f"test{i}.tiff", sample_tiff_bytes, "image/tiff")}
            )
            assert response.status_code == 201
            job_ids.append(response.json()["job_id"])
        
        # List all jobs
        response = client.get("/api/v1/jobs")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert len(data["jobs"]) == 3
    
    def test_download_completed_job(self, test_client, sample_tiff_bytes):
        """Test downloading a completed job's output."""
        client, sync_db_manager, phi_dir, clean_dir = test_client
        
        # Create job manually
        job_id = str(uuid.uuid4())
        output_key = f"masked/{job_id}.tiff"
        
        with sync_db_manager.get_sync_session() as session:
            job = Job(
                id=job_id,
                status=JobStatus.COMPLETE,
                ocr_provider="azure",
                phi_provider="azure",
                masking_level="safe_harbor",
                input_key=f"input/{job_id}.tiff",
                output_key=output_key,
                pages_processed=1,
                phi_entities_masked=5,
                processing_time_ms=1000.0,
            )
            session.add(job)
            session.commit()
        
        # Upload mock output to clean storage
        clean_storage = LocalStorageBackend(base_path=clean_dir)
        clean_storage.upload(output_key, sample_tiff_bytes, "image/tiff")
        
        # Download
        response = client.get(f"/api/v1/jobs/{job_id}/download")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/tiff"
        assert len(response.content) > 0
    
    def test_cannot_download_pending_job(self, test_client, sample_tiff_bytes):
        """Test that pending jobs cannot be downloaded."""
        client, sync_db_manager, phi_dir, clean_dir = test_client
        
        # Create job
        response = client.post(
            "/api/v1/jobs",
            params={"masking_level": "safe_harbor"},
            files={"file": ("test.tiff", sample_tiff_bytes, "image/tiff")}
        )
        job_id = response.json()["job_id"]
        
        # Try to download
        response = client.get(f"/api/v1/jobs/{job_id}/download")
        assert response.status_code == 400
        assert "not complete" in response.json()["detail"].lower()
    
    def test_file_size_validation(self, test_client):
        """Test that oversized files are rejected."""
        client, _, _, _ = test_client
        
        # Create a large file (60MB)
        large_file = b"x" * (60 * 1024 * 1024)
        
        response = client.post(
            "/api/v1/jobs",
            params={"masking_level": "safe_harbor"},
            files={"file": ("large.tiff", large_file, "image/tiff")}
        )
        
        assert response.status_code == 413
        assert "too large" in response.json()["detail"].lower()
    
    def test_health_check(self, test_client):
        """Test health check endpoint."""
        client, _, _, _ = test_client
        
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"
    
    def test_job_filtering_by_status(self, test_client, sample_tiff_bytes):
        """Test filtering jobs by status."""
        client, sync_db_manager, phi_dir, clean_dir = test_client
        
        # Create pending job
        response = client.post(
            "/api/v1/jobs",
            params={"masking_level": "safe_harbor"},
            files={"file": ("pending.tiff", sample_tiff_bytes, "image/tiff")}
        )
        pending_job_id = response.json()["job_id"]
        
        # Create completed job manually
        completed_job_id = str(uuid.uuid4())
        with sync_db_manager.get_sync_session() as session:
            job = Job(
                id=completed_job_id,
                status=JobStatus.COMPLETE,
                ocr_provider="azure",
                phi_provider="azure",
                masking_level="safe_harbor",
                input_key=f"input/{completed_job_id}.tiff",
                output_key=f"masked/{completed_job_id}.tiff",
            )
            session.add(job)
            session.commit()
        
        # Filter by pending
        response = client.get("/api/v1/jobs?status=pending")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["jobs"][0]["job_id"] == pending_job_id
        
        # Filter by complete
        response = client.get("/api/v1/jobs?status=complete")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["jobs"][0]["job_id"] == completed_job_id
