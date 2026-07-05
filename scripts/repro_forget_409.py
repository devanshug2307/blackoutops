"""Minimal repro: remember() into a previously forget()-ed dataset name 409s forever.

Observed on Cognee Cloud (server 1.2.2.dev0, SDK 1.2.2), 2026-07-05.

    A: remember -> forget(full) -> remember      => 409 RetryError[ProgrammingError]
    B: remember -> forget(memory_only) -> remember => OK

Run: python scripts/repro_forget_409.py   (needs COGNEE_BASE_URL / COGNEE_API_KEY in .env)
"""

import asyncio
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from dns_fallback import ensure_resolvable  # noqa: E402

BASE_URL = os.environ["COGNEE_BASE_URL"].strip('"')
API_KEY = os.environ["COGNEE_API_KEY"].strip('"')


async def cycle(name: str, memory_only: bool) -> str:
    import cognee

    await cognee.remember("v1", dataset_name=name)
    await cognee.forget(dataset=name, memory_only=memory_only)
    try:
        await cognee.remember("v2", dataset_name=name)
        return "re-remember OK"
    except Exception as e:
        return f"re-remember FAILED: {str(e)[:140]}"


async def main():
    ensure_resolvable(urllib.parse.urlparse(BASE_URL).hostname)
    import cognee

    await cognee.serve(url=BASE_URL, api_key=API_KEY)
    print("A (full forget):       ", await cycle("repro_409_full", memory_only=False))
    print("B (memory-only forget):", await cycle("repro_409_memonly", memory_only=True))
    await cognee.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
