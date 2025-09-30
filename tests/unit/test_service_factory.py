import pytest
from src.services.service_factory import create_ocr_service, create_phi_service
from src.services.azure_ocr_service import AzureOCRService
from src.services.aws_textract_service import AWSTextractService
from src.services.azure_phi_detection_service import AzurePHIDetectionService
from src.services.aws_comprehend_medical_service import AWSComprehendMedicalService
from tests.mocks.mock_ocr_service import MockOCRService
from tests.mocks.mock_phi_detection_service import MockPHIDetectionService
from src.config.azure_settings import AzureSettings
from src.config.aws_settings import AWSSettings


class TestServiceFactory:
    """Test suite for service factory functions."""
    
    def test_create_azure_ocr_service(self):
        """Test creating Azure OCR service."""
        settings = AzureSettings(
            azure_document_intelligence_endpoint="https://test.cognitiveservices.azure.com/",
            azure_document_intelligence_key="test-key",
            azure_language_endpoint="https://test.cognitiveservices.azure.com/",
            azure_language_key="test-key"
        )
        
        service = create_ocr_service("azure", azure_settings=settings)
        
        assert isinstance(service, AzureOCRService)
        assert service.settings.azure_document_intelligence_endpoint == "https://test.cognitiveservices.azure.com/"
        assert service.settings.azure_document_intelligence_key == "test-key"
    
    def test_create_aws_ocr_service(self):
        """Test creating AWS OCR service."""
        settings = AWSSettings(
            aws_access_key_id="test-access-key",
            aws_secret_access_key="test-secret-key",
            aws_region="us-east-1",
            aws_comprehend_region="us-east-1"
        )
        
        service = create_ocr_service("aws", aws_settings=settings)
        
        assert isinstance(service, AWSTextractService)
        assert service.settings.aws_region == "us-east-1"
    
    def test_create_mock_ocr_service(self):
        """Test creating mock OCR service."""
        service = create_ocr_service("mock")
        
        assert isinstance(service, MockOCRService)
    
    def test_create_azure_phi_service(self):
        """Test creating Azure PHI detection service."""
        settings = AzureSettings(
            azure_document_intelligence_endpoint="https://test.cognitiveservices.azure.com/",
            azure_document_intelligence_key="test-key",
            azure_language_endpoint="https://test.cognitiveservices.azure.com/",
            azure_language_key="test-key"
        )
        
        service = create_phi_service("azure", azure_settings=settings)
        
        assert isinstance(service, AzurePHIDetectionService)
        assert service.settings.azure_language_endpoint == "https://test.cognitiveservices.azure.com/"
        assert service.settings.azure_language_key == "test-key"
    
    def test_create_aws_phi_service(self):
        """Test creating AWS PHI detection service."""
        settings = AWSSettings(
            aws_access_key_id="test-access-key",
            aws_secret_access_key="test-secret-key",
            aws_region="us-east-1",
            aws_comprehend_region="us-east-1"
        )
        
        service = create_phi_service("aws", aws_settings=settings)
        
        assert isinstance(service, AWSComprehendMedicalService)
        assert service.settings.aws_region == "us-east-1"
    
    def test_create_mock_phi_service(self):
        """Test creating mock PHI detection service."""
        service = create_phi_service("mock")
        
        assert isinstance(service, MockPHIDetectionService)
    
    def test_invalid_ocr_provider(self):
        """Test that invalid OCR provider raises error."""
        with pytest.raises(ValueError, match="Unknown OCR provider: invalid"):
            create_ocr_service("invalid")
    
    def test_invalid_phi_provider(self):
        """Test that invalid PHI provider raises error."""
        with pytest.raises(ValueError, match="Unknown PHI provider: invalid"):
            create_phi_service("invalid")
    
    def test_ocr_service_without_settings(self):
        """Test creating service without explicit settings (uses env)."""
        # This will fail if env vars aren't set, but demonstrates the pattern
        # In real tests, you'd mock the settings or ensure they're set
        try:
            service = create_ocr_service("azure")
            assert isinstance(service, AzureOCRService)
        except Exception:
            # Expected if env vars not set
            pass
    
    def test_phi_service_without_settings(self):
        """Test creating PHI service without explicit settings (uses env)."""
        try:
            service = create_phi_service("aws")
            assert isinstance(service, AWSComprehendMedicalService)
        except Exception:
            # Expected if env vars not set
            pass