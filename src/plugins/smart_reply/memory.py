from __future__ import annotations

import json
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Deque

from nonebot import get_driver

from .config import config

@dataclass(slots=True)
class MemoryTurn:
    role: str
    name: str
    content: str
    time: str


class ShortTermMemory:
    def __init__(self, path: Path, max_turns: int) -> None:
        self.path = path
        self.max_turns = max_turns
        self._sessions: dict[str, Deque[MemoryTurn]] = defaultdict(
            lambda: deque(maxlen=self.max_turns)
        )
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.path.exists():
            return

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        for session_id, turns in raw.items():
            session = deque(maxlen=self.max_turns)
            for item in turns[-self.max_turns :]:
                try:
                    session.append(MemoryTurn(**item))
                except TypeError:
                    continue
            self._sessions[session_id] = session

    def append(self, session_id: str, role: str, name: str, content: str) -> None:
        self._ensure_loaded()
        self._sessions[session_id].append(
            MemoryTurn(
                role=role,
                name=name[:40],
                content=content[:1200],
                time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
        )

    def get(self, session_id: str) -> list[MemoryTurn]:
        self._ensure_loaded()
        return list(self._sessions[session_id])

    def save(self) -> None:
        self._ensure_loaded()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            session_id: [asdict(turn) for turn in turns]
            for session_id, turns in self._sessions.items()
        }
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


memory = ShortTermMemory(
    Path("data") / "short_term_memory.json",
    max_turns=config.smart_reply_memory_turns,
)


@get_driver().on_shutdown
async def _save_memory_on_shutdown() -> None:
    memory.save()
