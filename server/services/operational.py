"""Best-effort persistent health signals; monitoring runs outside the app."""
import logging
from sqlalchemy import case, func
from sqlalchemy.dialects.postgresql import insert
from .. import database
from ..auth_models import OperationalSignal
from ..models import utcnow


def record_signal(name: str, success: bool):
    if name not in {'ai', 'email'}:
        raise ValueError('Unknown signal')
    try:
        now = utcnow()
        with database.SessionLocal() as db:
            statement = insert(OperationalSignal).values(name=name, consecutive_failures=0 if success else 1,
                last_success=now if success else None, last_failure=None if success else now)
            updates = {'consecutive_failures': 0 if success else OperationalSignal.consecutive_failures + 1,
                       'last_success' if success else 'last_failure': now}
            db.execute(statement.on_conflict_do_update(index_elements=['name'], set_=updates))
            db.commit()
    except Exception:
        logging.getLogger(__name__).warning('Health signal unavailable category=%s', name)
