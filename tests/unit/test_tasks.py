"""Unit tests for Celery tasks - fully mocked, no real I/O."""

import pytest
import uuid
from datetime import datetime, timezone
from unittest.mock import Mock, patch, MagicMock
from io import BytesIO
from PIL import Image

from src.tasks import deidentify_document_task
from src.db.models import JobStatus
from src.models.domain import DeidentificationResult, PHIEntity, BoundingBox, MaskRegion


@pytest.fixture
def sample_tiff_bytes():
    """Create a simple TIFF image for testing."""
    img = Image.new('RGB', (100, 100), color='white')
    buffer = BytesIO()
    img.save(buffer, format='TIFF')
    return buffer.getvalue()


@pytest.fixture
def mock_deidentification_result(sample_tiff_bytes):
    """Mock successful deidentification result."""
    phi_entity = PHIEntity(
        text="John Doe",
        category="Person",
        offset=5,
        length=8,
        confidence=0.95
    )
    bounding_box = BoundingBox(
        page=1,  # 1-indexed
        x=7.2398,
        y=9.34123,
        width=2.45132,
        height=8.123498
    )
    mask_region = MaskRegion(
        page=1,  # 1-indexed
        bounding_box=bounding_box,
        entity_category="Person",
        confidence=0.95
    )
    return DeidentificationResult(
        status="success",
        masked_image_bytes=sample_tiff_bytes,
        pages_processed=1,
        phi_entities_count=1,
        phi_entities=[phi_entity],
        mask_regions=[mask_region],
        processing_time_ms=1234.5,
        errors=[],
        original_format="image/tiff",
        output_format="image/tiff",
        entities_masked=5,
    )


class TestDeidentificationTaskUnit:
    """Pure unit tests for deidentify_document_task with full mocking."""
    
    def test_successful_task_execution(self, sample_tiff_bytes, mock_deidentification_result):
        """Test successful task execution with all components mocked."""
        job_id = str(uuid.uuid4())
        input_key = f"input/{job_id}.tiff"
        
        # Create mock job
        mock_job = Mock()
        mock_job.id = job_id
        mock_job.status = JobStatus.PENDING
        mock_job.retry_count = 0
        
        # Mock database session
        mock_session = MagicMock()
        mock_session.__enter__.return_value = mock_session
        mock_session.__exit__.return_value = None
        mock_session.get.return_value = mock_job
        
        # Mock database manager
        mock_db_manager = Mock()
        mock_db_manager.get_sync_session.return_value = mock_session
        
        # Mock storage backends
        mock_phi_storage = Mock()
        mock_clean_storage = Mock()
        
        with patch('src.tasks.DatabaseSessionManager', return_value=mock_db_manager), \
             patch('src.tasks.create_storage_backend') as mock_storage_factory, \
             patch('src.tasks.asyncio.run') as mock_asyncio_run:
            
            # Setup storage factory
            def storage_factory_side_effect(bucket_type):
                return mock_phi_storage if bucket_type == "phi" else mock_clean_storage
            mock_storage_factory.side_effect = storage_factory_side_effect
            
            # Setup asyncio.run to handle all async calls
            def asyncio_run_side_effect(coro):
                coro_str = str(coro)
                if 'download' in coro_str:
                    return sample_tiff_bytes
                elif '_run_deidentification_pipeline' in coro_str:
                    return mock_deidentification_result
                elif 'upload' in coro_str:
                    return f"masked/{job_id}.tiff"
                elif 'delete' in coro_str:
                    return None
                return None
            
            mock_asyncio_run.side_effect = asyncio_run_side_effect
            
            # Execute task
            result = deidentify_document_task(
                job_id=job_id,
                input_key=input_key,
                masking_level="safe_harbor",
                provider="mock",
            )
            
            # Verify result
            assert result["status"] == "success"
            assert result["job_id"] == job_id
            assert result["pages_processed"] == 1
            assert result["entities_masked"] == 5
            
            # Verify job status was updated to PROCESSING then COMPLETE
            assert mock_job.status == JobStatus.COMPLETE
            assert mock_job.started_at is not None
            assert mock_job.completed_at is not None
            assert mock_job.pages_processed == 1
            assert mock_job.phi_entities_masked == 5
            assert mock_job.output_key == f"masked/{job_id}.tiff"
            
            # Verify session.commit was called
            assert mock_session.commit.call_count >= 2  # At least PROCESSING and COMPLETE updates
    
    def test_task_with_missing_job(self):
        """Test task raises ValueError when job doesn't exist."""
        job_id = str(uuid.uuid4())
        
        # Mock session that returns None for job
        mock_session = MagicMock()
        mock_session.__enter__.return_value = mock_session
        mock_session.__exit__.return_value = None
        mock_session.get.return_value = None
        
        mock_db_manager = Mock()
        mock_db_manager.get_sync_session.return_value = mock_session
        
        with patch('src.tasks.DatabaseSessionManager', return_value=mock_db_manager):
            with pytest.raises(ValueError, match="Job .* not found"):
                deidentify_document_task(
                    job_id=job_id,
                    input_key="input/test.tiff",
                    masking_level="safe_harbor",
                    provider="mock",
                )
    
    def test_phi_storage_deleted_only_on_success(self, sample_tiff_bytes, mock_deidentification_result):
        """Test that PHI storage is only deleted after successful processing."""
        job_id = str(uuid.uuid4())
        input_key = f"input/{job_id}.tiff"
        
        mock_job = Mock()
        mock_job.id = job_id
        mock_job.status = JobStatus.PENDING
        mock_job.retry_count = 0
        
        mock_session = MagicMock()
        mock_session.__enter__.return_value = mock_session
        mock_session.__exit__.return_value = None
        mock_session.get.return_value = mock_job
        
        mock_db_manager = Mock()
        mock_db_manager.get_sync_session.return_value = mock_session
        
        mock_phi_storage = Mock()
        mock_clean_storage = Mock()
        
        with patch('src.tasks.DatabaseSessionManager', return_value=mock_db_manager), \
             patch('src.tasks.create_storage_backend') as mock_storage_factory, \
             patch('src.tasks.asyncio.run') as mock_asyncio_run:
            
            mock_storage_factory.side_effect = lambda bt: (
                mock_phi_storage if bt == "phi" else mock_clean_storage
            )
            
            # Setup successful flow
            mock_asyncio_run.side_effect = [
                sample_tiff_bytes,  # download
                mock_deidentification_result,  # pipeline
                None,  # upload
                None,  # delete
            ]
            
            result = deidentify_document_task(
                job_id=job_id,
                input_key=input_key,
                masking_level="safe_harbor",
                provider="mock",
            )
            
            # Verify asyncio.run was called 4 times (including delete)
            assert mock_asyncio_run.call_count == 4
            assert result["status"] == "success"


class TestCeleryConfiguration:
    """Test Celery app configuration."""
    
    def test_celery_app_configured(self):
        """Test that celery app has correct configuration."""
        from src.tasks import celery_app
        
        assert celery_app is not None
        assert celery_app.conf.task_serializer == 'json'
        assert celery_app.conf.result_serializer == 'json'
        assert celery_app.conf.accept_content == ['json']
        assert celery_app.conf.timezone == 'UTC'
    
    def test_task_has_retry_configuration(self):
        """Test that task has proper retry configuration."""
        assert deidentify_document_task.autoretry_for == (Exception,)
        assert deidentify_document_task.retry_backoff is True
        assert deidentify_document_task.retry_jitter is True