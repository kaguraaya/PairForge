from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import create_sqlite_engine


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_sqlite_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
        db.rollback()
    engine.dispose()

