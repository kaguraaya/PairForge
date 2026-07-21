from sqlalchemy import inspect, text

from app.db.migrations import ensure_schema_compatibility
from app.db.session import create_sqlite_engine


def test_existing_task_table_gains_retry_timestamp(tmp_path) -> None:
    engine = create_sqlite_engine(f"sqlite+pysqlite:///{(tmp_path / 'legacy.sqlite3').as_posix()}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE generation_tasks (id VARCHAR(36) PRIMARY KEY)"))

    ensure_schema_compatibility(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("generation_tasks")}
    assert "retry_not_before" in columns
    engine.dispose()
