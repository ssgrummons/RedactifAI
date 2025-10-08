"""Unit tests for PHI entities endpoint."""

import pytest
import uuid
from datetime import datetime, timezone
from unittest.mock import Mock, MagicMock, patch

from fastapi.testclient import TestClient

from src.api.main import app
from src.db.models import Job, JobStatus, PHIEntity


class TestGetPHIEntities:
    """Tests for GET /api/v1/jobs/{job_id}/entities endpoint."""
    
    def test_get_entities_without_text(self, client, mock_db_session):
        """Test retrieving entities without PHI text."""
        job_id = str(uuid.uuid4())
        
        # Create mock job with entities
        mock_job = Mock()
        mock_job.id = job_id
        mock_job.status = JobStatus.COMPLETE
        
        mock_entity1 = Mock()
        mock_entity1.text = "John Doe"
        mock_entity1.category = "Person"
        mock_entity1.page = 1
        mock_entity1.confidence = 0.95
        mock_entity1.offset = 120
        mock_entity1.length = 8
        mock_entity1.bbox_x = 150.5
        mock_entity1.bbox_y = 200.3
        mock_entity1.bbox_width = 80.2
        mock_entity1.bbox_height = 12.1
        
        mock_entity2 = Mock()
        mock_entity2.text = "555-1234"
        mock_entity2.category = "Phone"
        mock_entity2.page = 1
        mock_entity2.confidence = 0.89
        mock_entity2.offset = 200
        mock_entity2.length = 8
        mock_entity2.bbox_x = 200.0
        mock_entity2.bbox_y = 250.0
        mock_entity2.bbox_width = 60.0
        mock_entity2.bbox_height = 10.0
        
        mock_job.phi_entities = [mock_entity1, mock_entity2]
        
        mock_db_session.get = Mock(return_value=mock_job)
        
        # Mock execute for eager loading query
        mock_result = Mock()
        mock_result.scalar_one.return_value = mock_job
        mock_db_session.execute = Mock(return_value=mock_result)
        
        def mock_get_db():
            yield mock_db_session
        
        with patch('src.api.dependencies.get_db_session', mock_get_db):
            response = client.get(f"/api/v1/jobs/{job_id}/entities")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["job_id"] == job_id
        assert data["total_entities"] == 2
        assert len(data["entities"]) == 2
        
        # Text should be null when include_text=false (default)
        assert data["entities"][0]["text"] is None
        assert data["entities"][0]["category"] == "Person"
        assert data["entities"][0]["page"] == 1
        assert data["entities"][0]["confidence"] == 0.95
        
        assert data["entities"][1]["text"] is None
        assert data["entities"][1]["category"] == "Phone"
    
    def test_get_entities_with_text(self, client, mock_db_session):
        """Test retrieving entities WITH PHI text."""
        job_id = str(uuid.uuid4())
        
        mock_job = Mock()
        mock_job.id = job_id
        mock_job.status = JobStatus.COMPLETE
        
        mock_entity = Mock()
        mock_entity.text = "John Doe"
        mock_entity.category = "Person"
        mock_entity.page = 1
        mock_entity.confidence = 0.95
        mock_entity.offset = 120
        mock_entity.length = 8
        mock_entity.bbox_x = 150.5
        mock_entity.bbox_y = 200.3
        mock_entity.bbox_width = 80.2
        mock_entity.bbox_height = 12.1
        
        mock_job.phi_entities = [mock_entity]
        
        mock_db_session.get = Mock(return_value=mock_job)
        
        mock_result = Mock()
        mock_result.scalar_one.return_value = mock_job
        mock_db_session.execute = Mock(return_value=mock_result)
        
        def mock_get_db():
            yield mock_db_session
        
        with patch('src.api.dependencies.get_db_session', mock_get_db):
            response = client.get(f"/api/v1/jobs/{job_id}/entities?include_text=true")
        
        assert response.status_code == 200
        data = response.json()
        
        # Text should be included when include_text=true
        assert data["entities"][0]["text"] == "John Doe"
        assert data["entities"][0]["category"] == "Person"
    
    def test_get_entities_job_not_found(self, client, mock_db_session):
        """Test 404 when job doesn't exist."""
        job_id = str(uuid.uuid4())
        mock_db_session.get = Mock(return_value=None)
        
        def mock_get_db():
            yield mock_db_session
        
        with patch('src.api.dependencies.get_db_session', mock_get_db):
            response = client.get(f"/api/v1/jobs/{job_id}/entities")
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
    
    def test_get_entities_job_not_complete(self, client, mock_db_session):
        """Test 400 when job is not complete."""
        job_id = str(uuid.uuid4())
        
        mock_job = Mock()
        mock_job.status = JobStatus.PROCESSING
        mock_db_session.get = Mock(return_value=mock_job)
        
        def mock_get_db():
            yield mock_db_session
        
        with patch('src.api.dependencies.get_db_session', mock_get_db):
            response = client.get(f"/api/v1/jobs/{job_id}/entities")
        
        assert response.status_code == 400
        assert "not available" in response.json()["detail"].lower()
    
    def test_get_entities_empty_list(self, client, mock_db_session):
        """Test retrieving entities when none were detected."""
        job_id = str(uuid.uuid4())
        
        mock_job = Mock()
        mock_job.id = job_id
        mock_job.status = JobStatus.COMPLETE
        mock_job.phi_entities = []
        
        mock_db_session.get = Mock(return_value=mock_job)
        
        mock_result = Mock()
        mock_result.scalar_one.return_value = mock_job
        mock_db_session.execute = Mock(return_value=mock_result)
        
        def mock_get_db():
            yield mock_db_session
        
        with patch('src.api.dependencies.get_db_session', mock_get_db):
            response = client.get(f"/api/v1/jobs/{job_id}/entities")
        
        assert response.status_code == 200
        data = response.json()
        assert data["total_entities"] == 0
        assert len(data["entities"]) == 0
    
    def test_get_entities_multiple_pages(self, client, mock_db_session):
        """Test entities from multiple pages."""
        job_id = str(uuid.uuid4())
        
        mock_job = Mock()
        mock_job.id = job_id
        mock_job.status = JobStatus.COMPLETE
        
        # Entities on different pages
        mock_entity_page1 = Mock()
        mock_entity_page1.text = "Entity 1"
        mock_entity_page1.category = "Person"
        mock_entity_page1.page = 1
        mock_entity_page1.confidence = 0.95
        mock_entity_page1.offset = 100
        mock_entity_page1.length = 8
        mock_entity_page1.bbox_x = 100.0
        mock_entity_page1.bbox_y = 100.0
        mock_entity_page1.bbox_width = 50.0
        mock_entity_page1.bbox_height = 10.0
        
        mock_entity_page2 = Mock()
        mock_entity_page2.text = "Entity 2"
        mock_entity_page2.category = "Date"
        mock_entity_page2.page = 2
        mock_entity_page2.confidence = 0.90
        mock_entity_page2.offset = 200
        mock_entity_page2.length = 10
        mock_entity_page2.bbox_x = 150.0
        mock_entity_page2.bbox_y = 150.0
        mock_entity_page2.bbox_width = 60.0
        mock_entity_page2.bbox_height = 12.0
        
        mock_job.phi_entities = [mock_entity_page1, mock_entity_page2]
        
        mock_db_session.get = Mock(return_value=mock_job)
        
        mock_result = Mock()
        mock_result.scalar_one.return_value = mock_job
        mock_db_session.execute = Mock(return_value=mock_result)
        
        def mock_get_db():
            yield mock_db_session
        
        with patch('src.api.dependencies.get_db_session', mock_get_db):
            response = client.get(f"/api/v1/jobs/{job_id}/entities")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["total_entities"] == 2
        assert data["entities"][0]["page"] == 1
        assert data["entities"][1]["page"] == 2
    
    def test_get_entities_various_categories(self, client, mock_db_session):
        """Test entities of different PHI categories."""
        job_id = str(uuid.uuid4())
        
        mock_job = Mock()
        mock_job.id = job_id
        mock_job.status = JobStatus.COMPLETE
        
        categories = ["Person", "Date", "Phone", "Email", "SSN", "Address"]
        entities = []
        
        for i, category in enumerate(categories):
            entity = Mock()
            entity.text = f"Test {category}"
            entity.category = category
            entity.page = 1
            entity.confidence = 0.90 + (i * 0.01)
            entity.offset = i * 100
            entity.length = 10
            entity.bbox_x = float(i * 50)
            entity.bbox_y = 100.0
            entity.bbox_width = 50.0
            entity.bbox_height = 10.0
            entities.append(entity)
        
        mock_job.phi_entities = entities
        
        mock_db_session.get = Mock(return_value=mock_job)
        
        mock_result = Mock()
        mock_result.scalar_one.return_value = mock_job
        mock_db_session.execute = Mock(return_value=mock_result)
        
        def mock_get_db():
            yield mock_db_session
        
        with patch('src.api.dependencies.get_db_session', mock_get_db):
            response = client.get(f"/api/v1/jobs/{job_id}/entities")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["total_entities"] == len(categories)
        returned_categories = [e["category"] for e in data["entities"]]
        assert set(returned_categories) == set(categories)