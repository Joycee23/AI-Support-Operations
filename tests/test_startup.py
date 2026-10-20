import os
import unittest
import uuid

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from server.database import Base
from server.models import AuditEvent, KnowledgeItem, Team, Ticket, TicketMessage, User, Workspace
from server.seed import seed_demo
from server.services.ingestion import split_chunks


class ChunkingTests(unittest.TestCase):
    def test_short_document_is_not_repeated_as_overlapping_suffixes(self):
        self.assertEqual(split_chunks("Chính sách đổi hàng trong 7 ngày."), ["Chính sách đổi hàng trong 7 ngày."])

    def test_long_document_stops_after_the_final_chunk(self):
        chunks = split_chunks("x" * 2600)
        self.assertEqual([len(chunk) for chunk in chunks], [1200, 1200, 520])

    def test_invalid_overlap_is_rejected(self):
        with self.assertRaises(ValueError):
            split_chunks("text", size=100, overlap=100)


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "Set TEST_DATABASE_URL to run against PostgreSQL.")
class SeedPostgresTests(unittest.TestCase):
    def setUp(self):
        self.schema = "test_startup_" + uuid.uuid4().hex
        self.engine = create_engine(
            os.environ["TEST_DATABASE_URL"],
            execution_options={"schema_translate_map": {None: self.schema}},
        )
        with self.engine.begin() as connection:
            connection.execute(CreateSchema(self.schema))
        self.addCleanup(self.cleanup_schema)
        Base.metadata.create_all(self.engine)

    def cleanup_schema(self):
        try:
            with self.engine.begin() as connection:
                connection.execute(DropSchema(self.schema, cascade=True))
        finally:
            self.engine.dispose()

    def test_seed_respects_foreign_keys_and_does_not_duplicate_data(self):
        expected = {Workspace: 1, Team: 3, User: 5, Ticket: 10, TicketMessage: 10, KnowledgeItem: 5, AuditEvent: 1}
        with Session(self.engine) as session:
            self.assertEqual(len(seed_demo(session)), 4)
            self.assertEqual(seed_demo(session), [])
            for model, count in expected.items():
                with self.subTest(table=model.__tablename__):
                    self.assertEqual(session.scalar(select(func.count()).select_from(model)), count)


if __name__ == "__main__":
    unittest.main()
