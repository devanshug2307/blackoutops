"""BlackoutOps memory layer — a thin, honest wrapper over cognee's memory lifecycle.

Every public function here maps 1:1 to a cognee lifecycle call:

    ingest_artifacts()  -> cognee.remember(...)   permanent graph memory
    log_to_session()    -> cognee.remember(..., session_id=...)   session memory
    ask()               -> cognee.recall(...)     auto-routed graph + session recall
    file_postmortem()   -> cognee.remember(...) + cognee.improve(...)   memory that learns
    purge()             -> cognee.forget(dataset=...)   surgical deletion

The app keeps no state of its own beyond dataset ids — the knowledge lives in
Cognee Cloud, which is the whole point.
"""

from __future__ import annotations

import os
import urllib.parse
from typing import Any

import aiohttp
from dotenv import load_dotenv

import cognee

from dns_fallback import ensure_resolvable

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

BASE_URL = os.environ["COGNEE_BASE_URL"].strip('"')
API_KEY = os.environ["COGNEE_API_KEY"].strip('"')

SESSION_ID = "morning-after-debrief"

_state: dict[str, Any] = {
    "connected": False,
    "dns_note": None,
    "dataset_ids": {},  # dataset_name -> dataset_id (from RememberResult)
}


async def connect() -> dict:
    """serve() once at startup; reconnects are idempotent."""
    _state["dns_note"] = ensure_resolvable(urllib.parse.urlparse(BASE_URL).hostname)
    await cognee.serve(url=BASE_URL, api_key=API_KEY)
    _state["connected"] = True
    return {"connected": True, "dns": _state["dns_note"], "tenant": BASE_URL}


async def ingest_artifacts(artifacts: list[str], dataset: str) -> list[dict]:
    """REMEMBER: each artifact becomes permanent graph memory in `dataset`."""
    results = []
    for text in artifacts:
        r = await cognee.remember(text, dataset_name=dataset)
        info = r if isinstance(r, dict) else getattr(r, "__dict__", {"result": str(r)})
        if isinstance(info, dict) and info.get("dataset_id"):
            _state["dataset_ids"][dataset] = info["dataset_id"]
        results.append(
            {
                "status": (info.get("status") if isinstance(info, dict) else "completed"),
                "dataset": dataset,
            }
        )
    return results


async def store_qa(question: str, answer: str) -> str | None:
    """REMEMBER (session, typed): each debrief exchange is stored as a typed
    QAEntry in session memory, so it can carry structured feedback later."""
    result = await cognee.remember(
        cognee.QAEntry(question=question, answer=answer), session_id=SESSION_ID
    )
    return getattr(result, "entry_id", None) or (
        result.get("entry_id") if isinstance(result, dict) else None
    )


async def add_feedback(qa_id: str, score: int, text: str = "") -> dict:
    """FEEDBACK: a typed FeedbackEntry attached to the QA memory it judges —
    human signal stored alongside the answer in Cognee session memory."""
    result = await cognee.remember(
        cognee.FeedbackEntry(qa_id=qa_id, feedback_score=score, feedback_text=text or None),
        session_id=SESSION_ID,
    )
    return {"status": getattr(result, "status", str(result))}


async def ask(
    question: str,
    datasets: list[str],
    use_session: bool = True,
    top_k: int = 12,
) -> dict:
    """RECALL: auto-routed search over graph + session memory.

    If every requested dataset has been forgotten, the tenant reports that
    recall prerequisites aren't met — which we surface as the truthful answer:
    the brain has no memory of it.
    """
    try:
        entries = await cognee.recall(
            question,
            datasets=datasets or None,
            session_id=SESSION_ID if use_session else None,
            top_k=top_k,
            auto_route=True,
        )
    except Exception as e:
        if "prerequisites not met" in str(e) or "404" in str(e):
            return {
                "answers": [
                    {
                        "kind": "no_memory",
                        "text": "I have no memory of that. That incident was forgotten — "
                        "the dataset no longer exists in Cognee Cloud.",
                        "dataset": None,
                    }
                ],
                "contexts": [],
                "routed_over": datasets,
            }
        raise
    answers, contexts = [], []
    for e in entries:
        d = e if isinstance(e, dict) else getattr(e, "__dict__", {})
        kind = d.get("kind") or d.get("search_type") or "entry"
        text = d.get("text") or d.get("value") or str(e)
        item = {
            "kind": str(kind),
            "text": str(text),
            "dataset": d.get("dataset_name"),
        }
        (answers if "completion" in str(kind).lower() else contexts).append(item)
    if not answers and not contexts:
        answers = [
            {
                "kind": "no_memory",
                "text": "I have no memory of that — nothing in these datasets matches.",
                "dataset": None,
            }
        ]
    return {"answers": answers, "contexts": contexts[:8], "routed_over": datasets}


async def file_postmortem(postmortem_text: str, dataset: str) -> dict:
    """IMPROVE: feed the human-confirmed root cause back into graph memory,
    then attempt the dedicated improve() enrichment pass.

    The postmortem goes through the full cloud remember pipeline (add +
    cognify), which links the confirmed pattern into the incident graph. On
    tenants that don't expose the dedicated improve() route yet, that pipeline
    is the enrichment we get — reported honestly in the receipt.
    """
    await cognee.remember(postmortem_text, dataset_name=dataset)
    try:
        improve_result = await cognee.improve(dataset=dataset)
        improve_note = str(improve_result)[:300] if improve_result is not None else "completed"
    except Exception as e:
        improve_note = (
            "postmortem processed by the full remember pipeline; dedicated "
            f"improve() route not exposed on this tenant ({str(e)[:90]})"
        )
    return {"postmortem": "stored", "improve": improve_note, "dataset": dataset}


async def purge(dataset: str) -> dict:
    """FORGET: surgical, dataset-scoped deletion. Returns cognee's own receipt.

    memory_only=True wipes the dataset's graph/vector memory but keeps the
    relational dataset row. We found (and reported upstream) that a FULL
    forget() on this Cloud build tombstones the dataset name forever — any
    later remember() into it 409s with RetryError[ProgrammingError]. Memory-
    only deletion gives the same demo-visible guarantee (recall knows nothing)
    while keeping incident names reusable.
    """
    result = await cognee.forget(dataset=dataset, memory_only=True)
    _state["dataset_ids"].pop(dataset, None)
    return result if isinstance(result, dict) else {"status": str(result)}


async def graph_html(dataset: str) -> str | None:
    """Proxy the tenant's graph visualization for `dataset` (X-Api-Key auth)."""
    dataset_id = _state["dataset_ids"].get(dataset)
    if dataset_id is None:
        dataset_id = await _lookup_dataset_id(dataset)
    if dataset_id is None:
        return None
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
        async with session.get(
            f"{BASE_URL}/api/v1/visualize",
            params={"dataset_id": str(dataset_id)},
            headers={"X-Api-Key": API_KEY},
        ) as resp:
            resp.raise_for_status()
            return await resp.text()


async def _lookup_dataset_id(dataset: str) -> str | None:
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        async with session.get(
            f"{BASE_URL}/api/v1/datasets/", headers={"X-Api-Key": API_KEY}
        ) as resp:
            resp.raise_for_status()
            for d in await resp.json():
                if d.get("name") == dataset:
                    _state["dataset_ids"][dataset] = d["id"]
                    return d["id"]
    return None


def status() -> dict:
    return {
        "connected": _state["connected"],
        "dns": _state["dns_note"],
        "tenant": BASE_URL.split("//")[-1].split(".")[0],
        "datasets": _state["dataset_ids"],
        "session_id": SESSION_ID,
    }
