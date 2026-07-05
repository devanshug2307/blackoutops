"""BlackoutOps — the morning-after incident brain.

FastAPI app exposing the four memory-lifecycle beats over the demo incident
datasets, plus a static war-room UI. All memory operations run on Cognee Cloud.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import traceback

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import memory
from demo.incident_data import (
    HISTORICAL,
    HISTORICAL_DATASET,
    LAST_NIGHT,
    LAST_NIGHT_DATASET,
    MORNING_POSTMORTEM,
)

seed_progress: dict = {"state": "idle", "done": 0, "total": 0, "error": None}


@contextlib.asynccontextmanager
async def lifespan(app):
    try:
        await memory.connect()
    except Exception:
        traceback.print_exc()
    yield


app = FastAPI(title="BlackoutOps", lifespan=lifespan)


@app.get("/api/status")
async def api_status():
    return {**memory.status(), "seed": seed_progress}


class SeedRequest(BaseModel):
    which: str = "all"  # "last_night" | "historical" | "all"


async def _run_seed(which: str):
    global seed_progress
    jobs = []
    if which in ("historical", "all"):
        jobs += [(a, HISTORICAL_DATASET) for a in HISTORICAL]
    if which in ("last_night", "all"):
        jobs += [(a, LAST_NIGHT_DATASET) for a in LAST_NIGHT]
    seed_progress.update(state="running", done=0, total=len(jobs), error=None)
    try:
        for text, dataset in jobs:
            await memory.ingest_artifacts([text], dataset)
            seed_progress["done"] += 1
        seed_progress["state"] = "done"
    except Exception as e:
        traceback.print_exc()
        seed_progress.update(state="error", error=str(e)[:400])


@app.post("/api/seed")
async def api_seed(req: SeedRequest):
    if seed_progress["state"] == "running":
        raise HTTPException(409, "seed already running")
    asyncio.create_task(_run_seed(req.which))
    return {"started": True, "which": req.which}


class AskRequest(BaseModel):
    question: str
    use_session: bool = True
    datasets: list[str] | None = None


@app.post("/api/ask")
async def api_ask(req: AskRequest):
    datasets = req.datasets or [LAST_NIGHT_DATASET, HISTORICAL_DATASET]
    try:
        result = await memory.ask(req.question, datasets=datasets, use_session=req.use_session)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(502, f"recall failed: {e}")
    # Session memory: store the exchange as a typed QAEntry so follow-up
    # questions have context and the answer can receive feedback.
    qa_id = None
    if req.use_session and result["answers"]:
        with contextlib.suppress(Exception):
            qa_id = await memory.store_qa(req.question, result["answers"][0]["text"][:800])
    return {**result, "qa_id": qa_id}


class FeedbackRequest(BaseModel):
    qa_id: str
    score: int  # 1 = not helpful, 5 = helpful
    text: str = ""


@app.post("/api/feedback")
async def api_feedback(req: FeedbackRequest):
    try:
        return await memory.add_feedback(req.qa_id, req.score, req.text)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(502, f"feedback failed: {e}")


@app.post("/api/postmortem")
async def api_postmortem():
    try:
        return await memory.file_postmortem(MORNING_POSTMORTEM, LAST_NIGHT_DATASET)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(502, f"improve failed: {e}")


class ForgetRequest(BaseModel):
    dataset: str


@app.post("/api/forget")
async def api_forget(req: ForgetRequest):
    if req.dataset not in (LAST_NIGHT_DATASET, HISTORICAL_DATASET):
        raise HTTPException(400, "unknown dataset")
    try:
        return await memory.purge(req.dataset)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(502, f"forget failed: {e}")


@app.get("/api/graph")
async def api_graph(dataset: str = LAST_NIGHT_DATASET):
    try:
        html = await memory.graph_html(dataset)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(502, f"visualize failed: {e}")
    if html is None:
        raise HTTPException(404, f"dataset {dataset} not found on tenant (seed first)")
    return HTMLResponse(html)


@app.get("/api/artifacts")
async def api_artifacts():
    return {
        "last_night": {"dataset": LAST_NIGHT_DATASET, "items": LAST_NIGHT},
        "historical": {"dataset": HISTORICAL_DATASET, "items": HISTORICAL},
        "postmortem": MORNING_POSTMORTEM,
    }


@app.get("/")
async def index():
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "index.html"))


app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")
