from fastapi.testclient import TestClient
from app.main import app

def test_health():
    with TestClient(app) as client:
        assert client.get('/health').json()['status'] == 'healthy'

def test_register_then_chat():
    with TestClient(app) as client:
        auth=client.post('/api/auth/register',json={'name':'Test','email':'test@example.com','password':'password123'}).json()['access_token']
        r=client.post('/api/chat',json={'query':'What documents are available?'},headers={'Authorization':f'Bearer {auth}'})
        assert r.status_code == 200
        assert 'answer' in r.json()
