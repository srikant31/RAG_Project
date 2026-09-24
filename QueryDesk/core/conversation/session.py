"""
QueryDesk — Conversation Session Manager
Manages multi-turn chat history per session in memory.
Persists sessions to disk for restart survival.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from QueryDesk.models.schemas import ChatMessage, ChatSession, MessageRole
from QueryDesk.utils.logger import logger

SESSIONS_PATH = Path("data/sessions")


class SessionManager:
    """
    In-memory session store with disk persistence.
    Each session maintains full conversation history for multi-turn context.
    """

    MAX_HISTORY_TURNS = 10  # Max turns to include in prompt context

    def __init__(self):
        SESSIONS_PATH.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, ChatSession] = {}
        logger.info("SessionManager initialized")

    def create_session(self) -> str:
        """Create a new chat session and return its ID."""
        session_id = str(uuid.uuid4())
        self._sessions[session_id] = ChatSession(session_id=session_id)
        logger.info(f"New session created: {session_id}")
        return session_id

    def get_session(self, session_id: str) -> Optional[ChatSession]:
        """Retrieve a session by ID."""
        if session_id in self._sessions:
            return self._sessions[session_id]
        # Try loading from disk
        return self._load_session(session_id)

    def add_message(self, session_id: str, message: ChatMessage) -> None:
        """Append a message to a session."""
        session = self.get_session(session_id)
        if not session:
            logger.warning(
                f"Session {session_id} not found — creating new session"
            )
            self._sessions[session_id] = ChatSession(session_id=session_id)
            session = self._sessions[session_id]

        session.messages.append(message)
        self._save_session(session)

    def get_history_for_prompt(self, session_id: str) -> list[dict]:
        """
        Return the last N turns of conversation formatted for the LLM prompt.

        Returns:
            List of {"role": str, "content": str} dicts
        """
        session = self.get_session(session_id)
        if not session:
            return []

        messages = session.messages[-self.MAX_HISTORY_TURNS * 2 :]
        return [
            {"role": msg.role.value, "content": msg.content}
            for msg in messages
            if msg.role in (MessageRole.USER, MessageRole.ASSISTANT)
        ]

    def clear_session(self, session_id: str) -> None:
        """Clear all messages in a session."""
        if session_id in self._sessions:
            self._sessions[session_id].messages = []
            self._save_session(self._sessions[session_id])
            logger.info(f"Session {session_id} cleared")

    def list_sessions(self, limit: Optional[int] = None) -> list[ChatSession]:
        """Return known sessions sorted by most recent activity."""
        sessions: dict[str, ChatSession] = dict(self._sessions)

        for path in SESSIONS_PATH.glob("*.json"):
            session_id = path.stem
            if session_id not in sessions:
                session = self._load_session(session_id)
                if session:
                    sessions[session_id] = session

        sorted_sessions = sorted(
            sessions.values(),
            key=lambda session: (
                session.messages[-1].timestamp if session.messages else session.created_at
            ),
            reverse=True,
        )
        return sorted_sessions[:limit] if limit else sorted_sessions

    def _save_session(self, session: ChatSession) -> None:
        """Persist a session to disk as JSON."""
        try:
            path = SESSIONS_PATH / f"{session.session_id}.json"
            with open(path, "w", encoding="utf-8") as f:
                f.write(session.model_dump_json())
        except Exception as e:
            logger.warning(f"Failed to persist session {session.session_id}: {e}")

    def _load_session(self, session_id: str) -> Optional[ChatSession]:
        """Load a session from disk."""
        path = SESSIONS_PATH / f"{session_id}.json"
        if not path.exists():
            return None
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            session = ChatSession(**data)
            self._sessions[session_id] = session
            return session
        except Exception as e:
            logger.warning(f"Failed to load session {session_id} from disk: {e}")
            return None
