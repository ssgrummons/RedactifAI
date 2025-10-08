"""Celery tasks for asynchronous document de-identification."""

import asyncio
import uuid
import logging
from datetime import datetime, timezone
from celery import Celery
from celery.exceptions import MaxRetriesExceededError

from src.config.celery_settings import CelerySettings
from src.config.database import DatabaseSettings
from src.config.provider import ProviderSettings
from src.db.session import DatabaseSessionManager
from src.db.models import Job, JobStatus, PHIEntity
from src.storage.factory import create_storage_backend
from src.services.service_factory import create_ocr_service, create_phi_service
from src.services.deidentification_service import DeidentificationService
from src.services.entity_matcher import EntityMatcher
from src.services.image_masking_service import ImageMaskingService
from src.utils.tiff_processor import TIFFProcessor
from src.models.domain import MaskingLevel

logger = logging.getLogger(__name__)

# Load settings
celery_settings = CelerySettings()
db_settings = DatabaseSettings()
provider_settings = ProviderSettings()

# Initialize Celery app
celery_app = Celery('redactifai')

celery_app.conf.update(
    broker_url=celery_settings.CELERY_BROKER_URL,
    result_backend=celery_settings.CELERY_RESULT_BACKEND,
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=celery_settings.CELERY_TASK_TIME_LIMIT,
    task_soft_time_limit=celery_settings.CELERY_TASK_SOFT_TIME_LIMIT,
    task_acks_late=True,  # Acknowledge after task completes, not before
    worker_prefetch_multiplier=1,  # Process one task at a time per worker
    task_always_eager=celery_settings.CELERY_TASK_ALWAYS_EAGER,  # For testing
)


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,  # Exponential backoff
    retry_backoff_max=600,  # Max 10 minutes between retries
    retry_jitter=True,  # Add randomness to avoid thundering herd
    max_retries=celery_settings.CELERY_TASK_MAX_RETRIES,
)
def deidentify_document_task(
    self,
    job_id: str,
    input_key: str,
    masking_level: str,
    ocr_provider: str,
    phi_provider: str
):
    """
    Celery task for document de-identification.
    
    This is a SYNC function that wraps the async deidentification pipeline.
    Uses sync database sessions and asyncio.run() to call async code.
    
    Args:
        self: Celery task instance (bind=True)
        job_id: UUID of the job in database
        input_key: Storage key for input document (PHI bucket)
        masking_level: "safe_harbor", "limited_dataset", or "custom"
        provider: "azure", "aws", or "mock"
    
    Process:
        1. Update job status to PROCESSING
        2. Download document from PHI storage
        3. Run async deidentification pipeline
        4. Upload masked document to clean storage
        5. Delete original from PHI storage
        6. Update job status to COMPLETE with metadata
        
    On error:
        - Celery auto-retries with exponential backoff
        - After max retries, marks job as FAILED
    """
    # Initialize database session manager
    db_manager = DatabaseSessionManager(
        database_url=db_settings.connection_string,
        echo=False
    )
    
    try:
        # Update job status to PROCESSING
        with db_manager.get_sync_session() as session:
            job = session.get(Job, job_id)
            if not job:
                raise ValueError(f"Job {job_id} not found in database")
            
            job.status = JobStatus.PROCESSING
            job.started_at = datetime.now(timezone.utc)
            job.retry_count = self.request.retries
            session.commit()
            
            logger.info(f"Job {job_id}: Starting processing (attempt {self.request.retries + 1})")
        
        # Create storage backends
        phi_storage = create_storage_backend("phi")
        clean_storage = create_storage_backend("clean")
        
        # Download document from PHI storage
        logger.info(f"Job {job_id}: Downloading from PHI storage: {input_key}")
        document_bytes = asyncio.run(phi_storage.download(input_key))
        
        # Run async deidentification pipeline
        logger.info(f"Job {job_id}: Running deidentification pipeline")
        result = asyncio.run(_run_deidentification_pipeline(
            document_bytes=document_bytes,
            masking_level=masking_level,
            ocr_provider=ocr_provider,
            phi_provider=phi_provider
        ))
        
        if result.status != "success":
            raise RuntimeError(f"Deidentification failed: {result.errors}")
        
        # Upload to clean storage
        output_key = f"masked/{job_id}.tiff"
        logger.info(f"Job {job_id}: Uploading to clean storage: {output_key}")
        asyncio.run(clean_storage.upload(
            key=output_key,
            data=result.masked_image_bytes,
            content_type="image/tiff"
        ))
        
        # Delete from PHI storage
        logger.info(f"Job {job_id}: Deleting from PHI storage: {input_key}")
        asyncio.run(phi_storage.delete(input_key))
        
        # Update job status to COMPLETE
        with db_manager.get_sync_session() as session:
            job = session.get(Job, job_id)
            job.status = JobStatus.COMPLETE
            job.output_key = output_key
            job.pages_processed = result.pages_processed
            job.phi_entities_masked = result.entities_masked
            job.processing_time_ms = result.processing_time_ms
            job.completed_at = datetime.now(timezone.utc)
            
            # Save PHI entities to database
            for entity in result.phi_entities:
                # Get bounding box from first mask region for this entity
                # (entities can have multiple masks if multi-line, we'll use first)
                mask_region = next(
                    (mr for mr in result.mask_regions if mr.entity_category == entity.category),
                    None
                )
                
                phi_entity = PHIEntity(
                    job_id=job_id,
                    text=entity.text,
                    category=entity.category,
                    subcategory=entity.subcategory, 
                    page=mask_region.page if mask_region else 1,
                    confidence=entity.confidence,
                    offset=entity.offset,
                    length=entity.length,
                    bbox_x=mask_region.bounding_box.x if mask_region else 0.0,
                    bbox_y=mask_region.bounding_box.y if mask_region else 0.0,
                    bbox_width=mask_region.bounding_box.width if mask_region else 0.0,
                    bbox_height=mask_region.bounding_box.height if mask_region else 0.0,
                )
                session.add(phi_entity)
            
            session.commit()
            
            logger.info(
                f"Job {job_id}: Completed successfully. "
                f"Pages: {result.pages_processed}, Entities: {result.entities_masked}, "
                f"Time: {result.processing_time_ms:.1f}ms"
            )
        
        return {
            "job_id": job_id,
            "status": "success",
            "output_key": output_key,
            "pages_processed": result.pages_processed,
            "entities_masked": result.entities_masked,
        }
        
    except MaxRetriesExceededError:
        # Max retries exceeded - mark as FAILED
        logger.error(f"Job {job_id}: Max retries exceeded")
        with db_manager.get_sync_session() as session:
            job = session.get(Job, job_id)
            job.status = JobStatus.FAILED
            job.error_message = f"Max retries ({celery_settings.CELERY_TASK_MAX_RETRIES}) exceeded"
            job.completed_at = datetime.now(timezone.utc)
            session.commit()
        raise
        
    except Exception as e:
        logger.warning(f"Job {job_id}: Error on attempt {self.request.retries + 1}: {str(e)}")
        
        with db_manager.get_sync_session() as session:
            job = session.get(Job, job_id)
            if job:  # <-- Add this null check
                job.retry_count = self.request.retries + 1
                
                # If this will be the last retry, mark as FAILED
                if self.request.retries + 1 >= celery_settings.CELERY_TASK_MAX_RETRIES:
                    job.status = JobStatus.FAILED
                    job.error_message = str(e)
                    job.completed_at = datetime.now(timezone.utc)
                
                session.commit()
        
        # Re-raise to trigger Celery retry
        raise


async def _run_deidentification_pipeline(
    document_bytes: bytes,
    masking_level: str,
    ocr_provider: str,
    phi_provider: str
):
    """
    Run the async deidentification pipeline.
    
    This is a helper function that encapsulates all async operations.
    Called via asyncio.run() from the sync Celery task.
    
    Args:
        document_bytes: Input document bytes
        masking_level: Masking level string
        provider: Provider string
        
    Returns:
        DeidentificationResult
    """
    # Create services using factory
    ocr_service = create_ocr_service(ocr_provider)
    phi_service = create_phi_service(phi_provider)
    
    # Create supporting services
    entity_matcher = EntityMatcher()
    image_masking_service = ImageMaskingService()
    document_processor = TIFFProcessor()
    
    # Convert masking level string to enum
    masking_level_enum = MaskingLevel[masking_level.upper()]
    
    # Create deidentification service
    deidentification_service = DeidentificationService(
        ocr_service=ocr_service,
        phi_detection_service=phi_service,
        entity_matcher=entity_matcher,
        image_masking_service=image_masking_service,
        document_processor=document_processor,
    )
    
    # Run pipeline
    async with deidentification_service:
        result = await deidentification_service.deidentify_document(
            document_bytes=document_bytes,
            masking_level=masking_level_enum,
            output_format="image/tiff",
        )
    
    return result