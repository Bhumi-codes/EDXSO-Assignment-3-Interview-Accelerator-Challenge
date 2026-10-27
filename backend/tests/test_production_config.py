import base64,json
import pytest
from pydantic import ValidationError
from app.config import Settings


def production(**changes):
    return Settings(_env_file=None,**{'app_env':'production','app_origin':'https://interview.example.com','app_allowed_hosts':'interview.example.com',
        'database_url':'postgresql+psycopg://app:synthetic@database.example.com:5432/app?sslmode=require',
        'supabase_url':'https://example.supabase.co','supabase_publishable_key':'public-placeholder','groq_api_key':'synthetic-provider',**changes})


def test_complete_production_config_is_valid():
    assert production().configured


@pytest.mark.parametrize('changes',[
    {'app_origin':'http://interview.example.com'},
    {'app_origin':'https://interview.example.com/path'},
    {'app_allowed_hosts':'*'},
    {'app_allowed_hosts':'another.example.com'},
    {'database_url':'postgresql+psycopg://app:synthetic@database.example.com:5432/app'},
    {'groq_api_key':None},
    {'supabase_url':None},
])
def test_unsafe_or_incomplete_production_settings_fail(changes):
    with pytest.raises(ValidationError):production(**changes)


def test_private_supabase_key_is_never_accepted_as_public_key():
    with pytest.raises(ValidationError):production(supabase_publishable_key='sb_secret_synthetic')
    payload=base64.urlsafe_b64encode(json.dumps({'role':'service_role'}).encode()).decode().rstrip('=')
    with pytest.raises(ValidationError):production(supabase_publishable_key='header.'+payload+'.signature')


def test_validation_errors_hide_credentials():
    secret='synthetic-password-do-not-display'
    with pytest.raises(ValidationError) as caught:production(database_url='invalid://'+secret)
    assert secret not in str(caught.value)


def test_development_can_start_without_live_services():
    assert Settings(_env_file=None).app_env=='development'
