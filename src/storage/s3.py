import asyncio
from functools import partial
import boto3
from typing import Optional
from botocore.exceptions import ClientError
from .base import StorageBackend


class S3StorageBackend(StorageBackend):
    """S3/MinIO storage backend using boto3 with async wrapper."""
    
    def __init__(
        self,
        bucket: str,
        endpoint_url: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        region: str = "us-east-1"
    ):
        """
        Initialize S3 storage backend.
        
        Args:
            bucket: S3 bucket name
            endpoint_url: Optional S3 endpoint (for MinIO/localstack). 
                         None for real AWS S3.
            access_key: AWS access key (required)
            secret_key: AWS secret key (required)
            region: AWS region
        """
        self.bucket = bucket
        self.endpoint_url = endpoint_url
        self.region = region
        
        # Build client kwargs
        client_kwargs = {
            'service_name': 's3',
            'region_name': self.region
        }
        
        # Add credentials if provided
        if access_key and secret_key:
            client_kwargs['aws_access_key_id'] = access_key
            client_kwargs['aws_secret_access_key'] = secret_key
        
        # Add endpoint_url only if specified (for MinIO/localstack)
        if self.endpoint_url:
            client_kwargs['endpoint_url'] = self.endpoint_url
        
        self.client = boto3.client(**client_kwargs)
        self._ensure_bucket_exists()
    
    def _ensure_bucket_exists(self):
        """Create bucket if it doesn't exist."""
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')
            if error_code == '404':
                # Bucket doesn't exist, create it
                if self.region == 'us-east-1':
                    self.client.create_bucket(Bucket=self.bucket)
                else:
                    self.client.create_bucket(
                        Bucket=self.bucket,
                        CreateBucketConfiguration={'LocationConstraint': self.region}
                    )
            else:
                # Some other error (permissions, etc.)
                raise
    
    async def upload(self, key: str, data: bytes, content_type: str = "image/tiff") -> str:
        """Upload data to S3."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            partial(
                self.client.put_object,
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type
            )
        )
        return key
    
    async def download(self, key: str) -> bytes:
        """Download data from S3."""
        loop = asyncio.get_event_loop()
        try:
            response = await loop.run_in_executor(
                None,
                partial(
                    self.client.get_object,
                    Bucket=self.bucket,
                    Key=key
                )
            )
            return response['Body'].read()
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')
            if error_code == 'NoSuchKey':
                raise FileNotFoundError(f"Key not found: {key}")
            raise
    
    async def exists(self, key: str) -> bool:
        """Check if key exists in S3."""
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                None,
                partial(
                    self.client.head_object,
                    Bucket=self.bucket,
                    Key=key
                )
            )
            return True
        except ClientError:
            return False
    
    async def delete(self, key: str) -> None:
        """Delete key from S3."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            partial(
                self.client.delete_object,
                Bucket=self.bucket,
                Key=key
            )
        )