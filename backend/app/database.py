from functools import lru_cache
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from .config import get_settings

@lru_cache
def get_engine():
    url = get_settings().database_url
    if url is None:
        raise HTTPException(503, 'Database setup is required. See docs/SETUP.md.')
    return create_engine(url.get_secret_value(), pool_pre_ping=True, pool_size=5,
                         max_overflow=0, connect_args={'connect_timeout': 10})

def get_db():
    with Session(get_engine()) as db:
        yield db
