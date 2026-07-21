from sqlalchemy import Engine, inspect, text


def ensure_schema_compatibility(engine: Engine) -> None:
    """Apply additive SQLite migrations needed by existing local workspaces."""
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "generation_tasks" in table_names:
        task_columns = {column["name"] for column in inspector.get_columns("generation_tasks")}
        if "retry_not_before" not in task_columns:
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE generation_tasks ADD COLUMN retry_not_before DATETIME")
                )
    if "questions" in table_names:
        question_columns = {column["name"] for column in inspector.get_columns("questions")}
        missing_export_columns = {
            "last_exported_image1_id",
            "last_exported_image2_id",
        } - question_columns
        if not missing_export_columns:
            return
        with engine.begin() as connection:
            for column_name in sorted(missing_export_columns):
                connection.execute(
                    text(f"ALTER TABLE questions ADD COLUMN {column_name} VARCHAR(36)")
                )
