import pytest
import tempfile
import shutil
from pathlib import Path
from moto import mock_aws
import boto3
from src.storage import LocalStorageBackend, S3StorageBackend


@pytest.fixture
def temp_storage_path():
    """Create a temporary directory for local storage tests."""
    tmpdir = tempfile.mkdtemp()
    yield tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def mock_s3_storage():
    """Create a mocked S3 storage backend."""
    with mock_aws():
        # Create mock bucket
        bucket_name = 'test-redactifai-bucket'
        s3_client = boto3.client(
            's3',
            region_name='us-east-1',
            aws_access_key_id='testing',
            aws_secret_access_key='testing'
        )
        s3_client.create_bucket(Bucket=bucket_name)
        
        # Create storage backend inside the mock context
        storage = S3StorageBackend(
            endpoint_url='',
            bucket=bucket_name,
            access_key='testing',
            secret_key='testing',
            region='us-east-1'
        )
        
        yield storage


class TestLocalStorageBackend:
    """Test suite for local filesystem storage."""
    
    def test_upload_and_download(self, temp_storage_path):
        """Test basic upload and download operations."""
        storage = LocalStorageBackend(base_path=temp_storage_path)
        
        test_data = b"test content for storage"
        key = "test/document.tiff"
        
        # Upload
        returned_key = storage.upload(key, test_data)
        assert returned_key == key
        
        # Download
        downloaded = storage.download(key)
        assert downloaded == test_data
    
    def test_exists(self, temp_storage_path):
        """Test file existence checking."""
        storage = LocalStorageBackend(base_path=temp_storage_path)
        
        key = "test/exists.tiff"
        
        # Should not exist initially
        assert not storage.exists(key)
        
        # Upload file
        storage.upload(key, b"data")
        
        # Should exist now
        assert storage.exists(key)
    
    def test_delete(self, temp_storage_path):
        """Test file deletion."""
        storage = LocalStorageBackend(base_path=temp_storage_path)
        
        key = "test/delete_me.tiff"
        
        # Upload file
        storage.upload(key, b"data")
        assert storage.exists(key)
        
        # Delete file
        storage.delete(key)
        assert not storage.exists(key)
    
    def test_download_nonexistent_file(self, temp_storage_path):
        """Test that downloading nonexistent file raises FileNotFoundError."""
        storage = LocalStorageBackend(base_path=temp_storage_path)
        
        with pytest.raises(FileNotFoundError):
            storage.download("nonexistent/file.tiff")
    
    def test_nested_directories(self, temp_storage_path):
        """Test that nested directories are created automatically."""
        storage = LocalStorageBackend(base_path=temp_storage_path)
        
        key = "deeply/nested/path/to/file.tiff"
        storage.upload(key, b"data")
        
        # Verify file exists and can be downloaded
        assert storage.exists(key)
        data = storage.download(key)
        assert data == b"data"
    
    def test_path_traversal_protection(self, temp_storage_path):
        """Test that path traversal attacks are prevented."""
        storage = LocalStorageBackend(base_path=temp_storage_path)
        
        # Try to escape base directory
        with pytest.raises(ValueError):
            storage.upload("../../etc/passwd", b"bad")
    
    def test_content_type_parameter(self, temp_storage_path):
        """Test that content_type parameter is accepted (even if not used)."""
        storage = LocalStorageBackend(base_path=temp_storage_path)
        
        key = "test/file.pdf"
        storage.upload(key, b"pdf data", content_type="application/pdf")
        
        # Should work normally
        data = storage.download(key)
        assert data == b"pdf data"


class TestS3StorageBackend:
    """Test suite for S3/MinIO storage using mocked S3."""
    
    def test_upload_and_download(self, mock_s3_storage):
        """Test basic S3 upload and download operations."""
        test_data = b"test content for s3"
        key = "test/document.tiff"
        
        # Upload
        returned_key = mock_s3_storage.upload(key, test_data)
        assert returned_key == key
        
        # Download
        downloaded = mock_s3_storage.download(key)
        assert downloaded == test_data
    
    def test_exists(self, mock_s3_storage):
        """Test S3 file existence checking."""
        key = "test/exists.tiff"
        
        # Should not exist initially
        assert not mock_s3_storage.exists(key)
        
        # Upload file
        mock_s3_storage.upload(key, b"data")
        
        # Should exist now
        assert mock_s3_storage.exists(key)
    
    def test_delete(self, mock_s3_storage):
        """Test S3 file deletion."""
        key = "test/delete_me.tiff"
        
        # Upload file
        mock_s3_storage.upload(key, b"data")
        assert mock_s3_storage.exists(key)
        
        # Delete file
        mock_s3_storage.delete(key)
        assert not mock_s3_storage.exists(key)
    
    def test_download_nonexistent_file(self, mock_s3_storage):
        """Test that downloading nonexistent S3 file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            mock_s3_storage.download("nonexistent/file.tiff")
    
    def test_nested_keys(self, mock_s3_storage):
        """Test that nested S3 keys work correctly."""
        key = "deeply/nested/path/to/file.tiff"
        test_data = b"nested data"
        
        mock_s3_storage.upload(key, test_data)
        assert mock_s3_storage.exists(key)
        
        downloaded = mock_s3_storage.download(key)
        assert downloaded == test_data
    
    def test_content_type(self, mock_s3_storage):
        """Test that content type is properly set on upload."""
        key = "test/file.pdf"
        mock_s3_storage.upload(key, b"pdf data", content_type="application/pdf")
        
        # Verify we can download it back
        data = mock_s3_storage.download(key)
        assert data == b"pdf data"