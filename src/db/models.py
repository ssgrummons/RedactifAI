from sqlalchemy import String, Text, Integer, Float, DateTime, Enum, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from datetime import datetime, timezone
from typing import Optional, List
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
    
    # Provider tracking
    ocr_provider: Mapped[str] = mapped_column(String(32))  # azure | aws | mock
    phi_provider: Mapped[str] = mapped_column(String(32))  # azure | aws | mock
    masking_level: Mapped[str] = mapped_column(String(32))  # safe_harbor | limited_dataset | custom
    
    # Storage keys (input = PHI bucket, output = clean bucket)
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
    
    # Relationship to PHI entities
    phi_entities: Mapped[List["PHIEntity"]] = relationship(
        "PHIEntity",
        back_populates="job",
        cascade="all, delete-orphan"
    )


class PHIEntity(Base):
    """Database model for detected PHI entities."""
    __tablename__ = "phi_entities"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    
    # Entity details
    text: Mapped[str] = mapped_column(Text)  # Actual PHI text (SENSITIVE!)
    category: Mapped[str] = mapped_column(String(64))  # Person, Date, Phone, etc.
    subcategory: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    page: Mapped[int] = mapped_column(Integer)  # Page number (1-indexed)
    confidence: Mapped[float] = mapped_column(Float)  # Detection confidence (0.0-1.0)
    
    # Position information (character offsets in original text)
    offset: Mapped[int] = mapped_column(Integer)
    length: Mapped[int] = mapped_column(Integer)
    
    # Bounding box (pixel coordinates)
    bbox_x: Mapped[float] = mapped_column(Float)
    bbox_y: Mapped[float] = mapped_column(Float)
    bbox_width: Mapped[float] = mapped_column(Float)
    bbox_height: Mapped[float] = mapped_column(Float)
    
    # Relationship back to job
    job: Mapped["Job"] = relationship("Job", back_populates="phi_entities")