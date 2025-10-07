"""
AWS service configuration using Pydantic BaseSettings.

Environment variables:
- AWS_ACCESS_KEY_ID
- AWS_SECRET_ACCESS_KEY
- AWS_REGION
- AWS_TEXTRACT_REGION (optional, defaults to AWS_REGION)
- AWS_COMPREHEND_REGION (optional, defaults to AWS_REGION)
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class AWSSettings(BaseSettings):
    """
    AWS service credentials and configuration.
    
    Setup Instructions:
    
    1. Create IAM user with appropriate permissions:
       aws iam create-user --user-name redactifai-service
    
    2. Attach required policies:
       # For Textract (OCR)
       aws iam attach-user-policy \
         --user-name redactifai-service \
         --policy-arn arn:aws:iam::aws:policy/AmazonTextractFullAccess
       
       # For Comprehend Medical (PHI detection)
       aws iam attach-user-policy \
         --user-name redactifai-service \
         --policy-arn arn:aws:iam::aws:policy/ComprehendMedicalFullAccess
    
    3. Create access key:
       aws iam create-access-key --user-name redactifai-service
       
       This returns:
       - AccessKeyId
       - SecretAccessKey
    
    4. Set environment variables in .env file:
       AWS_ACCESS_KEY_ID=your_access_key_id
       AWS_SECRET_ACCESS_KEY=your_secret_access_key
       AWS_REGION=us-east-1
    
    Note: AWS Comprehend Medical is only available in specific regions:
    - us-east-1 (N. Virginia)
    - us-east-2 (Ohio)
    - us-west-2 (Oregon)
    - ap-southeast-2 (Sydney)
    - ca-central-1 (Canada)
    - eu-west-1 (Ireland)
    - eu-west-2 (London)
    
    Best Practice: Use IAM roles instead of access keys when running in AWS
    (EC2, ECS, Lambda). This configuration supports both methods.
    """
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    # AWS credentials (optional if using IAM roles)
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    
    # Region configuration
    aws_region: str = "us-east-1"
    aws_textract_region: Optional[str] = None
    aws_comprehend_region: Optional[str] = None
    
    def get_textract_region(self) -> str:
        """Get Textract region, defaulting to main AWS region."""
        return self.aws_textract_region or self.aws_region
    
    def get_comprehend_region(self) -> str:
        """Get Comprehend Medical region, defaulting to main AWS region."""
        region = self.aws_comprehend_region or self.aws_region
        
        # Validate that region supports Comprehend Medical
        supported_regions = {
            "us-east-1", "us-east-2", "us-west-2",
            "ap-southeast-2", "ca-central-1",
            "eu-west-1", "eu-west-2"
        }
        
        if region not in supported_regions:
            raise ValueError(
                f"AWS Comprehend Medical not available in region '{region}'. "
                f"Supported regions: {', '.join(sorted(supported_regions))}"
            )
        
        return region
    
    def validate_ocr_config(self) -> None:
        """Validate that Textract credentials are configured."""
        # If running in AWS with IAM role, credentials not needed
        if not self.aws_access_key_id and not self.aws_secret_access_key:
            # Assume IAM role - boto3 will handle it
            return
        
        if not self.aws_access_key_id or not self.aws_secret_access_key:
            raise ValueError(
                "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY must both be set, "
                "or neither (when using IAM roles). "
                "See AWSSettings docstring for setup instructions."
            )
    
    def validate_phi_config(self) -> None:
        """Validate that Comprehend Medical credentials are configured."""
        self.validate_ocr_config()  # Same credentials
        
        # Validate region
        try:
            self.get_comprehend_region()
        except ValueError as e:
            raise ValueError(str(e))


# Global settings instance
aws_settings = AWSSettings()
