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


def test_existing_question_table_gains_incremental_export_markers(tmp_path) -> None:
    engine = create_sqlite_engine(f"sqlite+pysqlite:///{(tmp_path / 'legacy.sqlite3').as_posix()}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE questions (id VARCHAR(36) PRIMARY KEY)"))

    ensure_schema_compatibility(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("questions")}
    assert {"last_exported_image1_id", "last_exported_image2_id"} <= columns
    engine.dispose()


def test_existing_profile_table_gains_archive_marker_even_when_questions_are_current(
    tmp_path,
) -> None:
    engine = create_sqlite_engine(
        f"sqlite+pysqlite:///{(tmp_path / 'legacy.sqlite3').as_posix()}"
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE provider_profiles "
                "(id VARCHAR(36) PRIMARY KEY)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE questions ("
                "id VARCHAR(36) PRIMARY KEY, "
                "last_exported_image1_id VARCHAR(36), "
                "last_exported_image2_id VARCHAR(36))"
            )
        )

    ensure_schema_compatibility(engine)

    columns = {
        column["name"] for column in inspect(engine).get_columns("provider_profiles")
    }
    assert "archived" in columns
    engine.dispose()
