"""Local daily-source scheduler. Runs while the local application stack is running."""
import json
import os
import signal
import threading
import urllib.request
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    token = os.environ.get("AGENT_SEARCH_TOKEN", "")
    if not token:
        for line in (root / ".dev.vars").read_text().splitlines():
            key, _, value = line.partition("=")
            if key == "AGENT_SEARCH_TOKEN":
                token = value.strip().strip('"\'')
    if len(token) < 32:
        raise RuntimeError("Missing scheduler credential")
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    while not stop.is_set():
        request = urllib.request.Request(
            "http://localhost:5178/api/job-sources/refresh-due", data=b"{}",
            headers={"Authorization": f"Bearer {token}", "Origin": "http://localhost:5178", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=500) as response:
                result = json.load(response)
                if result.get("checked"):
                    print(f"Sources refreshed: {result['checked']}", flush=True)
        except Exception:
            print("Source scheduler: service unavailable; retrying in 60 seconds", flush=True)
        stop.wait(60)


if __name__ == "__main__":
    main()
