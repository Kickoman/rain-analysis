import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    """Create test client."""
    from app.main import app
    return TestClient(app)


def test_health_check(client):
    """Test health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "checks" in data
    assert data["checks"]["version"] == "0.1.0"
    assert data["checks"]["api"] == "ok"
    assert data["checks"]["database"] == "ok"


def test_root(client):
    """Test root endpoint."""
    response = client.get("/")
    # Root is an informational page and is exempt from authentication
    assert response.status_code == 200
    assert response.json()["message"] == "Rain Analysis API"


def test_docs_accessible(client):
    """Test that OpenAPI docs are accessible."""
    response = client.get("/docs")
    assert response.status_code == 200


def test_openapi_schema(client):
    """Test that OpenAPI schema is available."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert "openapi" in schema
    assert "info" in schema
    assert "paths" in schema
    assert schema["info"]["title"] == "Rain Analysis API"
    assert schema["info"]["version"] == "0.1.0"
