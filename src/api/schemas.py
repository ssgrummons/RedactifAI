"""Pydantic schemas for API request/response models."""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class JobStatusEnum(str, Enum):
    """Job status values for API responses."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"


class MaskingLevelEnum(str, Enum):
    """Masking level options."""
    SAFE_HARBOR = "safe_harbor"
    LIMITED_DATASET = "limited_dataset"
    CUSTOM = "custom"


class CreateJobRequest(BaseModel):
    """Request body for creating a job (multipart form data)."""
    masking_level: MaskingLevelEnum = Field(
        default=MaskingLevelEnum.SAFE_HARBOR,
        description="HIPAA de-identification level"
    )
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "masking_level": "safe_harbor"
            }
        }
    }


class CreateJobResponse(BaseModel):
    """Response for job creation."""
    job_id: str = Field(..., description="Unique job identifier")
    status: JobStatusEnum = Field(..., description="Current job status")
    created_at: datetime = Field(..., description="Job creation timestamp")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "job_id": "123e4567-e89b-12d3-a456-426614174000",
                "status": "pending",
                "created_at": "2025-10-01T12:00:00Z"
            }
        }
    }


class JobStatusResponse(BaseModel):
    """Response for job status query."""
    job_id: str
    status: JobStatusEnum
    provider: str
    masking_level: str
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    pages_processed: Optional[int] = None
    phi_entities_masked: Optional[int] = None
    processing_time_ms: Optional[float] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "job_id": "123e4567-e89b-12d3-a456-426614174000",
                "status": "complete",
                "provider": "azure",
                "masking_level": "safe_harbor",
                "created_at": "2025-10-01T12:00:00Z",
                "started_at": "2025-10-01T12:00:05Z",
                "completed_at": "2025-10-01T12:00:15Z",
                "pages_processed": 5,
                "phi_entities_masked": 23,
                "processing_time_ms": 8543.2,
                "error_message": None,
                "retry_count": 0
            }
        }
    }


class JobListItem(BaseModel):
    """Simplified job info for list endpoint."""
    job_id: str
    status: JobStatusEnum
    masking_level: str
    created_at: datetime
    completed_at: Optional[datetime] = None
    pages_processed: Optional[int] = None


class JobListResponse(BaseModel):
    """Response for job list query."""
    jobs: List[JobListItem]
    total: int = Field(..., description="Total number of jobs matching filters")
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description="Number of items per page")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "jobs": [
                    {
                        "job_id": "123e4567-e89b-12d3-a456-426614174000",
                        "status": "complete",
                        "masking_level": "safe_harbor",
                        "created_at": "2025-10-01T12:00:00Z",
                        "completed_at": "2025-10-01T12:00:15Z",
                        "pages_processed": 5
                    }
                ],
                "total": 42,
                "page": 1,
                "page_size": 10
            }
        }
    }


class ErrorResponse(BaseModel):
    """Standard error response."""
    detail: str = Field(..., description="Error message")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "detail": "Job not found"
            }
        }
    }