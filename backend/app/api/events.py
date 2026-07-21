import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import GenerationTask

router = APIRouter(prefix="/api", tags=["events"])


@router.get("/events")
async def events(request: Request) -> StreamingResponse:
    async def stream():
        last = None
        while not await request.is_disconnected():
            with Session(request.app.state.engine) as session:
                marker = session.execute(
                    select(func.count(GenerationTask.id), func.max(GenerationTask.updated_at))
                ).one()
            value = (marker[0], str(marker[1]))
            if value != last:
                yield f"event: tasks\ndata: {json.dumps({'count': value[0]})}\n\n"
                last = value
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream")

