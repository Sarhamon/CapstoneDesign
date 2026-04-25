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
    """
    FocusGuard 이벤트를 JSONL 파일에 기록하는 로거.

    각 이벤트는 JSON 한 줄(JSONL 형식)로 저장되며, 타임스탬프·종류·사유를 포함한다.
    파일은 Config.LOG_DIR 디렉토리 안의 events.jsonl에 누적 저장된다.
    """

    def __init__(self):
        # 로그 파일 경로를 설정하고, 디렉토리가 없으면 자동으로 생성한다.
        self.log_path = Path(Config.LOG_DIR) / "events.jsonl"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_block(self, stage: str, reason: str, llm_result: str = ""):
        """
        차단 이벤트를 기록한다.

        Args:
            stage: 탐지 단계 식별자.
                   "TITLE_MATCH" | "URL_MATCH" | "KEYWORD_MATCH" |
                   "WINDOW_CLOSE" | "PROCESS_KILL"
            reason: 차단 원인을 설명하는 문자열 (예: 감지된 키워드, 창 제목 등).
            llm_result: LLM 판정 결과 ("BLOCK" | "ALLOW" | "UNSURE").
                        규칙 기반 즉시 차단 시에는 "RULE_BASED"를 전달한다.
        """
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
        """
        차단 해제 요청 이벤트를 기록한다.

        Args:
            block_reason: 이번 해제 요청의 원인이 된 차단 사유 문자열.
            student_note: 해제 시 남기는 메모 (현재는 인증 결과 문자열을 전달).
        """
        event = {
            "timestamp": datetime.now().isoformat(),
            "type": "UNLOCK_REQUEST",
            "block_reason": block_reason,
            "student_note": student_note,
        }
        self._write(event)
        logger.info(f"[해제 요청] {student_note or '사유 없음'}")

    def log_allow(self, window_title: str):
        """
        LLM이 ALLOW 또는 UNSURE로 판단하여 허용한 이벤트를 기록한다.

        Args:
            window_title: 허용된 창의 제목 또는 탐지 사유 문자열.
        """
        event = {
            "timestamp": datetime.now().isoformat(),
            "type": "ALLOW",
            "window_title": window_title,
        }
        self._write(event)

    def _write(self, event: dict):
        """
        이벤트 딕셔너리를 JSONL 파일에 한 줄로 추가한다.

        파일 쓰기 오류가 발생해도 예외를 전파하지 않고 로그만 남겨,
        로거 오류가 메인 모니터링 루프를 중단시키지 않도록 한다.

        Args:
            event: 기록할 이벤트 데이터 딕셔너리.
        """
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                # ensure_ascii=False: 한글이 이스케이프되지 않고 원문으로 저장된다.
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"로그 저장 오류: {e}")
