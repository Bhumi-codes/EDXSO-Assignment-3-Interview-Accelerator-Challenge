from functools import lru_cache
from pathlib import Path
from pydantic import Field, SecretStr, field_validator, model_validator
from typing import Literal
from urllib.parse import urlsplit
import base64,json
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[1] / '.env', extra='ignore',hide_input_in_errors=True)
    app_env:Literal['development','production']='development'
    app_allowed_hosts:str='localhost,127.0.0.1'
    database_url: SecretStr | None = None
    migration_database_url:SecretStr | None=None
    supabase_url: str | None = None
    supabase_publishable_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    groq_communication_api_key: SecretStr | None = None
    groq_communication_model: str | None = None
    groq_communication_token_budget: int = Field(default=7000,ge=2500)
    groq_stt_model: str = 'whisper-large-v3-turbo'
    groq_interview_token_budget: int = Field(default=7000,ge=2500)
    groq_model: str = 'openai/gpt-oss-120b'
    app_origin: str = 'http://localhost:5173'

    @field_validator('database_url','migration_database_url')
    @classmethod
    def postgres_only(cls, value):
        if value and make_url(value.get_secret_value()).drivername != 'postgresql+psycopg':
            raise ValueError('DATABASE_URL must use postgresql+psycopg')
        return value

    @field_validator('supabase_url')
    @classmethod
    def https_auth(cls, value):
        if value and (not value.startswith('https://') or '/' in value[8:].rstrip('/')):
            raise ValueError('SUPABASE_URL must be an HTTPS project origin')
        return value.rstrip('/') if value else None

    @model_validator(mode='after')
    def production_config(self):
        if self.supabase_publishable_key:
            key=self.supabase_publishable_key.get_secret_value()
            if key.startswith('sb_secret_'):raise ValueError('Use a public Supabase publishable key, never a secret key')
            if key.count('.')==2:
                try:
                    payload=key.split('.')[1];claims=json.loads(base64.urlsafe_b64decode(payload+'='*(-len(payload)%4)))
                except (ValueError,UnicodeDecodeError):claims={}
                if claims.get('role')=='service_role':raise ValueError('A Supabase service-role key must not be used as the public key')
        if self.app_env=='production':
            if not self.configured or not self.groq_api_key:raise ValueError('Production requires database, Supabase and Groq configuration')
            origin=urlsplit(self.app_origin)
            if origin.scheme!='https' or not origin.hostname or origin.path not in ('','/') or origin.query or origin.fragment:raise ValueError('Production APP_ORIGIN must be an HTTPS origin')
            hosts=[h.strip() for h in self.app_allowed_hosts.split(',') if h.strip()]
            if not hosts or any('*' in h for h in hosts) or origin.hostname not in hosts:raise ValueError('APP_ALLOWED_HOSTS must explicitly include the production hostname without wildcards')
            url=make_url(self.database_url.get_secret_value())
            if url.query.get('sslmode') not in ('require','verify-ca','verify-full'):raise ValueError('Production database connections must require SSL')
        return self

    @property
    def configured(self):
        return bool(self.database_url and self.supabase_url and self.supabase_publishable_key)

@lru_cache
def get_settings():
    return Settings()
