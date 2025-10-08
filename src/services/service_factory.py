"""Factory for creating OCR and PHI detection services based on provider configuration."""

from typing import Literal
from src.services.ocr_service import OCRService
from src.services.phi_detection_service import PHIDetectionService
from src.services.azure_ocr_service import AzureOCRService
from src.services.aws_textract_service import AWSTextractService
from src.services.azure_phi_detection_service import AzurePHIDetectionService
from src.services.aws_comprehend_medical_service import AWSComprehendMedicalService
from src.config.azure_settings import AzureSettings
from src.config.aws_settings import AWSSettings


Provider = Literal["azure", "aws", "mock"]


def create_ocr_service(
    provider: Provider,
    azure_settings: AzureSettings | None = None,
    aws_settings: AWSSettings | None = None
) -> OCRService:
    """
    Create OCR service based on provider.
    
    Args:
        provider: "azure", "aws", or "mock"
        azure_settings: Optional Azure settings (loads from env if not provided)
        aws_settings: Optional AWS settings (loads from env if not provided)
    
    Returns:
        Configured OCR service
        
    Example:
        # Production usage
        ocr = create_ocr_service("azure")
        
        # Testing with dependency injection
        test_settings = AzureSettings(...)
        ocr = create_ocr_service("azure", azure_settings=test_settings)
    
    Raises:
        ValueError: If provider is unknown
    """
    if provider == "azure":
        return AzureOCRService(settings=azure_settings)
    elif provider == "aws":
        return AWSTextractService(settings=aws_settings)
    elif provider == "mock":
        # Import here to avoid circular dependency
        from src.services.mock_ocr_service import MockOCRService
        return MockOCRService()
    else:
        raise ValueError(f"Unknown OCR provider: {provider}")


def create_phi_service(
    provider: Provider,
    azure_settings: AzureSettings | None = None,
    aws_settings: AWSSettings | None = None
) -> PHIDetectionService:
    """
    Create PHI detection service based on provider.
    
    Args:
        provider: "azure", "aws", or "mock"
        azure_settings: Optional Azure settings (loads from env if not provided)
        aws_settings: Optional AWS settings (loads from env if not provided)
    
    Returns:
        Configured PHI detection service
        
    Example:
        # Production usage
        phi = create_phi_service("aws")
        
        # Testing with dependency injection
        test_settings = AWSSettings(...)
        phi = create_phi_service("aws", aws_settings=test_settings)
    
    Raises:
        ValueError: If provider is unknown
    """
    if provider == "azure":
        return AzurePHIDetectionService(settings=azure_settings)
    elif provider == "aws":
        return AWSComprehendMedicalService(settings=aws_settings)
    elif provider == "mock":
        # Import here to avoid circular dependency
        from src.services.mock_phi_detection_service import MockPHIDetectionService
        return MockPHIDetectionService()
    else:
        raise ValueError(f"Unknown PHI provider: {provider}")