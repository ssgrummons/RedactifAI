import asyncio
from functools import partial
import boto3
from typing import Optional
from botocore.exceptions import ClientError
from .base import StorageBackend
from .settings import settings

class S3StorageBackend(StorageBackend):
    """S3/MinIO storage backend using boto3."""
    
    def __init__(
        self,
        endpoint_url: str = None,
        bucket: str = None,
        access_key: str = None,
        secret_key: str = None,
        region: str = None
    ):
        # Allow explicit None to disable endpoint_url (for mocking)
        if endpoint_url is None and hasattr(settings, 'S3_ENDPOINT_URL'):
            endpoint_url = settings.S3_ENDPOINT_URL
        
        self.endpoint_url = endpoint_url
        self.bucket = bucket or settings.S3_BUCKET
        self.region = region or settings.S3_REGION
        
        # Only pass endpoint_url if it's not None (moto doesn't need it)
        client_kwargs = {
            'service_name': 's3',
            'aws_access_key_id': access_key or settings.S3_ACCESS_KEY,
            'aws_secret_access_key': secret_key or settings.S3_SECRET_KEY,
            'region_name': self.region
        }
        if self.endpoint_url:
            client_kwargs['endpoint_url'] = self.endpoint_url
        
        self.client = boto3.client(**client_kwargs)
    
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
            if e.response['Error']['Code'] == 'NoSuchKey':
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
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                return False
            raise
    
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