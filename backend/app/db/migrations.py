from sqlalchemy import Engine, inspect, text


def ensure_schema_compatibility(engine: Engine) -> None:
    """Apply additive SQLite migrations needed by existing local workspaces."""
    inspector = inspect(engine)
    if "generation_tasks" not in inspector.get_table_names():
        return
    task_columns = {column["name"] for column in inspector.get_columns("generation_tasks")}
    if "retry_not_before" not in task_columns:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE generation_tasks ADD COLUMN retry_not_before DATETIME")
            )
