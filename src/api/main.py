"""FastAPI application for RedactifAI document de-identification service."""

import uuid
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from src.api.dependencies import (
    initialize_dependencies,
    cleanup_dependencies,
    get_db_session,
    get_phi_storage,
    get_clean_storage,
    get_general_settings,
    get_provider_settings,
    verify_authentication,
)
from src.api.schemas import (
    CreateJobRequest,
    CreateJobResponse,
    JobStatusResponse,
    JobListResponse,
    JobListItem,
    JobStatusEnum,
    MaskingLevelEnum,
)
from src.db.models import Job, JobStatus
from src.storage.base import StorageBackend
from src.config.settings import Settings
from src.config.provider import ProviderSettings
from src.tasks import deidentify_document_task

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup/shutdown."""
    # Startup
    logger.info("Initializing RedactifAI API...")
    initialize_dependencies()
    logger.info("API ready")
    
    yield
    
    # Shutdown
    logger.info("Shutting down API...")
    await cleanup_dependencies()
    logger.info("API shutdown complete")


app = FastAPI(
    title="RedactifAI",
    description="HIPAA-compliant document de-identification service",
    version="1.0.0",
    lifespan=lifespan,
)


@app.post(
    "/api/v1/jobs",
    response_model=CreateJobResponse,
    status_code=201,
    summary="Submit document for de-identification",
    description="Upload a document (TIFF/PDF) and create a de-identification job",
)
async def create_job(
    request: Request,
    file: UploadFile = File(..., description="Document to de-identify"),
    masking_level: MaskingLevelEnum = Query(
        default=MaskingLevelEnum.SAFE_HARBOR,
        description="HIPAA de-identification level"
    ),
    authenticated: bool = Depends(verify_authentication),
    db: Session = Depends(get_db_session),
    phi_storage: StorageBackend = Depends(get_phi_storage),
    settings: Settings = Depends(get_general_settings),
    provider_settings: ProviderSettings = Depends(get_provider_settings),
):
    """
    Create a new de-identification job.
    
    Process:
    1. Validate file size
    2. Upload to PHI storage
    3. Create job record in database
    4. Enqueue Celery task
    5. Return job ID
    """
    # Validate file type
    if not file.content_type:
        raise HTTPException(400, "Unable to determine file type")
    
    if file.content_type not in ["image/tiff", "image/tif", "application/pdf"]:
        raise HTTPException(
            400,
            f"Unsupported file type: {file.content_type}. Supported: TIFF, PDF"
        )
    
    # Read file
    file_bytes = await file.read()
    
    # Validate file size
    file_size_mb = len(file_bytes) / (1024 * 1024)
    if file_size_mb > settings.MAX_FILE_SIZE_MB:
        raise HTTPException(
            413,
            f"File too large: {file_size_mb:.1f}MB. Maximum: {settings.MAX_FILE_SIZE_MB}MB"
        )
    
    # Generate job ID
    job_id = str(uuid.uuid4())
    
    # Upload to PHI storage
    input_key = f"input/{job_id}.tiff"
    try:
        await phi_storage.upload(
            key=input_key,
            data=file_bytes,
            content_type=file.content_type
        )
    except Exception as e:
        logger.error(f"Failed to upload to PHI storage: {e}")
        raise HTTPException(500, "Failed to upload document")
    
    # Create job record
    try:
        job = Job(
            id=job_id,
            status=JobStatus.PENDING,
            ocr_provider=provider_settings.OCR_PROVIDER,
            phi_provider=provider_settings.PHI_PROVIDER,
            masking_level=masking_level.value,
            input_key=input_key,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
    except Exception as e:
        logger.error(f"Failed to create job record: {e}")
        # Clean up uploaded file
        try:
            await phi_storage.delete(input_key)
        except:
            pass
        raise HTTPException(500, "Failed to create job")
    
    # Enqueue Celery task
    try:
        deidentify_document_task.delay(
            job_id=job_id,
            input_key=input_key,
            masking_level=masking_level.value,
            ocr_provider=provider_settings.OCR_PROVIDER,
            phi_provider=provider_settings.PHI_PROVIDER,
        )
    except Exception as e:
        logger.error(f"Failed to enqueue task: {e}")
        # Job still exists in DB with PENDING status
        # User can retry or admin can manually trigger
        raise HTTPException(500, "Failed to enqueue processing task")
    
    logger.info(f"Created job {job_id} with masking level {masking_level.value}")
    
    return CreateJobResponse(
        job_id=job_id,
        status=JobStatusEnum(job.status.value),
        created_at=job.created_at,
    )


@app.get(
    "/api/v1/jobs/{job_id}",
    response_model=JobStatusResponse,
    summary="Get job status",
    description="Retrieve detailed status and metadata for a job",
)
async def get_job_status(
    job_id: str,
    authenticated: bool = Depends(verify_authentication),
    db: Session = Depends(get_db_session),
):
    """Get detailed job status and metadata."""
    job = db.get(Job, job_id)
    
    if not job:
        raise HTTPException(404, f"Job {job_id} not found")
    
    return JobStatusResponse(
        job_id=job.id,
        status=JobStatusEnum(job.status.value),
        provider=job.ocr_provider,
        masking_level=job.masking_level,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        pages_processed=job.pages_processed,
        phi_entities_masked=job.phi_entities_masked,
        processing_time_ms=job.processing_time_ms,
        error_message=job.error_message,
        retry_count=job.retry_count,
    )


@app.get(
    "/api/v1/jobs",
    response_model=JobListResponse,
    summary="List jobs",
    description="Retrieve paginated list of jobs with optional status filtering",
)
async def list_jobs(
    status: Optional[JobStatusEnum] = Query(None, description="Filter by job status"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(10, ge=1, le=100, description="Items per page"),
    authenticated: bool = Depends(verify_authentication),
    db: Session = Depends(get_db_session),
):
    """
    List jobs with pagination and optional status filtering.
    
    Returns jobs ordered by creation time (newest first).
    """
    # Build query
    query = select(Job)
    
    # Apply status filter
    if status:
        query = query.where(Job.status == JobStatus[status.name])
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = db.execute(count_query).scalar()
    
    # Apply pagination
    offset = (page - 1) * page_size
    query = query.order_by(Job.created_at.desc()).offset(offset).limit(page_size)
    
    # Execute query
    result = db.execute(query)
    jobs = result.scalars().all()
    
    # Convert to response
    job_items = [
        JobListItem(
            job_id=job.id,
            status=JobStatusEnum(job.status.value),
            masking_level=job.masking_level,
            created_at=job.created_at,
            completed_at=job.completed_at,
            pages_processed=job.pages_processed,
        )
        for job in jobs
    ]
    
    return JobListResponse(
        jobs=job_items,
        total=total,
        page=page,
        page_size=page_size,
    )


@app.get(
    "/api/v1/jobs/{job_id}/download",
    summary="Download de-identified document",
    description="Download the processed document (only available for completed jobs)",
)
async def download_result(
    job_id: str,
    authenticated: bool = Depends(verify_authentication),
    db: Session = Depends(get_db_session),
    clean_storage: StorageBackend = Depends(get_clean_storage),
):
    """
    Download de-identified document.
    
    Returns the masked document as a streaming response.
    Only available for completed jobs.
    """
    # Get job
    job = db.get(Job, job_id)
    
    if not job:
        raise HTTPException(404, f"Job {job_id} not found")
    
    # Check job status
    if job.status != JobStatus.COMPLETE:
        raise HTTPException(
            400,
            f"Job not complete. Current status: {job.status.value}"
        )
    
    # Check output exists
    if not job.output_key:
        raise HTTPException(500, "Job marked complete but no output file found")
    
    # Download from clean storage
    try:
        document_bytes = await clean_storage.download(job.output_key)
    except FileNotFoundError:
        logger.error(f"Output file not found for job {job_id}: {job.output_key}")
        raise HTTPException(500, "Output file not found in storage")
    except Exception as e:
        logger.error(f"Failed to download output for job {job_id}: {e}")
        raise HTTPException(500, "Failed to download document")
    
    # Return as streaming response
    def iter_bytes():
        yield document_bytes
    
    return StreamingResponse(
        iter_bytes(),
        media_type="image/tiff",
        headers={
            "Content-Disposition": f"attachment; filename=redacted_{job_id}.tiff"
        }
    )


@app.get(
    "/health",
    summary="Health check",
    description="Check if API is running",
)
async def health_check():
    """Simple health check endpoint."""
    return {"status": "healthy"}
