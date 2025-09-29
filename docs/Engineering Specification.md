# Redactify - Engineering Specification & Implementation Plan

**Make it so.**

---

## Project Overview

**Name:** Redactify  
**Tagline:** Open-source medical document de-identification service  
**License:** MIT  
**Language:** Python 3.11+  
**Dependency Management:** Poetry

**What it does:** Accepts TIFF medical records via REST API, detects and masks PHI using Azure Document Intelligence, returns sanitized TIFF asynchronously.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         API Layer (FastAPI)                     │
│  POST /jobs          - Submit TIFF for processing              │
│  GET  /jobs/{id}     - Get job status                          │
│  GET  /jobs/{id}/result - Download masked TIFF                 │
│  GET  /health        - Health check                            │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ↓
┌─────────────────────────────────────────────────────────────────┐
│                    Job Queue (Celery + Redis)                   │
│  - Enqueue de-identification tasks                             │
│  - Track job state (pending/processing/complete/failed)        │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ↓
┌─────────────────────────────────────────────────────────────────┐
│                    Celery Worker Process                        │
│  1. Fetch job from queue                                       │
│  2. Download input TIFF from storage                           │
│  3. Call DeidentificationService                               │
│  4. Upload masked TIFF to storage                              │
│  5. Update job status in database                              │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ↓
┌─────────────────────────────────────────────────────────────────┐
│              DeidentificationService (Orchestrator)             │
│  - Load TIFF                                                   │
│  - Call OCR service                                            │
│  - Call PHI detection service                                  │
│  - Call masking service                                        │
│  - Return masked TIFF + metadata                               │
└─────────┬──────────────┬──────────────┬────────────────────────┘
          │              │              │
          ↓              ↓              ↓
    ┌─────────┐    ┌──────────┐   ┌──────────┐
    │   OCR   │    │   PHI    │   │  Masking │
    │ Service │    │Detection │   │  Service │
    │         │    │ Service  │   │          │
    │ Azure   │    │Azure+    │   │ Pillow   │
    │Doc Intel│    │ Regex    │   │          │
    └─────────┘    └──────────┘   └──────────┘
```

---

## Component Specifications

### 1. Storage Abstraction

**File:** `redactify/storage/base.py`

```python
from abc import ABC, abstractmethod
from typing import Optional


class StorageBackend(ABC):
    """Abstract base class for storage backends."""
    
    @abstractmethod
    async def upload(self, key: str, data: bytes, content_type: str = "image/tiff") -> str:
        """
        Upload data to storage.
        
        Args:
            key: Storage key/path
            data: Bytes to upload
            content_type: MIME type
            
        Returns:
            Storage key (may be different from input if backend modifies it)
        """
        pass
    
    @abstractmethod
    async def download(self, key: str) -> bytes:
        """
        Download data from storage.
        
        Args:
            key: Storage key/path
            
        Returns:
            File bytes
            
        Raises:
            FileNotFoundError: If key doesn't exist
        """
        pass
    
    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Check if key exists in storage."""
        pass
    
    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete key from storage."""
        pass
```

**Implementations:**

1. `redactify/storage/s3.py` - S3/MinIO via boto3
2. `redactify/storage/azure_blob.py` - Azure Blob via azure-storage-blob
3. `redactify/storage/local.py` - Local filesystem (dev only)

**Configuration (environment variables):**
```bash
STORAGE_BACKEND=s3  # s3 | azure | local
S3_ENDPOINT_URL=http://localhost:9000  # For MinIO
S3_BUCKET=redactify
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
S3_REGION=us-east-1

AZURE_STORAGE_CONNECTION_STRING=...  # For Azurite or production
AZURE_STORAGE_CONTAINER=redactify

LOCAL_STORAGE_PATH=/tmp/redactify  # For local development
```

---

### 2. Database Abstraction

**File:** `redactify/db/models.py`

```python
from sqlalchemy import String, Text, Integer, Float, DateTime, Enum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from datetime import datetime
import enum


class Base(DeclarativeBase):
    pass


class JobStatus(enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"


class Job(Base):
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
```

**File:** `redactify/db/session.py`

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from redactify.config import settings

# Support both PostgreSQL and SQLite
if settings.DATABASE_URL.startswith("sqlite"):
    engine = create_async_engine(
        settings.DATABASE_URL,
        connect_args={"check_same_thread": False}
    )
else:
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
```

**Configuration:**
```bash
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/redactify
# OR
DATABASE_URL=sqlite+aiosqlite:///./redactify.db
```

---

### 3. PHI Pattern Configuration

**File:** `redactify/config/phi_patterns.yaml`

```yaml
# Medical PHI patterns for regex-based detection
# These supplement Azure Document Intelligence's built-in PII detection

patterns:
  - name: MRN
    regex: '\b(?:MRN|Medical Record (?:Number|#|No\.?))[:\s]*([A-Z0-9]{6,12})\b'
    flags: IGNORECASE
    category: MedicalID_MRN
    
  - name: AccountNumber
    regex: '\b(?:Account|Acct\.?) (?:Number|#|No\.?)[:\s]*(\d{6,12})\b'
    flags: IGNORECASE
    category: MedicalID_Account
    
  - name: MemberID
    regex: '\b(?:Member|Insurance) ID[:\s]*([A-Z0-9]{8,15})\b'
    flags: IGNORECASE
    category: MedicalID_Member
    
  - name: SubscriberID
    regex: '\bSubscriber (?:ID|Number)[:\s]*([A-Z0-9]{8,15})\b'
    flags: IGNORECASE
    category: MedicalID_Subscriber
    
  - name: SSN_Pattern
    regex: '\b\d{3}-\d{2}-\d{4}\b'
    flags: null
    category: SSN

# Users can add custom patterns here
# custom_patterns:
#   - name: MyCustomID
#     regex: 'CUSTOM-\d{6}'
#     category: CustomIdentifier
```

**File:** `redactify/utils/medical_phi_patterns.py`

```python
import re
import yaml
from pathlib import Path
from typing import List, Tuple
from dataclasses import dataclass


@dataclass
class PHIPattern:
    name: str
    regex: re.Pattern
    category: str


class MedicalPHIPatterns:
    """Loads and manages PHI regex patterns from config."""
    
    def __init__(self, config_path: str = "redactify/config/phi_patterns.yaml"):
        self.patterns = self._load_patterns(config_path)
    
    def _load_patterns(self, config_path: str) -> List[PHIPattern]:
        path = Path(config_path)
        if not path.exists():
            # Return empty list if no custom patterns
            return []
        
        with open(path) as f:
            config = yaml.safe_load(f)
        
        patterns = []
        for pattern_config in config.get("patterns", []):
            flags = 0
            if pattern_config.get("flags") == "IGNORECASE":
                flags = re.IGNORECASE
            
            patterns.append(PHIPattern(
                name=pattern_config["name"],
                regex=re.compile(pattern_config["regex"], flags),
                category=pattern_config["category"]
            ))
        
        return patterns
    
    def get_patterns(self) -> List[Tuple[str, re.Pattern]]:
        """Returns list of (name, compiled_regex) tuples."""
        return [(p.name, p.regex) for p in self.patterns]
```

---

### 4. Configuration Management

**File:** `redactify/config.py`

```python
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")
    
    # API Settings
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_WORKERS: int = 1
    
    # Storage
    STORAGE_BACKEND: Literal["s3", "azure", "local"] = "s3"
    S3_ENDPOINT_URL: str = "http://localhost:9000"
    S3_BUCKET: str = "redactify"
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    S3_REGION: str = "us-east-1"
    AZURE_STORAGE_CONNECTION_STRING: str = ""
    AZURE_STORAGE_CONTAINER: str = "redactify"
    LOCAL_STORAGE_PATH: str = "/tmp/redactify"
    
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://redactify:redactify@localhost:5432/redactify"
    
    # Azure Document Intelligence
    AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT: str
    AZURE_DOCUMENT_INTELLIGENCE_KEY: str
    
    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"
    
    # Processing
    MAX_FILE_SIZE_MB: int = 50
    MASKING_PADDING_PX: int = 5
    MAX_RETRIES: int = 3
    RETRY_BACKOFF_BASE: float = 2.0  # Exponential backoff base
    
    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"  # json | text


settings = Settings()
```

**File:** `.env.example`

```bash
# API
API_HOST=0.0.0.0
API_PORT=8000

# Storage (choose one)
STORAGE_BACKEND=s3
S3_ENDPOINT_URL=http://minio:9000
S3_BUCKET=redactify
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin

# Database
DATABASE_URL=postgresql+asyncpg://redactify:redactify@postgres:5432/redactify

# Azure Document Intelligence (REQUIRED)
AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=https://your-instance.cognitiveservices.azure.com/
AZURE_DOCUMENT_INTELLIGENCE_KEY=your-key-here

# Celery
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0

# Processing
MAX_FILE_SIZE_MB=50
MASKING_PADDING_PX=5
LOG_LEVEL=INFO
```

---

### 5. API Endpoints

**File:** `redactify/api/routes.py`

```python
from fastapi import FastAPI, File, UploadFile, HTTPException, Depends
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from redactify.db.session import get_db
from redactify.db.models import Job, JobStatus
from redactify.storage import get_storage_backend
from redactify.tasks import deidentify_document_task
from redactify.config import settings
import uuid
from datetime import datetime


app = FastAPI(
    title="Redactify",
    description="Medical document de-identification service",
    version="0.1.0"
)


@app.post("/jobs", status_code=202)
async def create_job(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Submit a TIFF document for de-identification.
    
    Returns job ID for polling status.
    """
    # Validate file type
    if not file.filename.lower().endswith(('.tif', '.tiff')):
        raise HTTPException(status_code=400, detail="Only TIFF files supported")
    
    # Validate file size
    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > settings.MAX_FILE_SIZE_MB:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max size: {settings.MAX_FILE_SIZE_MB}MB"
        )
    
    # Generate job ID
    job_id = str(uuid.uuid4())
    
    # Upload input file to storage
    storage = get_storage_backend()
    input_key = f"input/{job_id}.tiff"
    await storage.upload(input_key, content)
    
    # Create job record
    job = Job(
        id=job_id,
        status=JobStatus.PENDING,
        input_key=input_key,
        created_at=datetime.utcnow()
    )
    db.add(job)
    await db.commit()
    
    # Enqueue task
    deidentify_document_task.delay(job_id)
    
    return {
        "job_id": job_id,
        "status": "pending",
        "status_url": f"/jobs/{job_id}",
        "message": "Job submitted successfully"
    }


@app.get("/jobs/{job_id}")
async def get_job_status(job_id: str, db: AsyncSession = Depends(get_db)):
    """Get job status and metadata."""
    result = await db.get(Job, job_id)
    if not result:
        raise HTTPException(status_code=404, detail="Job not found")
    
    response = {
        "job_id": result.id,
        "status": result.status.value,
        "created_at": result.created_at.isoformat(),
    }
    
    if result.status == JobStatus.PROCESSING:
        response["started_at"] = result.started_at.isoformat() if result.started_at else None
    
    if result.status == JobStatus.COMPLETE:
        response.update({
            "completed_at": result.completed_at.isoformat(),
            "result_url": f"/jobs/{job_id}/result",
            "metadata": {
                "pages_processed": result.pages_processed,
                "phi_entities_masked": result.phi_entities_masked,
                "processing_time_ms": result.processing_time_ms
            }
        })
    
    if result.status == JobStatus.FAILED:
        response["error"] = result.error_message
    
    return response


@app.get("/jobs/{job_id}/result")
async def download_result(job_id: str, db: AsyncSession = Depends(get_db)):
    """Download the masked TIFF."""
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status != JobStatus.COMPLETE:
        raise HTTPException(
            status_code=400,
            detail=f"Job not complete. Current status: {job.status.value}"
        )
    
    # Download from storage
    storage = get_storage_backend()
    try:
        masked_tiff = await storage.download(job.output_key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Result file not found")
    
    return Response(
        content=masked_tiff,
        media_type="image/tiff",
        headers={
            "Content-Disposition": f"attachment; filename=masked_{job_id}.tiff",
            "X-Job-ID": job_id,
            "X-Pages-Processed": str(job.pages_processed),
            "X-PHI-Entities-Masked": str(job.phi_entities_masked),
            "X-Processing-Time-MS": str(job.processing_time_ms)
        }
    )


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "redactify",
        "version": "0.1.0"
    }
```

---

### 6. Celery Worker

**File:** `redactify/tasks.py`

```python
from celery import Celery
from redactify.config import settings
from redactify.db.session import AsyncSessionLocal
from redactify.db.models import Job, JobStatus
from redactify.storage import get_storage_backend
from redactify.services.deidentification_service import DeidentificationService
from redactify.services.ocr_service import OCRService
from redactify.services.phi_detection_service import PHIDetectionService
from redactify.services.image_masking_service import ImageMaskingService
from redactify.utils.image_processing import ImageProcessor
from datetime import datetime
import logging
import asyncio

logger = logging.getLogger(__name__)

celery_app = Celery(
    "redactify",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max
    task_soft_time_limit=3000,  # 50 minutes soft limit
)


def get_deidentification_service():
    """Factory for creating service with all dependencies."""
    return DeidentificationService(
        ocr_service=OCRService(),
        phi_detection_service=PHIDetectionService(),
        image_masking_service=ImageMaskingService(),
        image_processor=ImageProcessor()
    )


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_kwargs={'max_retries': settings.MAX_RETRIES}
)
def deidentify_document_task(self, job_id: str):
    """
    Celery task to de-identify a document.
    Runs in worker process.
    """
    asyncio.run(_process_job(job_id, self.request.retries))


async def _process_job(job_id: str, retry_count: int):
    """Async function to process a job."""
    storage = get_storage_backend()
    
    async with AsyncSessionLocal() as db:
        # Update job status to processing
        job = await db.get(Job, job_id)
        if not job:
            logger.error(f"Job {job_id} not found")
            return
        
        job.status = JobStatus.PROCESSING
        job.started_at = datetime.utcnow()
        job.retry_count = retry_count
        await db.commit()
        
        try:
            # Download input TIFF
            logger.info(f"Processing job {job_id}")
            input_bytes = await storage.download(job.input_key)
            
            # Process document
            service = get_deidentification_service()
            result = await service.deidentify_document(job_id, input_bytes)
            
            if result.status == "failure":
                raise Exception(f"De-identification failed: {', '.join(result.errors)}")
            
            # Upload output TIFF
            output_key = f"output/{job_id}.tiff"
            await storage.upload(output_key, result.masked_tiff_bytes)
            
            # Update job with success
            job.status = JobStatus.COMPLETE
            job.output_key = output_key
            job.pages_processed = result.pages_processed
            job.phi_entities_masked = result.phi_entities_count
            job.processing_time_ms = result.processing_time_ms
            job.completed_at = datetime.utcnow()
            
            logger.info(
                f"Job {job_id} complete: "
                f"{result.pages_processed} pages, "
                f"{result.phi_entities_count} PHI entities masked"
            )
            
        except Exception as e:
            logger.error(f"Job {job_id} failed: {str(e)}", exc_info=True)
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            job.completed_at = datetime.utcnow()
        
        await db.commit()
```

---

### 7. Auth Abstraction (Placeholder)

**File:** `redactify/api/auth.py`

```python
from fastapi import Depends, HTTPException, Header
from typing import Optional


class AuthBackend:
    """
    Authentication backend abstraction.
    
    By default, this is a no-op (pass-through) for deployment behind
    an API gateway that handles authentication.
    
    To implement custom auth:
    1. Subclass AuthBackend
    2. Override authenticate()
    3. Set in dependencies
    
    Example with API key:
    
        class APIKeyAuth(AuthBackend):
            async def authenticate(self, authorization: Optional[str]) -> bool:
                if not authorization:
                    raise HTTPException(401, "Missing API key")
                # Validate key...
                return True
    
    Example with JWT:
    
        class JWTAuth(AuthBackend):
            async def authenticate(self, authorization: Optional[str]) -> dict:
                token = authorization.replace("Bearer ", "")
                payload = jwt.decode(token, SECRET_KEY)
                return payload
    """
    
    async def authenticate(
        self,
        authorization: Optional[str] = Header(None)
    ) -> bool:
        """
        Override this method to implement authentication.
        
        Args:
            authorization: Authorization header value
            
        Returns:
            True if authenticated, or user info dict
            
        Raises:
            HTTPException: If authentication fails
        """
        # Default: no authentication (pass-through)
        return True


# Dependency for routes
async def get_current_user(
    auth: AuthBackend = Depends(lambda: AuthBackend())
):
    """
    FastAPI dependency for authentication.
    
    Usage in routes:
        @app.post("/jobs")
        async def create_job(
            file: UploadFile,
            user = Depends(get_current_user)  # Add this
        ):
            ...
    """
    return await auth.authenticate()
```

---

## Project Structure

```
redactify/
├── .env.example
├── .gitignore
├── LICENSE (MIT)
├── README.md
├── pyproject.toml
├── docker-compose.yml
├── Dockerfile
├── Dockerfile.worker
├── alembic.ini
├── alembic/
│   ├── env.py
│   └── versions/
├── redactify/
│   ├── __init__.py
│   ├── config.py
│   ├── tasks.py
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py
│   │   └── auth.py
│   │
│   ├── db/
│   │   ├── __init__.py
│   │   ├── models.py
│   │   └── session.py
│   │
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── s3.py
│   │   ├── azure_blob.py
│   │   └── local.py
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── deidentification_service.py
│   │   ├── ocr_service.py
│   │   ├── phi_detection_service.py
│   │   └── image_masking_service.py
│   │
│   ├── domain/
│   │   ├── __init__.py
│   │   └── models.py
│   │
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── geometry.py
│   │   ├── image_processing.py
│   │   ├── medical_phi_patterns.py
│   │   └── logging.py
│   │
│   └── config/
│       └── phi_patterns.yaml
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── unit/
│   │   ├── test_storage.py
│   │   ├── test_phi_detection.py
│   │   └── test_masking.py
│   └── integration/
│       └── test_api.py
│
└── scripts/
    ├── run_api.sh
    ├── run_worker.sh
    └── init_db.py
```

---

## Implementation Order

### **Phase 1: Foundation (Days 1-2)**

**Goal:** Set up project skeleton, configuration, and storage abstraction

**Tasks:**
1. ✅ Initialize Poetry project
   ```bash
   poetry init
   poetry add fastapi uvicorn sqlalchemy asyncpg aiosqlite celery redis
   poetry add azure-ai-formrecognizer azure-storage-blob boto3 pillow pyyaml
   poetry add pydantic-settings python-multipart alembic
   poetry add --group dev pytest pytest-asyncio pytest-cov black ruff
   ```

2. ✅ Create project structure (folders, `__init__.py` files)

3. ✅ Implement `config.py` with Settings

4. ✅ Implement storage abstraction:
   - `storage/base.py` - Abstract base class
   - `storage/s3.py` - MinIO/S3 implementation
   - `storage/local.py` - Local filesystem (for tests)

5. ✅ Write unit tests for storage backends

6. ✅ Create `.env.example` and `.gitignore`

**Deliverable:** Can upload/download files to MinIO via abstraction

---

### **Phase 2: Domain Models & Database (Days 3-4)**

**Goal:** Set up data models and database layer

**Tasks:**
1. ✅ Implement `domain/models.py` (dataclasses)

2. ✅ Implement `db/models.py` (SQLAlchemy models)

3. ✅ Implement `db/session.py` (async session management)

4. ✅ Set up Alembic for migrations
   ```bash
   poetry run alembic init alembic
   # Create initial migration
   poetry run alembic revision --autogenerate -m "initial"
   ```

5. ✅ Write `scripts/init_db.py` for database initialization

6. ✅ Write unit tests using SQLite in-memory

**Deliverable:** Can create/query job records in database

---

### **Phase 3: Core Services (Days 5-7)**

**Goal:** Implement de-identification business logic

**Tasks:**
1. ✅ Implement `utils/image_processing.py` (TIFF load/save)

2. ✅ Implement `utils/geometry.py` (coordinate transformations)

3. ✅ Implement `utils/medical_phi_patterns.py` (regex pattern loading)

4. ✅ Implement `services/ocr_service.py` (Azure Document Intelligence)

5. ✅ Implement `services/phi_detection_service.py` (Azure + regex)

6. ✅ Implement `services/image_masking_service.py` (Pillow masking)

7. ✅ Implement `services/deidentification_service.py` (orchestrator)

8. ✅ Create `config/phi_patterns.yaml` with default patterns

9. ✅ Write unit tests for each service (mock Azure API)

**Deliverable:** Can process a TIFF end-to-end (without API/queue)

---

### **Phase 4: API & Celery (Days 8-9)**

**Goal:** Add REST API and async task processing

**Tasks:**
1. ✅ Implement `api/routes.py` (FastAPI endpoints)

2. ✅ Implement `api/auth.py` (placeholder auth)

3. ✅ Implement `tasks.py` (Celery task definition)

4. ✅ Create `scripts/run_api.sh` and `scripts/run_worker.sh`

5. ✅ Write integration tests for API endpoints

6. ✅ Test full flow: submit job → poll status → download result

**Deliverable:** Working async API with Celery workers

---

### **Phase 5: Docker & DevOps (Days 10-11)**

**Goal:** Containerize services and set up local development environment

**Tasks:**
1. ✅ Create `Dockerfile` for API service
   ```dockerfile
   FROM python:3.11-slim
   
   WORKDIR /app
   
   # Install system dependencies
   RUN apt-get update && apt-get install -y \
       libpq-dev \
       && rm -rf /var/lib/apt/lists/*
   
   # Install Poetry
   RUN pip install poetry
   
   # Copy dependency files
   COPY pyproject.toml poetry.lock ./
   
   # Install dependencies (no dev)
   RUN poetry config virtualenvs.create false \
       && poetry install --no-dev --no-interaction --no-ansi
   
   # Copy application
   COPY redactify/ ./redactify/
   COPY alembic/ ./alembic/
   COPY alembic.ini ./
   
   EXPOSE 8000
   
   CMD ["uvicorn", "redactify.api.routes:app", "--host", "0.0.0.0", "--port", "8000"]
   ```

2. ✅ Create `Dockerfile.worker` for Celery worker
   ```dockerfile
   FROM python:3.11-slim
   
   WORKDIR /app
   
   RUN apt-get update && apt-get install -y \
       libpq-dev \
       && rm -rf /var/lib/apt/lists/*
   
   RUN pip install poetry
   
   COPY pyproject.toml poetry.lock ./
   RUN poetry config virtualenvs.create false \
       && poetry install --no-dev --no-interaction --no-ansi
   
   COPY redactify/ ./redactify/
   
   CMD ["celery", "-A", "redactify.tasks", "worker", "--loglevel=info"]
   ```

3. ✅ Create `docker-compose.yml`
   ```yaml
   version: '3.8'
   
   services:
     postgres:
       image: postgres:15
       environment:
         POSTGRES_DB: redactify
         POSTGRES_USER: redactify
         POSTGRES_PASSWORD: redactify
       ports:
         - "5432:5432"
       volumes:
         - postgres_data:/var/lib/postgresql/data
       healthcheck:
         test: ["CMD-SHELL", "pg_isready -U redactify"]
         interval: 10s
         timeout: 5s
         retries: 5
   
     redis:
       image: redis:7-alpine
       ports:
         - "6379:6379"
       healthcheck:
         test: ["CMD", "redis-cli", "ping"]
         interval: 10s
         timeout: 5s
         retries: 5
   
     minio:
       image: minio/minio
       command: server /data --console-address ":9001"
       environment:
         MINIO_ROOT_USER: minioadmin
         MINIO_ROOT_PASSWORD: minioadmin
       ports:
         - "9000:9000"
         - "9001:9001"
       volumes:
         - minio_data:/data
       healthcheck:
         test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
         interval: 10s
         timeout: 5s
         retries: 5
   
     # Create MinIO bucket on startup
     minio-init:
       image: minio/mc
       depends_on:
         - minio
       entrypoint: >
         /bin/sh -c "
         /usr/bin/mc alias set myminio http://minio:9000 minioadmin minioadmin;
         /usr/bin/mc mb myminio/redactify --ignore-existing;
         exit 0;
         "
   
     api:
       build:
         context: .
         dockerfile: Dockerfile
       ports:
         - "8000:8000"
       env_file:
         - .env
       depends_on:
         postgres:
           condition: service_healthy
         redis:
           condition: service_healthy
         minio:
           condition: service_healthy
       volumes:
         - ./redactify:/app/redactify
       command: >
         sh -c "
         poetry run alembic upgrade head &&
         uvicorn redactify.api.routes:app --host 0.0.0.0 --port 8000 --reload
         "
   
     worker:
       build:
         context: .
         dockerfile: Dockerfile.worker
       env_file:
         - .env
       depends_on:
         postgres:
           condition: service_healthy
         redis:
           condition: service_healthy
         minio:
           condition: service_healthy
       volumes:
         - ./redactify:/app/redactify
       command: celery -A redactify.tasks worker --loglevel=info
   
   volumes:
     postgres_data:
     minio_data:
   ```

4. ✅ Create `scripts/run_api.sh`
   ```bash
   #!/bin/bash
   set -e
   
   echo "Running database migrations..."
   poetry run alembic upgrade head
   
   echo "Starting API server..."
   poetry run uvicorn redactify.api.routes:app \
       --host 0.0.0.0 \
       --port 8000 \
       --reload
   ```

5. ✅ Create `scripts/run_worker.sh`
   ```bash
   #!/bin/bash
   set -e
   
   echo "Starting Celery worker..."
   poetry run celery -A redactify.tasks worker \
       --loglevel=info \
       --concurrency=2
   ```

6. ✅ Create `scripts/init_db.py`
   ```python
   """Initialize database with tables."""
   import asyncio
   from redactify.db.models import Base
   from redactify.db.session import engine
   
   
   async def init_db():
       async with engine.begin() as conn:
           await conn.run_sync(Base.metadata.create_all)
       print("Database initialized successfully")
   
   
   if __name__ == "__main__":
       asyncio.run(init_db())
   ```

7. ✅ Test full stack:
   ```bash
   docker-compose up -d
   # Wait for services to be healthy
   docker-compose ps
   # Test API
   curl http://localhost:8000/health
   ```

**Deliverable:** Full stack running in Docker Compose

---

### **Phase 6: Documentation & Testing (Days 12-13)**

**Goal:** Write comprehensive documentation and tests

**Tasks:**
1. ✅ Write `README.md` (see below)

2. ✅ Write `CONTRIBUTING.md` with:
   - Code style guidelines (Black, Ruff)
   - How to run tests
   - How to submit PRs

3. ✅ Write `docs/DEPLOYMENT.md` with:
   - Production deployment guide
   - AWS/Azure/GCP examples
   - Environment variable reference
   - Scaling considerations

4. ✅ Write `docs/CONFIGURATION.md` with:
   - Storage backend configuration
   - Custom PHI patterns
   - Auth implementation examples

5. ✅ Add comprehensive test coverage:
   ```bash
   poetry run pytest --cov=redactify --cov-report=html
   # Target: >80% coverage
   ```

6. ✅ Set up pre-commit hooks (Black, Ruff, tests)

7. ✅ Add GitHub Actions CI/CD (if hosting on GitHub)
   ```yaml
   # .github/workflows/test.yml
   name: Tests
   
   on: [push, pull_request]
   
   jobs:
     test:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v3
         - uses: actions/setup-python@v4
           with:
             python-version: '3.11'
         - name: Install Poetry
           run: pip install poetry
         - name: Install dependencies
           run: poetry install
         - name: Run tests
           run: poetry run pytest --cov
         - name: Check formatting
           run: poetry run black --check .
         - name: Lint
           run: poetry run ruff check .
   ```

**Deliverable:** Production-ready documentation and CI

---

### **Phase 7: Polish & Release (Day 14)**

**Goal:** Final polish and prepare for open-source release

**Tasks:**
1. ✅ Add observability:
   - Structured logging with `structlog`
   - Add request IDs to all logs
   - Log job state transitions

2. ✅ Add health checks:
   - `/health` - basic health
   - `/health/ready` - check dependencies (DB, Redis, MinIO)

3. ✅ Add metrics endpoint (optional):
   - Prometheus-compatible `/metrics`
   - Track: jobs submitted, jobs completed, processing time, errors

4. ✅ Security review:
   - No hardcoded secrets
   - Secure defaults
   - Input validation
   - Rate limiting (document in README)

5. ✅ Performance testing:
   - Test with 100-page documents
   - Measure memory usage
   - Identify bottlenecks

6. ✅ Create example requests in `examples/`:
   ```bash
   examples/
   ├── submit_job.sh
   ├── check_status.sh
   ├── download_result.sh
   └── sample_tiff/
       └── test_document.tiff
   ```

7. ✅ Write release notes for v0.1.0

8. ✅ Tag release and publish to GitHub

**Deliverable:** Public GitHub repository with v0.1.0 release

---

## README.md (Draft)

```markdown
# Redactify

**Open-source medical document de-identification service**

Redactify automatically detects and masks Protected Health Information (PHI) in medical document images using Azure Document Intelligence and configurable regex patterns.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.11+-blue.svg)

## Features

- 🔒 **Automatic PHI Detection** - Identifies names, dates, SSNs, addresses, medical IDs
- 🎯 **Visual Masking** - Masks PHI directly on document images (TIFF format)
- ⚡ **Async Processing** - Submit jobs and poll for results (handles large documents)
- 🔌 **Pluggable Storage** - Support for S3, Azure Blob, MinIO, or local filesystem
- 🧩 **Configurable Patterns** - Add custom regex patterns for institution-specific identifiers
- 🐳 **Docker Ready** - Full Docker Compose setup for local development
- 🔓 **Open Source** - MIT licensed, contribution-friendly

## Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose
- Azure Document Intelligence account ([get one free](https://azure.microsoft.com/en-us/free/cognitive-services/))

### 1. Clone and Configure

```bash
git clone https://github.com/yourusername/redactify.git
cd redactify

# Copy environment template
cp .env.example .env

# Add your Azure credentials to .env
# AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=https://your-instance.cognitiveservices.azure.com/
# AZURE_DOCUMENT_INTELLIGENCE_KEY=your-key-here
```

### 2. Start Services

```bash
docker-compose up -d
```

This starts:
- **API Server** (port 8000)
- **Celery Worker**
- **PostgreSQL** (database)
- **Redis** (job queue)
- **MinIO** (S3-compatible storage)

### 3. Submit a Document

```bash
curl -X POST http://localhost:8000/jobs \
  -F "file=@/path/to/medical_record.tiff" \
  | jq .

# Response:
# {
#   "job_id": "550e8400-e29b-41d4-a716-446655440000",
#   "status": "pending",
#   "status_url": "/jobs/550e8400-e29b-41d4-a716-446655440000"
# }
```

### 4. Check Status

```bash
curl http://localhost:8000/jobs/550e8400-e29b-41d4-a716-446655440000 | jq .

# Response:
# {
#   "job_id": "550e8400-e29b-41d4-a716-446655440000",
#   "status": "complete",
#   "result_url": "/jobs/550e8400-e29b-41d4-a716-446655440000/result",
#   "metadata": {
#     "pages_processed": 25,
#     "phi_entities_masked": 147,
#     "processing_time_ms": 32450.2
#   }
# }
```

### 5. Download Result

```bash
curl -O http://localhost:8000/jobs/550e8400-e29b-41d4-a716-446655440000/result \
  --output masked_document.tiff
```

## Architecture

```
┌─────────────┐
│  REST API   │ ──────┐
└─────────────┘       │
                      ▼
┌─────────────┐   ┌────────────┐   ┌──────────────┐
│   MinIO     │◄──│   Celery   │──►│ PostgreSQL   │
│  (Storage)  │   │  Workers   │   │  (Jobs DB)   │
└─────────────┘   └────────────┘   └──────────────┘
                      │
                      ▼
              ┌───────────────┐
              │ Azure Doc     │
              │ Intelligence  │
              └───────────────┘
```

## Configuration

### Storage Backends

**S3 / MinIO** (default):
```bash
STORAGE_BACKEND=s3
S3_ENDPOINT_URL=http://localhost:9000
S3_BUCKET=redactify
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
```

**Azure Blob Storage**:
```bash
STORAGE_BACKEND=azure
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;...
AZURE_STORAGE_CONTAINER=redactify
```

**Local Filesystem** (dev only):
```bash
STORAGE_BACKEND=local
LOCAL_STORAGE_PATH=/tmp/redactify
```

### Custom PHI Patterns

Add institution-specific identifiers to `redactify/config/phi_patterns.yaml`:

```yaml
patterns:
  - name: CustomMRN
    regex: 'MRN-\d{8}'
    category: MedicalID_Custom
    flags: IGNORECASE
```

See [Configuration Guide](docs/CONFIGURATION.md) for details.

## Production Deployment

See [Deployment Guide](docs/DEPLOYMENT.md) for:
- AWS ECS deployment
- Azure Container Apps deployment
- Kubernetes manifests
- Scaling considerations
- Production storage configuration

## Development

### Setup

```bash
# Install Poetry
curl -sSL https://install.python-poetry.org | python3 -

# Install dependencies
poetry install

# Run tests
poetry run pytest

# Format code
poetry run black .

# Lint
poetry run ruff check .
```

### Running Locally (without Docker)

```bash
# Start dependencies
docker-compose up -d postgres redis minio

# Run migrations
poetry run alembic upgrade head

# Start API
poetry run uvicorn redactify.api.routes:app --reload

# Start worker (in another terminal)
poetry run celery -A redactify.tasks worker --loglevel=info
```

## API Reference

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/jobs` | Submit document for de-identification |
| GET | `/jobs/{id}` | Get job status |
| GET | `/jobs/{id}/result` | Download masked document |
| GET | `/health` | Health check |

See [API Documentation](docs/API.md) for detailed request/response examples.

## Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

MIT License - see [LICENSE](LICENSE) for details.

## Security

**Important**: This service masks PHI but does not guarantee 100% removal. Always:
- Review output documents
- Implement additional security controls
- Comply with HIPAA and relevant regulations
- Do NOT use for production without proper testing

Report security issues to: [security email]

## Acknowledgments

- Uses [Azure Document Intelligence](https://azure.microsoft.com/en-us/products/ai-services/ai-document-intelligence) for OCR and PII detection
- Inspired by medical data de-identification challenges in healthcare

## Support

- 📖 [Documentation](docs/)
- 🐛 [Issue Tracker](https://github.com/yourusername/redactify/issues)
- 💬 [Discussions](https://github.com/yourusername/redactify/discussions)

---

**It's ReDACTify, not RedactiFY** ✨
```

---

## pyproject.toml (Complete)

```toml
[tool.poetry]
name = "redactify"
version = "0.1.0"
description = "Open-source medical document de-identification service"
authors = ["Your Name <your.email@example.com>"]
license = "MIT"
readme = "README.md"
homepage = "https://github.com/yourusername/redactify"
repository = "https://github.com/yourusername/redactify"
keywords = ["healthcare", "phi", "deidentification", "hipaa", "medical"]

[tool.poetry.dependencies]
python = "^3.11"
fastapi = "^0.109.0"
uvicorn = {extras = ["standard"], version = "^0.27.0"}
sqlalchemy = "^2.0.25"
asyncpg = "^0.29.0"
aiosqlite = "^0.19.0"
celery = "^5.3.6"
redis = "^5.0.1"
azure-ai-formrecognizer = "^3.3.2"
azure-storage-blob = "^12.19.0"
boto3 = "^1.34.34"
pillow = "^10.2.0"
pyyaml = "^6.0.1"
pydantic-settings = "^2.1.0"
python-multipart = "^0.0.6"
alembic = "^1.13.1"
structlog = "^24.1.0"

[tool.poetry.group.dev.dependencies]
pytest = "^8.0.0"
pytest-asyncio = "^0.23.4"
pytest-cov = "^4.1.0"
black = "^24.1.1"
ruff = "^0.2.0"
httpx = "^0.26.0"
faker = "^22.6.0"

[tool.black]
line-length = 100
target-version = ['py311']

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
python_files = "test_*.py"
python_classes = "Test*"
python_functions = "test_*"

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"
```

---

## Testing Strategy

### Unit Tests

**File:** `tests/unit/test_storage.py`

```python
import pytest
from redactify.storage.local import LocalStorageBackend
import tempfile
import os


@pytest.mark.asyncio
async def test_local_storage_upload_download():
    """Test local storage upload and download."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorageBackend(base_path=tmpdir)
        
        # Upload
        test_data = b"test content"
        key = await storage.upload("test.txt", test_data)
        
        # Verify file exists
        assert await storage.exists(key)
        
        # Download
        downloaded = await storage.download(key)
        assert downloaded == test_data
        
        # Delete
        await storage.delete(key)
        assert not await storage.exists(key)
```

**File:** `tests/unit/test_phi_detection.py`

```python
import pytest
from redactify.utils.medical_phi_patterns import MedicalPHIPatterns


def test_mrn_pattern_detection():
    """Test MRN regex pattern detection."""
    patterns = MedicalPHIPatterns()
    
    test_text = "Patient MRN: ABC123456 was admitted"
    
    for name, regex in patterns.get_patterns():
        if name == "MRN":
            match = regex.search(test_text)
            assert match is not None
            assert "ABC123456" in match.group(0)
```

### Integration Tests

**File:** `tests/integration/test_api.py`

```python
import pytest
from fastapi.testclient import TestClient
from redactify.api.routes import app
import io


@pytest.fixture
def client():
    return TestClient(app)


def test_submit_job(client):
    """Test job submission endpoint."""
    # Create fake TIFF
    fake_tiff = io.BytesIO(b"fake tiff content")
    
    response = client.post(
        "/jobs",
        files={"file": ("test.tiff", fake_tiff, "image/tiff")}
    )
    
    assert response.status_code == 202
    data = response.json()
    assert "job_id" in data
    assert data["status"] == "pending"


def test_get_job_status(client):
    """Test job status endpoint."""
    # First submit a job
    fake_tiff = io.BytesIO(b"fake tiff content")
    submit_response = client.post(
        "/jobs",
        files={"file": ("test.tiff", fake_tiff, "image/tiff")}
    )
    job_id = submit_response.json()["job_id"]
    
    # Then check status
    status_response = client.get(f"/jobs/{job_id}")
    assert status_response.status_code == 200
    data = status_response.json()
    assert data["job_id"] == job_id
    assert data["status"] in ["pending", "processing", "complete", "failed"]
```

---

## CI/CD Pipeline

**File:** `.github/workflows/ci.yml`

```yaml
name: CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]

jobs:
  test:
    runs-on: ubuntu-latest
    
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: postgres
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
      
      redis:
        image: redis:7-alpine
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install Poetry
        run: |
          curl -sSL https://install.python-poetry.org | python3 -
          echo "$HOME/.local/bin" >> $GITHUB_PATH
      
      - name: Install dependencies
        run: poetry install
      
      - name: Run tests
        env:
          DATABASE_URL: postgresql+asyncpg://postgres:postgres@localhost:5432/test
          CELERY_BROKER_URL: redis://localhost:6379/0
        run: |
          poetry run pytest --cov=redactify --cov-report=xml --cov-report=term
      
      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          files: ./coverage.xml
      
      - name: Check formatting
        run: poetry run black --check .
      
      - name: Lint
        run: poetry run ruff check .
  
  build:
    runs-on: ubuntu-latest
    needs: test
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Build Docker image
        run: docker build -t redactify:${{ github.sha }} .
      
      - name: Test Docker image
        run: docker run --rm redactify:${{ github.sha }} python -c "import redactify; print('OK')"
```

---

## Summary: What You're Building

**Redactify** is a production-ready, open-source service that:

1. ✅ **Accepts** TIFF medical documents via REST API
2. ✅ **Detects** PHI using Azure Document Intelligence + custom regex
3. ✅ **Masks** PHI visually on the document images
4. ✅ **Returns** sanitized TIFFs asynchronously
5. ✅ **Abstracts** storage (S3/Azure/MinIO/Local)
6. ✅ **Scales** with Celery workers and Redis
7. ✅ **Documents** everything for open-source adoption
8. ✅ **Tests** with >80% coverage
9. ✅ **Deploys** via Docker Compose or production orchestrators

**Your internal fork** can then add:
- Training data collection
- HITL review workflow
- GPT-4 markdown conversion
- Business-specific quality scoring

---

