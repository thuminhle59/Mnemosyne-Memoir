"""Test config: point the store at a throwaway SQLite DB and reset it per test.

DATABASE_URL is set BEFORE importing config/db so load_dotenv (which does not
override existing env vars) can't pull in the real mnemosyne.db.
"""
import os
import tempfile

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.gettempdir(), "mnemosyne_test.db")

import pytest
import db as _db


@pytest.fixture(autouse=True)
def fresh_db():
    _db.Base.metadata.drop_all(_db.engine)
    _db.Base.metadata.create_all(_db.engine)
    yield
    _db.Base.metadata.drop_all(_db.engine)
