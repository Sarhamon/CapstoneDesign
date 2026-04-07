"""
event_logger.py
차단 이벤트 로컬 로그 저장
- 현재: JSON 파일 저장
- 추후: 클라우드 DB 전송으로 확장
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from config import Config

logger = logging.getLogger(__name__)


class EventLogger:
    def __init__(self):
        self.log_path = Path(Config.LOG_DIR) / "events.jsonl"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_block(self, stage: str, reason: str, llm_result: str = ""):
        event = {
            "timestamp": datetime.now().isoformat(),
            "type": "BLOCK",
            "stage": stage,          # TITLE_MATCH / URL_MATCH / KEYWORD_MATCH / LLM
            "reason": reason,
            "llm_result": llm_result,
        }
        self._write(event)
        logger.info(f"[차단 이벤트] {stage} | {reason}")

    def log_unlock_request(self, block_reason: str, student_note: str):
        event = {
            "timestamp": datetime.now().isoformat(),
            "type": "UNLOCK_REQUEST",
            "block_reason": block_reason,
            "student_note": student_note,
        }
        self._write(event)
        logger.info(f"[해제 요청] {student_note or '사유 없음'}")

    def log_allow(self, window_title: str):
        event = {
            "timestamp": datetime.now().isoformat(),
            "type": "ALLOW",
            "window_title": window_title,
        }
        self._write(event)

    def _write(self, event: dict):
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"로그 저장 오류: {e}")