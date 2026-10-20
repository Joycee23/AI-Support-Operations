from alembic import context
from sqlalchemy import create_engine, pool
from server.database import Base
from server import models, auth_models, billing_models
import os
from dotenv import load_dotenv
load_dotenv()
config = context.config
url = os.environ.get('DATABASE_MIGRATION_URL')
if not url:
    raise RuntimeError('Set DATABASE_MIGRATION_URL using a migration role; never pass it to the app container.')

def configure(connection=None):
    context.configure(connection=connection, url=url, target_metadata=Base.metadata,
                      compare_type=True, transaction_per_migration=True)
    with context.begin_transaction():
        context.run_migrations()

if context.is_offline_mode():
    raise RuntimeError('Offline SQL disabled: migrations require validated online database connection.')
elif config.attributes.get('connection') is not None:
    configure(config.attributes['connection'])
else:
    engine = create_engine(url, poolclass=pool.NullPool, hide_parameters=True)
    with engine.connect() as connection:
        configure(connection)
