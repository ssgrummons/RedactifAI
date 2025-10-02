"""Integration tests for Celery tasks using eager mode and mock services."""

import pytest
import uuid
import asyncio

from src.tasks import deidentify_document_task, _run_deidentification_pipeline
from src.db.models import Job, JobStatus, Base
from src.storage.local import LocalStorageBackend
from src.config.storage import StorageSettings
from pathlib import Path



class TestCeleryTaskIntegration:
    """Integration tests with real database, storage, and mock OCR/PHI services."""
    
    def test_end_to_end_deidentification_with_eager_mode(
        self,
        sync_db_manager,
        temp_storage_dirs,
        sample_tiff_bytes
    ):
        """Test complete flow: job creation → processing → completion."""
        phi_dir, clean_dir = temp_storage_dirs
        
        # Create job in database using SYNC session
        job_id = str(uuid.uuid4())
        input_key = f"input/{job_id}.tiff"
        
        with sync_db_manager.get_sync_session() as session:
            job = Job(
                id=job_id,
                status=JobStatus.PENDING,
                ocr_provider="mock",
                phi_provider="mock",
                masking_level="safe_harbor",
                input_key=input_key,
            )
            session.add(job)
            session.commit()
        
        # Upload document to PHI storage
        phi_storage = LocalStorageBackend(base_path=phi_dir)
        asyncio.run(phi_storage.upload(input_key, sample_tiff_bytes, "image/tiff"))
        
        # Patch storage factory to use our temp directories
        from unittest.mock import patch
        from src.storage.factory import create_storage_backend
        
        def mock_storage_factory(bucket_type):
            if bucket_type == "phi":
                return LocalStorageBackend(base_path=phi_dir)
            else:
                return LocalStorageBackend(base_path=clean_dir)
        
        # Patch DatabaseSessionManager to use our test database
        with patch('src.tasks.create_storage_backend', side_effect=mock_storage_factory), \
             patch('src.tasks.DatabaseSessionManager', return_value=sync_db_manager), \
             patch('src.tasks.celery_settings') as mock_celery_settings:
            
            # Use eager mode
            mock_celery_settings.CELERY_TASK_ALWAYS_EAGER = True
            mock_celery_settings.CELERY_TASK_MAX_RETRIES = 3
            mock_celery_settings.CELERY_TASK_TIME_LIMIT = 3600
            mock_celery_settings.CELERY_TASK_SOFT_TIME_LIMIT = 3300
            
            # Execute task
            result = deidentify_document_task(
                job_id=job_id,
                input_key=input_key,
                masking_level="safe_harbor",
                ocr_provider="mock",
                phi_provider="mock"
            )
        
        # Verify result
        assert result["status"] == "success"
        assert result["job_id"] == job_id
        assert result["pages_processed"] > 0
        
        # Verify job was updated in database using SYNC session
        with sync_db_manager.get_sync_session() as session:
            job = session.get(Job, job_id)
            assert job.status == JobStatus.COMPLETE
            assert job.started_at is not None
            assert job.completed_at is not None
            assert job.pages_processed > 0
            assert job.output_key is not None
            assert job.processing_time_ms is not None
        
        # Verify masked document exists in clean storage
        clean_storage = LocalStorageBackend(base_path=clean_dir)
        asyncio.run(clean_storage.exists(result["output_key"]))
        
        # Verify original was deleted from PHI storage
        assert not asyncio.run(phi_storage.exists(input_key))
    
    @pytest.mark.asyncio
    async def test_pipeline_execution_with_mock_services(self, sample_tiff_bytes):
        """Test pipeline helper function with mock services."""
        result = await _run_deidentification_pipeline(
            document_bytes=sample_tiff_bytes,
            masking_level="safe_harbor",
            ocr_provider="mock",
            phi_provider="mock"
        )
        
        # Debug: print errors if status is failure
        if result.status == "failure":
            print(f"Pipeline failed with errors: {result.errors}")
        
        assert result.status == "success", f"Pipeline failed: {result.errors}"
        assert result.pages_processed > 0
        assert result.masked_image_bytes is not None
        assert len(result.masked_image_bytes) > 0
        assert result.phi_entities_count >= 0
        assert result.processing_time_ms > 0
    
    @pytest.mark.asyncio
    async def test_pipeline_with_different_masking_levels(self, sample_tiff_bytes):
        """Test pipeline with different masking levels."""
        for masking_level in ["safe_harbor", "limited_dataset"]:
            result = await _run_deidentification_pipeline(
                document_bytes=sample_tiff_bytes,
                masking_level=masking_level,
                ocr_provider="mock",
                phi_provider="mock"
            )
            
            assert result.status == "success"
            assert result.pages_processed > 0
    
    @pytest.mark.asyncio
    async def test_pipeline_handles_invalid_masking_level(self, sample_tiff_bytes):
        """Test pipeline fails gracefully with invalid masking level."""
        with pytest.raises(KeyError):
            await _run_deidentification_pipeline(
                document_bytes=sample_tiff_bytes,
                masking_level="invalid_level",
                ocr_provider="mock",
                phi_provider="mock"
            )
    
    def test_storage_isolation_between_phi_and_clean(
        self,
        sync_db_manager,
        temp_storage_dirs,
        sample_tiff_bytes
    ):
        """Test that PHI and clean storage are properly isolated."""
        phi_dir, clean_dir = temp_storage_dirs
        
        job_id = str(uuid.uuid4())
        input_key = f"input/{job_id}.tiff"
        
        # Create job using SYNC session
        with sync_db_manager.get_sync_session() as session:
            job = Job(
                id=job_id,
                status=JobStatus.PENDING,
                ocr_provider="mock",
                phi_provider="mock",
                masking_level="safe_harbor",
                input_key=input_key,
            )
            session.add(job)
            session.commit()
        
        # Upload to PHI
        phi_storage = LocalStorageBackend(base_path=phi_dir)
        asyncio.run(phi_storage.upload(input_key, sample_tiff_bytes, "image/tiff"))
        
        # Verify file is only in PHI, not in clean
        clean_storage = LocalStorageBackend(base_path=clean_dir)
        assert asyncio.run(phi_storage.exists(input_key))
        assert not asyncio.run(clean_storage.exists(input_key))
        
        # Run task
        from unittest.mock import patch
        
        def mock_storage_factory(bucket_type):
            return LocalStorageBackend(base_path=phi_dir if bucket_type == "phi" else clean_dir)
        
        with patch('src.tasks.create_storage_backend', side_effect=mock_storage_factory), \
             patch('src.tasks.DatabaseSessionManager', return_value=sync_db_manager), \
             patch('src.tasks.celery_settings') as mock_settings:
            
            mock_settings.CELERY_TASK_ALWAYS_EAGER = True
            mock_settings.CELERY_TASK_MAX_RETRIES = 3
            mock_settings.CELERY_TASK_TIME_LIMIT = 3600
            mock_settings.CELERY_TASK_SOFT_TIME_LIMIT = 3300
            
            result = deidentify_document_task(
                job_id=job_id,
                input_key=input_key,
                masking_level="safe_harbor",
                ocr_provider="mock",
                phi_provider="mock"
            )
        
        # Verify output is only in clean, not in PHI
        output_key = result["output_key"]
        assert asyncio.run(clean_storage.exists(output_key))
        assert not asyncio.run(phi_storage.exists(output_key))
        
        # Verify input was deleted from PHI
        assert not asyncio.run(phi_storage.exists(input_key))