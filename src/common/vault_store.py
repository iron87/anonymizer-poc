from dataclasses import dataclass, field


@dataclass
class SessionState:
    vault: dict[str, str] = field(default_factory=dict)
    reverse: dict[str, str] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)


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

    def items(self) -> list[tuple[str, SessionState]]:
        return list(self._sessions.items())

    def stats(self) -> dict[str, int]:
        return {"sessions": len(self._sessions)}
