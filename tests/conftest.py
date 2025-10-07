import pytest
import tempfile
import shutil
from io import BytesIO
from PIL import Image
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.schema import CreateColumn
from sqlalchemy.dialects.postgresql import TSVECTOR


from src.db.session import DatabaseSessionManager
from src.db.models import Base


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "unit: mark test as a unit test")
    config.addinivalue_line("markers", "integration: mark test as an integration test")
    config.addinivalue_line("markers", "slow: mark test as slow-running")

@compiles(CreateColumn, 'sqlite')
def skip_tsvector_create_column(element, compiler, **kw):
    """Skip TSVECTOR columns when creating tables in SQLite."""
    if isinstance(element.element.type, TSVECTOR):
        return None  # Skip this column entirely
    
    # Use default compilation for other columns
    return compiler.visit_create_column(element, **kw)
    
@pytest.fixture
def sync_db_manager(tmp_path):
    """Create file-based test database for thread safety."""
    db_path = tmp_path / "test.db"
    manager = DatabaseSessionManager(
        database_url=f"sqlite:///{db_path}",
        echo=False
    )
    
    # Create tables
    manager.create_tables_sync()
    
    yield manager
    
    # Cleanup
    manager.sync_engine.dispose()
    
@pytest.fixture
def temp_storage_dirs():
    """Create temporary directories for PHI and clean storage."""
    phi_dir = tempfile.mkdtemp(prefix="test_phi_")
    clean_dir = tempfile.mkdtemp(prefix="test_clean_")
    
    yield phi_dir, clean_dir
    
    # Cleanup
    shutil.rmtree(phi_dir, ignore_errors=True)
    shutil.rmtree(clean_dir, ignore_errors=True)
    
@pytest.fixture
def sample_tiff_bytes():
    """Create a simple TIFF image for testing."""
    img = Image.new('RGB', (100, 100), color='white')
    
    # Add some text-like patterns for OCR to detect
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)
    draw.text((10, 10), "Test Document", fill=(0, 0, 0))
    
    buffer = BytesIO()
    img.save(buffer, format='TIFF')
    return buffer.getvalue()


@pytest.fixture
async def async_db_manager():
    """Create in-memory test database."""
    manager = DatabaseSessionManager(
        database_url="sqlite+aiosqlite:///:memory:",
        echo=False
    )
    
    # Create tables
    async with manager.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield manager
    await manager.close()