"""MCP stdio client used by the voice orchestrator for durable context."""
from __future__ import annotations

import json
import os
import sys
from contextlib import AsyncExitStack


class VoiceContextClient:
    def __init__(self, cfg: dict, base_dir: str):
        self.enabled = bool(cfg.get("enabled", True))
        self.session_id = str(cfg.get("session_id") or "smart-home")
        self.history_rounds = max(0, int(cfg.get("history_rounds", 6)))
        server = str(cfg.get("server_path") or "voice_context_server.py")
        store = str(cfg.get("store_path") or "data/voice_context.json")
        self.server_path = server if os.path.isabs(server) else os.path.join(base_dir, server)
        self.store_path = store if os.path.isabs(store) else os.path.join(base_dir, store)
        self.max_turns = max(self.history_rounds, int(cfg.get("max_turns", 20)))
        self.ttl_hours = max(1.0, float(cfg.get("ttl_hours", 24.0)))
        self._stack: AsyncExitStack | None = None
        self._session = None

    @property
    def online(self) -> bool:
        return self._session is not None

    async def start(self) -> bool:
        if not self.enabled:
            return False
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        stack = AsyncExitStack()
        try:
            params = StdioServerParameters(
                command=sys.executable,
                args=[self.server_path, "--store", self.store_path,
                      "--max-turns", str(self.max_turns),
                      "--ttl-hours", str(self.ttl_hours)],
                cwd=os.path.dirname(self.server_path),
            )
            read, write = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self._stack = stack
            self._session = session
            return True
        except Exception:
            await stack.aclose()
            raise

    @staticmethod
    def _text(result) -> str:
        if getattr(result, "isError", False):
            raise RuntimeError("context MCP tool returned an error")
        return "".join(getattr(item, "text", "") for item in result.content)

    async def get_context(self) -> dict:
        if not self._session or self.history_rounds <= 0:
            return {"session_id": self.session_id, "turns": []}
        result = await self._session.call_tool("get_conversation_context", {
            "session_id": self.session_id, "limit": self.history_rounds})
        return json.loads(self._text(result) or "{}")

    async def record_turn(self, user: str, assistant: str,
                          tool_results: list[dict]) -> None:
        if not self._session:
            return
        result = await self._session.call_tool("record_conversation_turn", {
            "session_id": self.session_id,
            "user": user,
            "assistant": assistant,
            "tool_results_json": json.dumps(tool_results, ensure_ascii=False),
        })
        body = json.loads(self._text(result) or "{}")
        if not body.get("ok"):
            raise RuntimeError(str(body.get("error") or "context record failed"))

    async def close(self) -> None:
        self._session = None
        if self._stack is not None:
            stack, self._stack = self._stack, None
            await stack.aclose()
