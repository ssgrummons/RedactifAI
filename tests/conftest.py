import pytest
import tempfile
import shutil
from io import BytesIO
from PIL import Image

from src.db.session import DatabaseSessionManager


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "unit: mark test as a unit test")
    config.addinivalue_line("markers", "integration: mark test as an integration test")
    config.addinivalue_line("markers", "slow: mark test as slow-running")
    
@pytest.fixture
def sync_db_manager():
    """Create in-memory test database with sync SQLite."""
    manager = DatabaseSessionManager(
        database_url="sqlite:///:memory:",  # <-- Just use sync SQLite
        echo=False
    )
    
    # Create tables using sync engine
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