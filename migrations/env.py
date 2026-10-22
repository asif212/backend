from alembic import context
from my_time.config import settings
from my_time.db import Base, make_engine
from my_time.models import core, hr, work, leave

if context.is_offline_mode():
    context.configure(url=settings.DATABASE_URL, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with make_engine(settings.DATABASE_URL).connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=connection.dialect.name == "sqlite")
        with context.begin_transaction():
            context.run_migrations()
