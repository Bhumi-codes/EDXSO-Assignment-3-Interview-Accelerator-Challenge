from alembic import context
from sqlalchemy import create_engine, pool
from app.config import get_settings
from app.models import Base

settings=get_settings()
url = settings.migration_database_url or settings.database_url
if not url:
    raise RuntimeError('Set DATABASE_URL in backend/.env before running migrations.')

if context.is_offline_mode():
    context.configure(url=url.get_secret_value(), target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url.get_secret_value(), poolclass=pool.NullPool, connect_args={'connect_timeout':10})
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
