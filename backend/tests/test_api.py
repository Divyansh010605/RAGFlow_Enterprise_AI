from fastapi.testclient import TestClient
from app.main import app
from app.security import validate_read_only_sql
import pytest
from fastapi import HTTPException

def test_health():
    with TestClient(app) as client:
        assert client.get('/health').json()['status'] == 'healthy'

def test_metrics_plain_text():
    with TestClient(app) as client:
        r = client.get('/metrics')
        assert r.status_code == 200
        assert 'text/plain' in r.headers['content-type']
        assert 'agent_requests_total' in r.text
        assert 'ragflow_documents_total' in r.text

def test_register_then_chat():
    with TestClient(app) as client:
        auth = client.post('/api/auth/register', json={'name':'Test','email':'test@example.com','password':'password123'}).json()['access_token']
        r = client.post('/api/chat', json={'query':'What documents are available?'}, headers={'Authorization':f'Bearer {auth}'})
        assert r.status_code == 200
        assert 'answer' in r.json()

def test_safe_sql_blocks_system_tables():
    with TestClient(app) as client:
        auth = client.post('/api/auth/login', json={'email':'test@example.com','password':'password123'}).json()['access_token']
        r = client.post('/api/sql/query', json={'query':'SELECT * FROM users'}, headers={'Authorization':f'Bearer {auth}'})
        assert r.status_code == 403

def test_safe_sql_allows_sales_table():
    with TestClient(app) as client:
        auth = client.post('/api/auth/login', json={'email':'test@example.com','password':'password123'}).json()['access_token']
        r = client.post('/api/sql/query', json={'query':'SELECT region, revenue FROM sales WHERE manager LIKE "%Asha%"'}, headers={'Authorization':f'Bearer {auth}'})
        assert r.status_code == 200
        assert 'rows' in r.json()

def test_sql_keyword_validator_word_boundary():
    # 'alter' inside 'Walter' must not trigger unsafe keyword block
    res = validate_read_only_sql("SELECT * FROM sales WHERE manager = 'Walter'")
    assert "Walter" in res

    # Real blocked keyword must raise 422
    with pytest.raises(HTTPException):
        validate_read_only_sql("SELECT * FROM sales; DROP TABLE sales")

def test_conversation_ownership():
    with TestClient(app) as client:
        auth1 = client.post('/api/auth/register', json={'name':'User1','email':'user1@example.com','password':'password123'}).json()['access_token']
        r1 = client.post('/api/chat', json={'query':'Hello from user 1'}, headers={'Authorization':f'Bearer {auth1}'})
        cid = r1.json()['conversation_id']

        auth2 = client.post('/api/auth/register', json={'name':'User2','email':'user2@example.com','password':'password123'}).json()['access_token']
        # User 2 attempts to send message to User 1's conversation
        r2 = client.post('/api/chat', json={'query':'Hijack attempt','conversation_id':cid}, headers={'Authorization':f'Bearer {auth2}'})
        assert r2.status_code == 403
