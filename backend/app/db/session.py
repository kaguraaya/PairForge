from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


def create_sqlite_engine(url: str) -> Engine:
    is_memory = url.endswith(":memory:")
    kwargs: dict[str, object] = {
        "connect_args": {"check_same_thread": False},
    }
    if is_memory:
        kwargs["poolclass"] = StaticPool

    engine = create_engine(url, **kwargs)

    @event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        if not is_memory:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    return engine


def database_url(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+pysqlite:///{path.as_posix()}"


def session_iterator(engine: Engine) -> Iterator[Session]:
    with Session(engine, expire_on_commit=False) as session:
        yield session

