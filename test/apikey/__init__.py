from fastapi.testclient import TestClient

from app import app

client = TestClient(app)

def test_create_api_key(monkeypatch):
    # def mock_create_api_key(name, description):
    #     return ApiKey(id=1, name=name, description=description, api_key="testkey")
    # monkeypatch.setattr("service.api_key_service.ApiKeyService.create_api_key", mock_create_api_key)
    response = client.post("/v1/api_key/create_api_key", params={"name": "test", "description": "desc"})
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "test"
    assert data["description"] == "desc"
    assert data["api_key"] == "testkey"
