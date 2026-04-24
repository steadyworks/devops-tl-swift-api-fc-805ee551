from typing import AsyncGenerator
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from backend.db.dal import (
    DALJobs,
    DAOJobsCreate,
    DAOJobsUpdate,
    FilterOp,
    InvalidFilterFieldError,
    OrderDirection,
)
from backend.db.data_models import JobStatus


@pytest.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False, future=True
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async_session = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        yield session


@pytest.mark.asyncio
async def test_create_and_get_job(db_session: AsyncSession) -> None:
    job_in = DAOJobsCreate(
        job_type="test",
        status=JobStatus.QUEUED,
        input_payload={"x": 1},
        result_payload=None,
        error_message=None,
        user_id=uuid4(),
        owner_id=uuid4(),
        photobook_id=None,
        started_at=None,
        completed_at=None,
        retry_count=None,
        max_retries=None,
        last_attempted_at=None,
    )
    created = await DALJobs.create(db_session, job_in)
    await db_session.commit()
    assert created.id is not None
    assert created.status == JobStatus.QUEUED

    fetched = await DALJobs.get_by_id(db_session, created.id)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.retry_count == 0
    assert fetched.max_retries == 3


@pytest.mark.asyncio
async def test_update_job(db_session: AsyncSession) -> None:
    job_in = DAOJobsCreate(
        job_type="gen",
        status=JobStatus.QUEUED,
        input_payload=None,
        result_payload=None,
        error_message=None,
        user_id=None,
        owner_id=uuid4(),
        photobook_id=None,
        started_at=None,
        completed_at=None,
        retry_count=None,
        max_retries=None,
        last_attempted_at=None,
    )
    created = await DALJobs.create(db_session, job_in)
    await db_session.commit()

    update_in = DAOJobsUpdate(status=JobStatus.DONE, error_message="done")
    updated = await DALJobs.update_by_id(db_session, created.id, update_in)
    assert updated is not None
    assert updated.status == JobStatus.DONE
    assert updated.error_message == "done"


@pytest.mark.asyncio
async def test_list_filter_sort(db_session: AsyncSession) -> None:
    await DALJobs.create(
        db_session,
        DAOJobsCreate(
            job_type="a",
            status=JobStatus.QUEUED,
            input_payload=None,
            result_payload=None,
            error_message=None,
            user_id=None,
            owner_id=uuid4(),
            photobook_id=None,
            started_at=None,
            completed_at=None,
            retry_count=None,
            max_retries=None,
            last_attempted_at=None,
        ),
    )
    await db_session.commit()
    await DALJobs.create(
        db_session,
        DAOJobsCreate(
            job_type="b",
            status=JobStatus.QUEUED,
            input_payload=None,
            result_payload=None,
            error_message=None,
            user_id=None,
            owner_id=uuid4(),
            photobook_id=None,
            started_at=None,
            completed_at=None,
            retry_count=None,
            max_retries=None,
            last_attempted_at=None,
        ),
    )
    await db_session.commit()

    jobs = await DALJobs.list_all(
        db_session,
        filters={"status": (FilterOp.EQ, JobStatus.QUEUED)},
        order_by=[("job_type", OrderDirection.ASC)],
    )
    assert len(jobs) == 2
    assert jobs[0].job_type == "a"
    assert jobs[1].job_type == "b"


@pytest.mark.asyncio
async def test_count_and_exists(db_session: AsyncSession) -> None:
    assert await DALJobs.count(db_session) == 0
    assert not await DALJobs.exists(db_session)

    await DALJobs.create(
        db_session,
        DAOJobsCreate(
            job_type="a",
            status=JobStatus.QUEUED,
            input_payload=None,
            result_payload=None,
            error_message=None,
            user_id=None,
            owner_id=uuid4(),
            photobook_id=None,
            started_at=None,
            completed_at=None,
            retry_count=None,
            max_retries=None,
            last_attempted_at=None,
        ),
    )
    await db_session.commit()
    assert await DALJobs.count(db_session) == 1
    assert await DALJobs.exists(db_session)

    assert await DALJobs.exists(
        db_session, filters={"status": (FilterOp.EQ, JobStatus.QUEUED)}
    )


@pytest.mark.asyncio
async def test_list_limit_offset(db_session: AsyncSession) -> None:
    for letter in ["a", "b", "c"]:
        await DALJobs.create(
            db_session,
            DAOJobsCreate(
                job_type=letter,
                status=JobStatus.QUEUED,
                input_payload=None,
                result_payload=None,
                error_message=None,
                user_id=None,
                owner_id=uuid4(),
                photobook_id=None,
                started_at=None,
                completed_at=None,
                retry_count=None,
                max_retries=None,
                last_attempted_at=None,
            ),
        )
        await db_session.commit()

    jobs = await DALJobs.list_all(
        db_session,
        filters={"status": (FilterOp.EQ, JobStatus.QUEUED)},
        order_by=[("job_type", OrderDirection.ASC)],
        limit=2,
        offset=1,
    )

    assert len(jobs) == 2
    assert [job.job_type for job in jobs] == ["b", "c"]


@pytest.mark.asyncio
async def test_invalid_filter_field_raises(db_session: AsyncSession) -> None:
    with pytest.raises(InvalidFilterFieldError):
        await DALJobs.list_all(
            db_session,
            filters={"not_a_field": (FilterOp.EQ, "some_value")},
        )


@pytest.mark.asyncio
async def test_invalid_order_field_raises(db_session: AsyncSession) -> None:
    with pytest.raises(InvalidFilterFieldError):
        await DALJobs.list_all(
            db_session,
            order_by=[("bad_field", OrderDirection.ASC)],
        )


@pytest.mark.asyncio
async def test_exists_works_without_filters(db_session: AsyncSession) -> None:
    assert not await DALJobs.exists(db_session)

    await DALJobs.create(
        db_session,
        DAOJobsCreate(
            job_type="x",
            status=JobStatus.QUEUED,
            input_payload=None,
            result_payload=None,
            error_message=None,
            user_id=None,
            owner_id=uuid4(),
            photobook_id=None,
            started_at=None,
            completed_at=None,
            retry_count=None,
            max_retries=None,
            last_attempted_at=None,
        ),
    )
    await db_session.commit()
    assert await DALJobs.exists(db_session)


@pytest.mark.asyncio
async def test_count_with_filters(db_session: AsyncSession) -> None:
    await DALJobs.create(
        db_session,
        DAOJobsCreate(
            job_type="a",
            status=JobStatus.DONE,
            input_payload=None,
            result_payload=None,
            error_message=None,
            user_id=None,
            owner_id=uuid4(),
            photobook_id=None,
            started_at=None,
            completed_at=None,
            retry_count=None,
            max_retries=None,
            last_attempted_at=None,
        ),
    )
    await db_session.commit()
    await DALJobs.create(
        db_session,
        DAOJobsCreate(
            job_type="b",
            status=JobStatus.QUEUED,
            input_payload=None,
            result_payload=None,
            error_message=None,
            user_id=None,
            owner_id=uuid4(),
            photobook_id=None,
            started_at=None,
            completed_at=None,
            retry_count=None,
            max_retries=None,
            last_attempted_at=None,
        ),
    )
    await db_session.commit()

    count = await DALJobs.count(
        db_session,
        filters={"status": (FilterOp.EQ, JobStatus.QUEUED)},
    )
    assert count == 1
