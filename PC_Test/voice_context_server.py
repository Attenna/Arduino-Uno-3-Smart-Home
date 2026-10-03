"""Voice conversation context MCP server.

The voice orchestrator uses this server itself instead of exposing its mutation
tools to the language model.  That keeps context deterministic: only completed
turns and actual hardware results are persisted.
"""
from __future__ import annotations

import argparse
import json
import os
import threading
import time
from pathlib import Path

def _clean_text(value, limit: int = 2000) -> str:
    return " ".join(str(value or "").split())[:limit]


class ConversationContextStore:
    """Small, atomic JSON store keyed by conversation session."""

    def __init__(self, path: str | Path, max_turns: int = 20,
                 ttl_hours: float = 24.0):
        self.path = Path(path)
        self.max_turns = max(1, int(max_turns))
        self.ttl_s = max(60.0, float(ttl_hours) * 3600.0)
        self._lock = threading.RLock()

    def _load(self) -> dict:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(value, dict) and isinstance(value.get("sessions"), dict):
                return value
        except (OSError, ValueError, TypeError):
            pass
        return {"version": 1, "sessions": {}}

    def _save(self, value: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        os.replace(temp, self.path)

    def get(self, session_id: str, limit: int = 6) -> dict:
        now = time.time()
        sid = _clean_text(session_id, 80) or "default"
        with self._lock:
            root = self._load()
            session = root["sessions"].get(sid) or {}
            turns = session.get("turns") if isinstance(session.get("turns"), list) else []
            turns = [t for t in turns
                     if now - float(t.get("timestamp") or 0) <= self.ttl_s]
            limit = max(0, min(int(limit), self.max_turns))
            return {"session_id": sid, "turns": turns[-limit:] if limit else [],
                    "updated_at": session.get("updated_at")}

    def record(self, session_id: str, user: str, assistant: str,
               tool_results: list | None = None) -> dict:
        sid = _clean_text(session_id, 80) or "default"
        tools = []
        for raw in (tool_results or [])[:12]:
            if not isinstance(raw, dict):
                continue
            tools.append({
                "name": _clean_text(raw.get("name"), 80),
                "arguments": raw.get("arguments")
                if isinstance(raw.get("arguments"), dict) else {},
                "ok": bool(raw.get("ok")),
                "result": _clean_text(raw.get("result"), 500),
            })
        turn = {"timestamp": time.time(), "user": _clean_text(user),
                "assistant": _clean_text(assistant), "tool_results": tools}
        with self._lock:
            root = self._load()
            session = root["sessions"].setdefault(sid, {"turns": []})
            session.setdefault("turns", []).append(turn)
            session["turns"] = session["turns"][-self.max_turns:]
            session["updated_at"] = turn["timestamp"]
            self._save(root)
        return {"ok": True, "session_id": sid,
                "turn_count": len(session["turns"])}

    def clear(self, session_id: str) -> dict:
        sid = _clean_text(session_id, 80) or "default"
        with self._lock:
            root = self._load()
            existed = root["sessions"].pop(sid, None) is not None
            self._save(root)
        return {"ok": True, "session_id": sid, "cleared": existed}


def build_mcp(store: ConversationContextStore):
    """Build lazily so storage tests do not require the optional MCP package."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("voice-conversation-context")

    @server.tool()
    def get_conversation_context(session_id: str = "default", limit: int = 6) -> str:
        """Return recent confirmed voice turns and their real tool outcomes."""
        return json.dumps(store.get(session_id, limit), ensure_ascii=False)

    @server.tool()
    def record_conversation_turn(session_id: str, user: str, assistant: str,
                                 tool_results_json: str = "[]") -> str:
        """Persist one completed turn. tool_results_json must be a JSON array."""
        try:
            tools = json.loads(tool_results_json or "[]")
            if not isinstance(tools, list):
                raise ValueError("tool_results_json must be an array")
        except (ValueError, TypeError) as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
        return json.dumps(store.record(session_id, user, assistant, tools),
                          ensure_ascii=False)

    @server.tool()
    def clear_conversation_context(session_id: str = "default") -> str:
        """Clear one conversation session."""
        return json.dumps(store.clear(session_id), ensure_ascii=False)

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Voice conversation context MCP server")
    parser.add_argument("--store", default=os.environ.get(
        "SMART_HOME_VOICE_CONTEXT_PATH", "data/voice_context.json"))
    parser.add_argument("--max-turns", type=int, default=20)
    parser.add_argument("--ttl-hours", type=float, default=24.0)
    args = parser.parse_args()
    store = ConversationContextStore(args.store, args.max_turns, args.ttl_hours)
    build_mcp(store).run(transport="stdio")


if __name__ == "__main__":
    main()
