import pytest
from datetime import datetime, timezone
import uuid

from src.db.models import Job, JobStatus, Base
from src.db.session import DatabaseSessionManager


@pytest.fixture
async def db_manager():
    """Create an in-memory SQLite database session manager for testing."""
    manager = DatabaseSessionManager(
        database_url="sqlite+aiosqlite:///:memory:",
        echo=False
    )
    
    # Create tables using the async engine
    async with manager.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield manager
    
    # Cleanup
    await manager.close()


class TestJobModel:
    """Test suite for Job database model."""
    
    @pytest.mark.asyncio
    async def test_create_job(self, db_manager):
        """Test creating a new job record."""
        job_id = str(uuid.uuid4())
        
        async with db_manager.get_session() as session:
            job = Job(
                id=job_id,
                status=JobStatus.PENDING,
                provider="azure",
                masking_level="safe_harbor",
                input_key="input/test.tiff"
            )
            
            session.add(job)
            await session.commit()
            await session.refresh(job)
            
            # Verify job was created
            assert job.id == job_id
            assert job.status == JobStatus.PENDING
            assert job.provider == "azure"
            assert job.masking_level == "safe_harbor"
            assert job.input_key == "input/test.tiff"
            assert job.output_key is None
            assert job.retry_count == 0
            assert job.created_at is not None
    
    @pytest.mark.asyncio
    async def test_query_job(self, db_manager):
        """Test querying a job by ID."""
        job_id = str(uuid.uuid4())
        
        # Create job
        async with db_manager.get_session() as session:
            job = Job(
                id=job_id,
                status=JobStatus.PENDING,
                provider="aws",
                masking_level="limited_dataset",
                input_key="input/test.tiff"
            )
            session.add(job)
            await session.commit()
        
        # Query job in a new session
        async with db_manager.get_session() as session:
            result = await session.get(Job, job_id)
            
            assert result is not None
            assert result.id == job_id
            assert result.status == JobStatus.PENDING
            assert result.provider == "aws"
    
    @pytest.mark.asyncio
    async def test_update_job_status(self, db_manager):
        """Test updating job status."""
        job_id = str(uuid.uuid4())
        
        # Create job
        async with db_manager.get_session() as session:
            job = Job(
                id=job_id,
                status=JobStatus.PENDING,
                provider="azure",
                masking_level="safe_harbor",
                input_key="input/test.tiff"
            )
            session.add(job)
            await session.commit()
        
        # Update to processing
        async with db_manager.get_session() as session:
            job = await session.get(Job, job_id)
            job.status = JobStatus.PROCESSING
            job.started_at = datetime.now(timezone.utc)
            await session.commit()
        
        # Verify update
        async with db_manager.get_session() as session:
            job = await session.get(Job, job_id)
            assert job.status == JobStatus.PROCESSING
            assert job.started_at is not None
    
    @pytest.mark.asyncio
    async def test_complete_job(self, db_manager):
        """Test completing a job with results."""
        job_id = str(uuid.uuid4())
        
        # Create job
        async with db_manager.get_session() as session:
            job = Job(
                id=job_id,
                status=JobStatus.PENDING,
                provider="azure",
                masking_level="safe_harbor",
                input_key="input/test.tiff"
            )
            session.add(job)
            await session.commit()
        
        # Complete job
        async with db_manager.get_session() as session:
            job = await session.get(Job, job_id)
            job.status = JobStatus.COMPLETE
            job.output_key = "output/test.tiff"
            job.pages_processed = 10
            job.phi_entities_masked = 25
            job.processing_time_ms = 1500.5
            job.completed_at = datetime.now(timezone.utc)
            await session.commit()
        
        # Verify completion
        async with db_manager.get_session() as session:
            job = await session.get(Job, job_id)
            assert job.status == JobStatus.COMPLETE
            assert job.output_key == "output/test.tiff"
            assert job.pages_processed == 10
            assert job.phi_entities_masked == 25
            assert job.processing_time_ms == 1500.5
            assert job.completed_at is not None
    
    @pytest.mark.asyncio
    async def test_failed_job(self, db_manager):
        """Test marking a job as failed with error message."""
        job_id = str(uuid.uuid4())
        
        # Create job
        async with db_manager.get_session() as session:
            job = Job(
                id=job_id,
                status=JobStatus.PENDING,
                provider="azure",
                masking_level="safe_harbor",
                input_key="input/test.tiff"
            )
            session.add(job)
            await session.commit()
        
        # Mark as failed
        async with db_manager.get_session() as session:
            job = await session.get(Job, job_id)
            job.status = JobStatus.FAILED
            job.error_message = "Processing failed: Invalid TIFF format"
            job.retry_count = 1
            job.completed_at = datetime.now(timezone.utc)
            await session.commit()
        
        # Verify failure
        async with db_manager.get_session() as session:
            job = await session.get(Job, job_id)
            assert job.status == JobStatus.FAILED
            assert job.error_message == "Processing failed: Invalid TIFF format"
            assert job.retry_count == 1
    
    @pytest.mark.asyncio
    async def test_query_jobs_by_status(self, db_manager):
        """Test querying jobs by status."""
        from sqlalchemy import select
        
        # Create multiple jobs with different statuses
        async with db_manager.get_session() as session:
            pending_job = Job(
                id=str(uuid.uuid4()),
                status=JobStatus.PENDING,
                provider="azure",
                masking_level="safe_harbor",
                input_key="input/pending.tiff"
            )
            complete_job = Job(
                id=str(uuid.uuid4()),
                status=JobStatus.COMPLETE,
                provider="aws",
                masking_level="limited_dataset",
                input_key="input/complete.tiff"
            )
            
            session.add(pending_job)
            session.add(complete_job)
            await session.commit()
        
        # Query pending jobs
        async with db_manager.get_session() as session:
            stmt = select(Job).where(Job.status == JobStatus.PENDING)
            result = await session.execute(stmt)
            pending_jobs = result.scalars().all()
            
            assert len(pending_jobs) == 1
            assert pending_jobs[0].status == JobStatus.PENDING
    
    @pytest.mark.asyncio
    async def test_job_timestamps(self, db_manager):
        """Test that timestamps are properly set."""
        job_id = str(uuid.uuid4())
        
        async with db_manager.get_session() as session:
            job = Job(
                id=job_id,
                status=JobStatus.PENDING,
                provider="azure",
                masking_level="safe_harbor",
                input_key="input/test.tiff"
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)
            
            # Verify created_at was set automatically
            assert job.created_at is not None
            assert isinstance(job.created_at, datetime)
            
            # Other timestamps should be null
            assert job.started_at is None
            assert job.completed_at is None
    
    @pytest.mark.asyncio
    async def test_nullable_fields(self, db_manager):
        """Test that optional fields can be null."""
        job_id = str(uuid.uuid4())
        
        async with db_manager.get_session() as session:
            job = Job(
                id=job_id,
                status=JobStatus.PENDING,
                provider="azure",
                masking_level="safe_harbor",
                input_key="input/test.tiff"
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)
            
            # These should all be None for a new job
            assert job.output_key is None
            assert job.pages_processed is None
            assert job.phi_entities_masked is None
            assert job.processing_time_ms is None
            assert job.error_message is None
            assert job.started_at is None
            assert job.completed_at is None
    
    @pytest.mark.asyncio
    async def test_session_rollback_on_error(self, db_manager):
        """Test that sessions rollback on error."""
        job_id = str(uuid.uuid4())
        
        # This should rollback due to duplicate ID
        with pytest.raises(Exception):
            async with db_manager.get_session() as session:
                job1 = Job(
                    id=job_id,
                    status=JobStatus.PENDING,
                    provider="azure",
                    masking_level="safe_harbor",
                    input_key="input/test1.tiff"
                )
                session.add(job1)
                await session.commit()
            
            # Try to add same ID again - should fail
            async with db_manager.get_session() as session:
                job2 = Job(
                    id=job_id,  # Duplicate!
                    status=JobStatus.PENDING,
                    provider="azure",
                    masking_level="safe_harbor",
                    input_key="input/test2.tiff"
                )
                session.add(job2)
                await session.commit()
    
    @pytest.mark.asyncio
    async def test_provider_tracking(self, db_manager):
        """Test that provider and masking level are tracked correctly."""
        job_id = str(uuid.uuid4())
        
        async with db_manager.get_session() as session:
            job = Job(
                id=job_id,
                status=JobStatus.PENDING,
                provider="aws",
                masking_level="custom",
                input_key="input/test.tiff"
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)
            
            assert job.provider == "aws"
            assert job.masking_level == "custom"