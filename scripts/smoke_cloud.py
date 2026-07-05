"""End-to-end smoke test against the Cognee Cloud tenant: serve -> remember -> recall -> forget."""

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


async def main():
    host = urllib.parse.urlparse(BASE_URL).hostname
    print("[dns]", ensure_resolvable(host))

    import cognee

    client = await cognee.serve(url=BASE_URL, api_key=API_KEY)
    print("[serve] connected:", type(client).__name__)

    result = await cognee.remember(
        "BlackoutOps smoke test: the incident memory brain is online.",
        dataset_name="smoke_test",
    )
    print("[remember] ->", str(result)[:200])

    answers = await cognee.recall(
        "What is the status of the incident memory brain?",
        datasets=["smoke_test"],
    )
    for a in answers[:3]:
        print("[recall] ->", str(a)[:300])

    gone = await cognee.forget(dataset="smoke_test")
    print("[forget] ->", str(gone)[:200])

    await cognee.disconnect()
    print("SMOKE TEST PASSED")


if __name__ == "__main__":
    asyncio.run(main())
