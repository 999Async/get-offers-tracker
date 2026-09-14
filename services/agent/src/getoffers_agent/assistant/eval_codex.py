"""Resolve a real local Codex evaluation provider, without reading credentials."""

import asyncio
import re

from getoffers_agent.assistant.codex import CodexProvider, account_info, executable, terminate


async def local_provider(model_name=None):
    account = await account_info()
    models = account["models"]
    if not models:
        raise ValueError("CODEX_MODEL_UNAVAILABLE")
    selected = model_name or next((m["id"] for m in models if m["default"]), models[0]["id"])
    if selected not in {m["id"] for m in models}:
        raise ValueError("CODEX_MODEL_UNAVAILABLE")
    process = await asyncio.create_subprocess_exec(
        executable(),
        "--version",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=10)
        version = output.decode().strip()
        if process.returncode or not re.fullmatch(r"codex-cli [0-9][0-9A-Za-z.+-]{0,80}", version):
            raise ValueError("CODEX_VERSION_UNAVAILABLE")
    finally:
        await terminate(process)
    provider = CodexProvider(selected)
    return provider, {
        "provider": "codex",
        "provider_version": provider.version,
        "model_name": selected,
        "cli_version": version,
        "pricing_configured": False,
    }
