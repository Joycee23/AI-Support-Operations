"""Run reviewed migrations, optionally adopt a verified pre-Alembic database."""
import argparse
import os
from pathlib import Path
import sys
from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.autogenerate import compare_metadata

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from server.database import Base
from server import models, auth_models, billing_models


def main():
    load_dotenv(ROOT / '.env')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adopt-existing', action='store_true', help='Validate baseline columns before stamping; take a backup first')
    args = parser.parse_args()
    url = os.getenv('DATABASE_MIGRATION_URL')
    if not url:
        raise SystemExit('Set DATABASE_MIGRATION_URL on the administration host only.')
    config = Config(str(ROOT / 'alembic.ini'))
    engine = create_engine(url, hide_parameters=True)
    try:
        with engine.connect() as db:
            # Serialize releases; session lock remains held across Alembic transactions.
            db.execute(text("SELECT pg_advisory_lock(7020202601)"))
            db.commit()
            config.attributes['connection'] = db
            if args.adopt_existing and not inspect(db).has_table('alembic_version') and set(inspect(db).get_table_names()) & set(Base.metadata.tables):
                # Baseline does not contain knowledge_jobs (introduced in revision 0002).
                metadata = sa_baseline()
                differences = compare_metadata(MigrationContext.configure(db, opts={'compare_type': True}), metadata)
                if differences:
                    raise RuntimeError('Existing schema differs from baseline; review schema drift before adoption.')
                db.commit()
                command.stamp(config, '0001_baseline')
                db.commit()
            command.upgrade(config, 'head')
            db.commit()
            print('Database migration completed at head.')
    except Exception:
        raise SystemExit('Migration failed; inspect schema/version with the migration role. No credentials printed.') from None
    finally:
        engine.dispose()


def sa_baseline():
    from sqlalchemy import MetaData
    metadata = MetaData()
    for table in Base.metadata.sorted_tables:
        if table.name not in {'knowledge_jobs', 'operational_signals'}:
            table.to_metadata(metadata)
    return metadata


if __name__ == '__main__':
    main()
