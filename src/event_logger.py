"""
event_logger.py
차단 이벤트 저장 레이어
- 데이터 모델: BlockEvent / UnlockRequestEvent / AllowEvent (frozen dataclass)
- Sink 추상화: EventSink → LocalJSONLSink (현재) / 추후 RemoteDBSink (Phase 2)
- Facade: EventLogger — 종류별 헬퍼만 제공, 실제 저장은 sink가 담당
- 디바이스 식별자(ip/mac) 및 잠금 세션 추적
"""

import json
import logging
import socket
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar
from config import Config

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now().isoformat()


@dataclass(frozen=True)
class BlockEvent:
    """규칙 기반 또는 LLM 검증으로 차단된 이벤트."""
    stage: str
    reason: str
    llm_result: str = ""
    ip: str = "unknown"
    mac: str = "unknown"
    timestamp: str = field(default_factory=_now_iso)

    type: ClassVar[str] = "BLOCK"

    def to_dict(self) -> dict:
        """이벤트를 JSON 직렬화 가능한 dict로 변환한다."""
        return {
            "timestamp": self.timestamp,
            "type": self.type,
            "stage": self.stage,
            "reason": self.reason,
            "llm_result": self.llm_result,
            "ip": self.ip,
            "mac": self.mac,
        }


@dataclass(frozen=True)
class UnlockRequestEvent:
    """학생이 차단 해제 인증을 요청한 이벤트."""
    block_reason: str
    student_note: str
    lock_duration_seconds: float | None = None
    timestamp: str = field(default_factory=_now_iso)

    type: ClassVar[str] = "UNLOCK_REQUEST"

    def to_dict(self) -> dict:
        """이벤트를 JSON 직렬화 가능한 dict로 변환한다."""
        return {
            "timestamp": self.timestamp,
            "type": self.type,
            "block_reason": self.block_reason,
            "student_note": self.student_note,
            "lock_duration_seconds": self.lock_duration_seconds,
        }


@dataclass(frozen=True)
class AllowEvent:
    """LLM이 ALLOW/UNSURE로 판단해 통과 처리된 이벤트."""
    window_title: str
    timestamp: str = field(default_factory=_now_iso)

    type: ClassVar[str] = "ALLOW"

    def to_dict(self) -> dict:
        """이벤트를 JSON 직렬화 가능한 dict로 변환한다."""
        return {
            "timestamp": self.timestamp,
            "type": self.type,
            "window_title": self.window_title,
        }


Event = BlockEvent | UnlockRequestEvent | AllowEvent


class EventSink(ABC):
    """이벤트 저장 백엔드 공통 인터페이스.

    현재는 LocalJSONLSink만 사용한다. Phase 2에서 RemoteDBSink/S3Sink가
    추가되더라도 EventLogger가 알아야 하는 표면적은 write(event, screenshot) 한
    곳뿐이다.

    screenshot은 BLOCK 이벤트 시점의 화면 캡처(BGR np.ndarray)이며, sink 구현체가
    별도 경로(S3 등)에 보존하거나 무시한다. 이벤트 dataclass 자체는 직렬화 가능한
    메타데이터만 담아 JSON/DB 양쪽에서 재사용된다.
    """

    @abstractmethod
    def write(self, event: Event, screenshot: Any = None) -> None:
        ...


class LocalJSONLSink(EventSink):
    """이벤트를 JSONL 파일에 한 줄씩 누적 저장한다.

    screenshot은 보존 비용(디스크 + 프라이버시)이 커서 무시한다. Phase 2에서
    RemoteSink/S3Sink가 추가되면 그쪽에서 binary 보존을 담당한다.

    쓰기 오류는 로깅만 하고 예외를 전파하지 않는다 — 로거 오류가 메인 모니터링
    루프를 중단시키면 안 되기 때문이다.
    """

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: Event, screenshot: Any = None) -> None:
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"로그 저장 오류: {e}")


class EventLogger:
    """
    이벤트 종류별 헬퍼를 제공하는 얇은 facade.

    실제 저장은 주입된 sink가 담당한다. sink를 생략하면 LocalJSONLSink가
    기본값으로 사용되어 기존 동작과 동일하게 동작한다.

    잠금 세션 추적:
        log_block 호출 시점에 _block_start_time을 설정하고, log_unlock_request
        호출 시 잠금 지속 시간(lock_duration_seconds)을 계산해 이벤트에 포함한다.
        WINDOW_CLOSE/PROCESS_KILL은 같은 잠금 세션의 2차 이벤트이므로 시작 시각을
        덮어쓰지 않는다.

    디바이스 식별자(ip/mac):
        EventLogger 생성 시 한 번 측정하여 모든 BLOCK 이벤트에 첨부한다. Phase 2
        중앙 서버에서 학생 PC를 식별할 때 사용된다.
    """

    def __init__(self, sink: EventSink | None = None):
        if sink is None:
            sink = LocalJSONLSink(Config.LOG_DIR / "events.jsonl")
        self.sink = sink
        self._device_ip = self._get_ip()
        self._device_mac = self._get_mac()
        self._block_start_time: datetime | None = None

    @staticmethod
    def _get_ip() -> str:
        """실제 패킷 전송 없이 UDP 소켓 라우팅으로 LAN IP를 확인한다. 실패 시 'unknown'."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "unknown"

    @staticmethod
    def _get_mac() -> str:
        """현재 PC의 MAC 주소를 'xx:xx:xx:xx:xx:xx' 형식으로 반환한다. 실패 시 'unknown'."""
        try:
            mac_bytes = uuid.getnode().to_bytes(6, byteorder="big")
            return ":".join(f"{b:02x}" for b in mac_bytes)
        except Exception:
            return "unknown"

    def log_block(
        self,
        stage: str,
        reason: str,
        llm_result: str = "",
        screenshot: Any = None,
    ) -> None:
        """차단 이벤트를 기록한다.

        Args:
            stage: 탐지 단계 식별자.
                "TITLE_MATCH" | "URL_MATCH" | "KEYWORD_MATCH" |
                "WINDOW_CLOSE" | "PROCESS_KILL"
            reason: 차단 원인 설명.
            llm_result: LLM 판정 결과 ("BLOCK" | "ALLOW" | "UNSURE").
                규칙 기반 즉시 차단 시에는 "RULE_BASED"를 전달한다.
            screenshot: 차단 시점의 화면 캡처 (BGR np.ndarray). sink가 보존
                여부를 결정한다. LocalJSONLSink는 무시하고, Phase 2의
                RemoteSink/S3Sink는 binary로 보존한다.
        """
        # WINDOW_CLOSE/PROCESS_KILL은 같은 잠금 세션의 2차 이벤트이므로 시작 시각을 덮어쓰지 않는다.
        if self._block_start_time is None:
            self._block_start_time = datetime.now()

        self.sink.write(
            BlockEvent(
                stage=stage,
                reason=reason,
                llm_result=llm_result,
                ip=self._device_ip,
                mac=self._device_mac,
            ),
            screenshot=screenshot,
        )
        logger.info(f"[차단 이벤트] {stage} | {reason}")

    def log_unlock_request(self, block_reason: str, student_note: str) -> None:
        """차단 해제 요청 이벤트를 기록한다.

        Args:
            block_reason: 이번 해제 요청의 원인이 된 차단 사유 문자열.
            student_note: 해제 시 남기는 메모 (현재는 인증 결과 문자열을 전달).
        """
        duration: float | None = None
        if self._block_start_time is not None:
            duration = round((datetime.now() - self._block_start_time).total_seconds(), 1)
            self._block_start_time = None

        self.sink.write(UnlockRequestEvent(
            block_reason=block_reason,
            student_note=student_note,
            lock_duration_seconds=duration,
        ))
        logger.info(f"[해제 요청] {student_note or '사유 없음'} | 잠금 지속: {duration}초")

    def log_allow(self, window_title: str) -> None:
        """LLM이 ALLOW/UNSURE로 판단해 통과 처리된 이벤트를 기록한다."""
        self.sink.write(AllowEvent(window_title=window_title))
