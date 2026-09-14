"""Start the local, real-account Codex + knowledge + web stack. No synthetic identity."""

import argparse
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
PYTHON = str(ROOT / "services/agent/.venv/bin/python")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--developer", action="store_true", help="Enable read-only local developer inspection in Settings")
    args = parser.parse_args()
    path = ROOT / ".dev.vars"
    lines = path.read_text().splitlines() if path.exists() else []
    values = {}
    for line in lines:
        key, sep, value = line.partition("=")
        if sep and not line.lstrip().startswith("#"):
            values[key.strip()] = value.strip().strip('\"\'')
    for name, port in (("KNOWLEDGE", 8767), ("SEARCH", 8766), ("ASSISTANT", 8780)):
        values[f"AGENT_{name}_URL"] = f"http://127.0.0.1:{port}"
        key = f"AGENT_{name}_TOKEN"
        if len(values.get(key, "")) < 32:
            values[key] = secrets.token_hex(32)
    changed = {key: value for key, value in values.items() if key.startswith(("AGENT_KNOWLEDGE_", "AGENT_SEARCH_", "AGENT_ASSISTANT_"))}
    new_lines = [line for line in lines if line.partition("=")[0].strip() not in changed]
    new_lines.extend(f"{key}={value}" for key, value in changed.items())
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write("\n".join(new_lines) + "\n")
    path.chmod(0o600)
    environment = {**os.environ, **changed, "GETOFFERS_LOCAL_CODEX": "1", "GETOFFERS_LOCAL_DEVELOPER": "1" if args.developer else "0"}
    commands = [
        [PYTHON, "-m", "getoffers_agent.knowledge.cli", "serve", "--port", "8767"],
        [PYTHON, "-m", "getoffers_agent.job_search.cli", "serve", "--port", "8766"],
        [PYTHON, "-m", "getoffers_agent.assistant.server", "--local-codex", *(["--developer-tools"] if args.developer else [])],
        ["npm", "run", "dev", "--", "--port", "5178"],
        [PYTHON, "scripts/job-sources-scheduler.py"],
    ]
    children = []
    def stop(*_):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        for command in commands:
            children.append(subprocess.Popen(command, env=environment, start_new_session=True))
        print("Open http://localhost:5178/ — Codex connects automatically.", flush=True)
        while True:
            for child in children:
                if child.poll() is not None:
                    raise RuntimeError("A local service stopped; see its error above.")
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for child in children:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()


if __name__ == "__main__":
    main()
