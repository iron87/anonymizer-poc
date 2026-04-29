from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4


@dataclass
class SessionState:
    # placeholder → original value  (for deanonymization)
    vault: dict[str, str] = field(default_factory=dict)
    # original value → placeholder  (dedup: same value reuses same placeholder)
    reverse: dict[str, str] = field(default_factory=dict)
    # entity_type → counter         (e.g. PERSON → 2 means next is _3)
    counters: dict[str, int] = field(default_factory=dict)
    last_sanitized_prompt: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class VaultStore:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}

    def get_or_create(self, session_id: str | None = None) -> tuple[str, SessionState]:
        sid = session_id or str(uuid4())
        if sid not in self._sessions:
            self._sessions[sid] = SessionState()
        return sid, self._sessions[sid]

    def get(self, session_id: str) -> SessionState | None:
        return self._sessions.get(session_id)

    def set_last_prompt(self, session_id: str, prompt: str) -> None:
        self._sessions[session_id].last_sanitized_prompt = prompt

    def stats(self) -> dict[str, int]:
        return {"sessions": len(self._sessions)}
