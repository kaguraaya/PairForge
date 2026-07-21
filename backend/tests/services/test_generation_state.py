import hashlib

import pytest
from sqlalchemy import select

from app.db.models import (
    GenerationBatch,
    GenerationRun,
    GenerationTask,
    ImageAsset,
    Project,
    ProviderProfile,
    Question,
)
from app.domain.enums import (
    BatchStatus,
    GenerationStage,
    OutputSemantics,
    QuestionState,
    RunStatus,
    TaskStatus,
)
from app.domain.errors import CrossQuestionReferenceError, MissingReferenceImageError
from app.services.generation import (
    create_run,
    finalize_task,
    pause_batch,
    resume_batch,
    retry_task,
    start_batch,
)
from app.services.selections import select_image1


def context(session, outputs: int = 1):
    project = Project(name="题库", workspace_path="C:/tmp", q1_prompt_suffix="第一图通用")
    session.add(project)
    session.flush()
    profile = ProviderProfile(
        project_id=project.id,
        provider="alibaba",
        display_name="Qwen",
        base_url="https://example.invalid",
        model_id="qwen-image-2.0",
    )
    q1 = Question(
        project_id=project.id,
        code="001",
        title="第一题",
        answer="答案一",
        image1_prompt="一图提示",
        image2_prompt="二图提示",
    )
    q2 = Question(
        project_id=project.id,
        code="002",
        title="第二题",
        answer="答案二",
        image1_prompt="另一个一图提示",
        image2_prompt="另一个二图提示",
    )
    session.add_all([profile, q1, q2])
    session.flush()
    batch = GenerationBatch(
        project_id=project.id,
        provider_profile_id=profile.id,
        start_code="001",
        end_code="002",
        question_count=2,
        q1_requested_outputs=outputs,
        q2_requested_outputs=1,
        q1_output_semantics=OutputSemantics.EXACT,
        q2_output_semantics=OutputSemantics.EXACT,
        image1_maximum=outputs * 2,
        image2_maximum=2,
        total_maximum=outputs * 2 + 2,
        status=BatchStatus.CONFIRMED,
    )
    session.add(batch)
    session.flush()
    return project, profile, q1, q2, batch


def add_asset(session, task, question, stage, index, reference_id=None):
    asset = ImageAsset(
        task_id=task.id,
        question_id=question.id,
        stage=stage,
        output_index=index,
        local_path=f"C:/tmp/{question.code}-{stage.value}-{index}.png",
        sha256=hashlib.sha256(f"{question.id}-{stage}-{index}".encode()).hexdigest(),
        width=32,
        height=32,
        mime_type="image/png",
        file_size=100,
        reference_asset_id=reference_id,
        prompt_snapshot="快照",
        provider="fake",
        model="fake",
    )
    session.add(asset)
    session.flush()
    return asset


def test_second_run_requires_selected_first_image(session) -> None:
    _, _, q1, _, batch = context(session)
    with pytest.raises(MissingReferenceImageError):
        create_run(session, batch, q1, GenerationStage.IMAGE2)


def test_cross_question_selection_is_rejected(session) -> None:
    _, _, q1, q2, batch = context(session)
    _, task = create_run(session, batch, q1, GenerationStage.IMAGE1)
    wrong = add_asset(session, task, q2, GenerationStage.IMAGE1, 1)
    with pytest.raises(CrossQuestionReferenceError):
        select_image1(session, q1.id, wrong.id)


def test_one_actual_result_auto_chains_same_question(session) -> None:
    _, _, q1, q2, batch = context(session, outputs=3)
    tasks = start_batch(session, batch.id)
    first_task = next(task for task in tasks if session.get(GenerationRun, task.run_id).question_id == q1.id)
    asset = add_asset(session, first_task, q1, GenerationStage.IMAGE1, 1)
    first_task.status = TaskStatus.SUCCEEDED
    finalize_task(session, first_task.id)

    assert q1.selected_image1_id == asset.id
    assert q1.state == QuestionState.IMAGE2_QUEUED
    q2_run = session.scalar(
        select(GenerationRun).where(
            GenerationRun.question_id == q1.id,
            GenerationRun.stage == GenerationStage.IMAGE2,
        )
    )
    assert q2_run is not None and q2_run.reference_asset_id == asset.id
    assert q2_run.original_prompt == q1.image2_prompt
    assert q2_run.question_id != q2.id


def test_multiple_actual_results_wait_for_review(session) -> None:
    _, _, q1, _, batch = context(session, outputs=2)
    run, task = create_run(session, batch, q1, GenerationStage.IMAGE1)
    add_asset(session, task, q1, GenerationStage.IMAGE1, 1)
    add_asset(session, task, q1, GenerationStage.IMAGE1, 2)
    task.status = TaskStatus.SUCCEEDED
    finalize_task(session, task.id)
    assert run.status == RunStatus.REVIEW
    assert q1.state == QuestionState.IMAGE1_REVIEW
    assert q1.selected_image1_id is None


def test_changing_first_image_invalidates_second(session) -> None:
    _, _, q1, _, batch = context(session, outputs=2)
    run, task = create_run(session, batch, q1, GenerationStage.IMAGE1)
    first = add_asset(session, task, q1, GenerationStage.IMAGE1, 1)
    replacement = add_asset(session, task, q1, GenerationStage.IMAGE1, 2)
    select_image1(session, q1.id, first.id)
    second_run, second_task = create_run(session, batch, q1, GenerationStage.IMAGE2)
    second = add_asset(
        session, second_task, q1, GenerationStage.IMAGE2, 1, reference_id=first.id
    )
    second.selected = True
    q1.selected_image2_id = second.id
    q1.state = QuestionState.COMPLETED
    session.flush()

    select_image1(session, q1.id, replacement.id)
    assert second.stale is True
    assert q1.selected_image2_id is None
    assert q1.state == QuestionState.IMAGE2_READY
    assert second_run.reference_asset_id == first.id

    regenerated_run, regenerated_task = create_run(
        session, batch, q1, GenerationStage.IMAGE2
    )
    assert regenerated_run.id == second_run.id
    assert regenerated_run.reference_asset_id == replacement.id
    assert regenerated_task.id != second_task.id
    assert regenerated_task.request_index == 2


def test_failed_task_can_be_retried_once_without_reusing_idempotency_key(session) -> None:
    _, _, q1, _, batch = context(session)
    run, failed = create_run(session, batch, q1, GenerationStage.IMAGE1)
    failed.status = TaskStatus.FAILED
    run.status = RunStatus.FAILED
    q1.state = QuestionState.FAILED
    session.flush()

    retried = retry_task(session, failed.id)

    assert retried.id != failed.id
    assert retried.idempotency_key != failed.idempotency_key
    assert retried.request_index == 2
    assert retried.status == TaskStatus.QUEUED
    assert q1.state == QuestionState.IMAGE1_QUEUED


def test_paused_batch_resumes_queued_and_interrupted_work(session) -> None:
    _, _, q1, _, batch = context(session)
    tasks = start_batch(session, batch.id)
    first = tasks[0]
    first_run = session.get(GenerationRun, first.run_id)

    held = pause_batch(session, batch.id)
    assert set(held) == {task.id for task in tasks}
    assert batch.status == BatchStatus.PAUSED

    first.status = TaskStatus.INTERRUPTED
    first_run.status = RunStatus.INTERRUPTED
    q1.state = QuestionState.INTERRUPTED
    queued, released = resume_batch(session, batch.id)

    assert set(released) == {task.id for task in tasks}
    assert batch.status == BatchStatus.RUNNING
    assert len(queued) == 2
    retry = session.scalar(
        select(GenerationTask).where(
            GenerationTask.run_id == first_run.id,
            GenerationTask.status == TaskStatus.QUEUED,
        )
    )
    assert retry is not None
    assert retry.id != first.id
    assert q1.state == QuestionState.IMAGE1_QUEUED
