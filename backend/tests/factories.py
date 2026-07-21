from sqlalchemy.orm import Session

from app.db.models import (
    GenerationBatch,
    GenerationRun,
    Project,
    ProviderProfile,
    Question,
)
from app.domain.enums import (
    BatchStatus,
    GenerationStage,
    OutputSemantics,
    RunStatus,
)


def create_project(session: Session) -> Project:
    project = Project(name="测试项目", workspace_path="C:/workspace/test")
    session.add(project)
    session.commit()
    return project


def create_task_context(session: Session) -> tuple[GenerationRun, ProviderProfile]:
    project = create_project(session)
    profile = ProviderProfile(
        project_id=project.id,
        provider="fake",
        display_name="Fake",
        base_url="https://example.invalid",
        model_id="fake-model",
    )
    question = Question(
        project_id=project.id,
        code="001",
        title="第一题",
        answer="第一题",
        image1_prompt="图1",
        image2_prompt="图2",
    )
    session.add_all([profile, question])
    session.flush()
    batch = GenerationBatch(
        project_id=project.id,
        provider_profile_id=profile.id,
        start_code="001",
        end_code="001",
        question_count=1,
        q1_requested_outputs=1,
        q2_requested_outputs=1,
        q1_output_semantics=OutputSemantics.FIXED,
        q2_output_semantics=OutputSemantics.FIXED,
        image1_maximum=1,
        image2_maximum=1,
        total_maximum=2,
        status=BatchStatus.CONFIRMED,
    )
    session.add(batch)
    session.flush()
    run = GenerationRun(
        batch_id=batch.id,
        question_id=question.id,
        stage=GenerationStage.IMAGE1,
        original_prompt="图1",
        prompt_snapshot="图1",
        requested_outputs=1,
        output_semantics=OutputSemantics.FIXED,
        status=RunStatus.QUEUED,
    )
    session.add(run)
    session.flush()
    return run, profile

