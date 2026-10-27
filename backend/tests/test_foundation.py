"""Synthetic accounts and documents only; SQLite is a test fixture, never runtime storage."""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.auth import Identity, current_identity
from app.config import Settings
from app.database import get_db
from app.main import app
from app.models import Base, InterviewSession, Profile

@compiles(JSONB, 'sqlite')
def jsonb_fixture(type_, compiler, **kwargs):
    return 'JSON'

@pytest.fixture
def fixture():
    engine = create_engine('sqlite://', connect_args={'check_same_thread':False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    owner, other = uuid.uuid4(), uuid.uuid4()
    with Session(engine) as db:
        db.add_all([Profile(user_id=owner, display_name='Synthetic A'), Profile(user_id=other, display_name='Synthetic B')])
        db.flush()
        attempt = InterviewSession(user_id=owner, title='Synthetic private session')
        db.add(attempt); db.commit(); db.refresh(attempt)
        session_id = attempt.id
    def database():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[current_identity] = lambda: Identity(user_id=owner, display_name='Synthetic A')
    with TestClient(app) as client:
        yield client, owner, other, session_id
    app.dependency_overrides.clear()
    engine.dispose()

def test_owner_reads_and_other_account_cannot_discover(fixture):
    client, owner, other, session_id = fixture
    assert client.get(f'/api/sessions/{session_id}').status_code == 200
    assert len(client.get('/api/sessions').json()) == 1
    app.dependency_overrides[current_identity] = lambda: Identity(user_id=other, display_name='Synthetic B')
    denied = client.get(f'/api/sessions/{session_id}')
    assert denied.status_code == 404
    assert client.get('/api/sessions').json() == []
    assert client.get(f'/api/sessions/{uuid.uuid4()}').json() == denied.json()

def test_create_derives_owner_and_saves_session(fixture):
    client, owner, other, session_id = fixture
    assert client.post('/api/sessions', json={'title':'Synthetic new attempt','user_id':str(other)}).status_code == 422
    result = client.post('/api/sessions', json={'title':' Synthetic new attempt '})
    assert result.status_code == 201
    assert result.json()['title'] == 'Synthetic new attempt'
    assert result.json()['status'] == 'draft'
    assert len(client.get('/api/sessions').json()) == 2
    app.dependency_overrides[current_identity] = lambda: Identity(user_id=other, display_name='Synthetic B')
    assert client.get('/api/sessions/' + result.json()['id']).status_code == 404

def test_blank_title_is_rejected(fixture):
    client, *_ = fixture
    assert client.post('/api/sessions', json={'title':'   '}).status_code == 422

def test_missing_auth_denied():
    with TestClient(app) as client:
        for method, path in [('GET','/api/me'),('GET','/api/sessions'),('POST','/api/sessions')]:
            assert client.request(method,path,json={'title':'Synthetic'}).status_code == 401

def test_api_paths_do_not_fall_through_to_react():
    with TestClient(app) as client:
        response = client.get('/api/does-not-exist')
        assert response.status_code == 404
        assert 'application/json' in response.headers['content-type']
        assert response.headers['cache-control'] == 'no-store'

@pytest.mark.parametrize('status,expected', [(401,401),(403,401),(429,503),(500,503)])
def test_rejected_or_unavailable_auth_is_closed(status, expected):
    with patch('app.auth.get_settings', return_value=Settings(_env_file=None,
            supabase_url='https://synthetic.supabase.co',supabase_publishable_key='synthetic-public')), \
         patch('app.auth.httpx.AsyncClient') as factory:
        factory.return_value.__aenter__.return_value.get = AsyncMock(return_value=httpx.Response(status))
        with TestClient(app) as client:
            response = client.get('/api/me',headers={'Authorization':'Bearer synthetic-invalid'})
            assert response.status_code == expected

def test_verified_auth_identity():
    user_id = uuid.uuid4()
    with patch('app.auth.get_settings', return_value=Settings(_env_file=None,
            supabase_url='https://synthetic.supabase.co',supabase_publishable_key='synthetic-public')), \
         patch('app.auth.httpx.AsyncClient') as factory:
        factory.return_value.__aenter__.return_value.get = AsyncMock(return_value=httpx.Response(200,
            json={'id':str(user_id),'role':'authenticated','user_metadata':{'full_name':'Synthetic'}}))
        with TestClient(app) as client:
            result = client.get('/api/me',headers={'Authorization':'Bearer synthetic-token'})
            assert result.status_code == 200
            assert result.json()['user_id'] == str(user_id)

def test_configuration_rejects_wrong_database():
    with pytest.raises(ValueError):
        Settings(_env_file=None, database_url='sqlite://')
