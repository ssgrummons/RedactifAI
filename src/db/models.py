from sqlalchemy import String, Text, Integer, Float, DateTime, Enum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from datetime import datetime, timezone
from typing import Optional
import enum


class Base(DeclarativeBase):
    """Base class for all database models."""
    pass


class JobStatus(enum.Enum):
    """Status values for jobs."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"


class Job(Base):
    """Database model for de-identification jobs."""
    __tablename__ = "jobs"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.PENDING)
    
    # Storage keys
    input_key: Mapped[str] = mapped_column(String(512))
    output_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    
    # Metadata
    pages_processed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    phi_entities_masked: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    processing_time_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    # Error tracking
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc)
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)