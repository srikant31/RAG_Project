"""
QueryDesk — Feedback Manager
Persists user feedback (thumbs up/down) on AI answers to disk.
Provides analytics aggregation for the dashboard.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from QueryDesk.models.schemas import FeedbackRecord, FeedbackType
from QueryDesk.utils.logger import logger

FEEDBACK_PATH = Path("data/feedback.json")


class FeedbackManager:
    """
    Manages user feedback on AI-generated answers.
    Stores feedback records to a JSON file on disk.
    """

    def __init__(self):
        self._feedback: list[dict] = self._load()
        logger.info(f"FeedbackManager initialized — {len(self._feedback)} records")

    def add_feedback(
        self,
        message_id: str,
        session_id: str,
        feedback_type: FeedbackType,
        comment: Optional[str] = None,
    ) -> FeedbackRecord:
        """Record a piece of user feedback."""
        record = FeedbackRecord(
            message_id=message_id,
            session_id=session_id,
            feedback_type=feedback_type,
            comment=comment,
        )
        entry = {
            "feedback_id": record.feedback_id,
            "message_id": record.message_id,
            "session_id": record.session_id,
            "feedback_type": record.feedback_type.value,
            "comment": record.comment,
            "timestamp": record.timestamp.isoformat(),
        }
        self._feedback.append(entry)
        self._save()
        logger.info(
            f"Feedback recorded: {record.feedback_type.value} "
            f"for message {message_id}"
        )
        return record

    def get_feedback_for_message(self, message_id: str) -> Optional[str]:
        """Return the feedback type for a specific message, or None."""
        for entry in reversed(self._feedback):
            if entry["message_id"] == message_id:
                return entry["feedback_type"]
        return None

    def get_analytics(self) -> dict:
        """Return aggregated feedback analytics."""
        total = len(self._feedback)
        positive = sum(
            1 for f in self._feedback if f["feedback_type"] == "positive"
        )
        negative = sum(
            1 for f in self._feedback if f["feedback_type"] == "negative"
        )
        recent_negative = [
            {
                "comment": f.get("comment", ""),
                "timestamp": f.get("timestamp", ""),
                "message_id": f.get("message_id", ""),
            }
            for f in self._feedback
            if f["feedback_type"] == "negative" and f.get("comment")
        ][-5:]

        return {
            "total": total,
            "positive": positive,
            "negative": negative,
            "satisfaction_rate": round(positive / total, 3) if total > 0 else 0.0,
            "recent_negative_comments": recent_negative,
        }

    def _save(self) -> None:
        FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(FEEDBACK_PATH, "w", encoding="utf-8") as f:
            json.dump(self._feedback, f, indent=2)

    def _load(self) -> list[dict]:
        if FEEDBACK_PATH.exists():
            try:
                with open(FEEDBACK_PATH, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return []
