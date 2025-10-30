import boto3
from typing import Optional
from botocore.exceptions import ClientError
from .base import StorageBackend


class S3StorageBackend(StorageBackend):
    """S3/MinIO storage backend using boto3 (sync)."""
    
    def __init__(
        self,
        bucket: str,
        endpoint_url: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        region: str = "us-east-1"
    ):
        self.bucket = bucket
        self.endpoint_url = endpoint_url
        self.region = region
        
        client_kwargs = {
            'service_name': 's3',
            'region_name': self.region
        }
        
        if access_key and secret_key:
            client_kwargs['aws_access_key_id'] = access_key
            client_kwargs['aws_secret_access_key'] = secret_key
        
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
                if self.region == 'us-east-1':
                    self.client.create_bucket(Bucket=self.bucket)
                else:
                    self.client.create_bucket(
                        Bucket=self.bucket,
                        CreateBucketConfiguration={'LocationConstraint': self.region}
                    )
            else:
                raise
    
    def upload(self, key: str, data: bytes, content_type: str = "image/tiff") -> str:
        """Upload data to S3 (sync)."""
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type
        )
        return key
    
    def download(self, key: str) -> bytes:
        """Download data from S3 (sync)."""
        try:
            response = self.client.get_object(
                Bucket=self.bucket,
                Key=key
            )
            return response['Body'].read()
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')
            if error_code == 'NoSuchKey':
                raise FileNotFoundError(f"Key not found: {key}")
            raise
    
    def exists(self, key: str) -> bool:
        """Check if key exists in S3 (sync)."""
        try:
            self.client.head_object(
                Bucket=self.bucket,
                Key=key
            )
            return True
        except ClientError:
            return False
    
    def delete(self, key: str) -> None:
        """Delete key from S3 (sync)."""
        self.client.delete_object(
            Bucket=self.bucket,
            Key=key
        )