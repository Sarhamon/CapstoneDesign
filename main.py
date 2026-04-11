"""
main.py
FocusGuard 메인 컨트롤러
실행: python main.py
"""

import os
import logging
import sys
import threading
import time
import numpy as np
import psutil

# logs 폴더를 로깅 설정보다 먼저 생성
os.makedirs("logs", exist_ok=True)

from config import Config
from monitor import ScreenMonitor
from llm_client import get_llm_client, LocalLLMClient
from overlay import BlockOverlay
from event_logger import EventLogger

# ──────────────────────────────────────────────────────────────
# 로깅 설정
# ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/focus_guard.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("main")


# ──────────────────────────────────────────────────────────────
# FocusGuard 컨트롤러
# ──────────────────────────────────────────────────────────────

class FocusGuard:
    def __init__(self):
        self.event_logger = EventLogger()
        self.llm = get_llm_client()
        self.overlay = BlockOverlay(on_unlock_callback=self._on_unlock)
        self.monitor = ScreenMonitor(on_detect_callback=self._on_detect)

        # 화이트리스트 통과 후 LLM 판단 대기 상태 관리
        self._pending_llm: dict | None = None
        self._llm_lock = threading.Lock()

    # ──────────────────────────────────────────
    # 시작 / 종료
    # ──────────────────────────────────────────

    def run(self):
        logger.info("=" * 50)
        logger.info("FocusGuard 시작")
        logger.info(f"모드: {'클라우드' if Config.USE_CLOUD_LLM else '로컬'} LLM")
        logger.info(f"모델: {Config.OLLAMA_MODEL}")
        logger.info("=" * 50)

        # Ollama 워밍업 (로컬 모드일 때만)
        if not Config.USE_CLOUD_LLM and isinstance(self.llm, LocalLLMClient):
            self.llm.warmup()

        # 모니터링 시작
        self.monitor.start()

        try:
            # 메인 스레드 유지
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("종료 요청 (Ctrl+C)")
            self.monitor.stop()
            self.overlay.hide()

    # ──────────────────────────────────────────
    # 탐지 콜백 (ScreenMonitor → 여기로)
    # ──────────────────────────────────────────

    def _on_detect(self, stage: str, reason: str, screenshot: np.ndarray):
        """
        1~2단계 탐지 결과 수신
        화이트리스트 확인 후 → LLM 최종 판단
        """
        # 화이트리스트 확인
        if self._is_whitelisted(reason):
            logger.info(f"화이트리스트 통과: {reason}")
            return

        # 이미 차단 중이면 중복 처리 방지
        if self.overlay.is_active:
            return

        # 1·2단계 규칙에서 잡힌 경우 → LLM 최종 확인 (비동기)
        threading.Thread(
            target=self._llm_verify,
            args=(stage, reason, screenshot),
            daemon=True,
        ).start()

    def _llm_verify(self, stage: str, reason: str, screenshot: np.ndarray):
        """LLM 최종 판단 (별도 스레드에서 실행)"""
        with self._llm_lock:
            if self.overlay.is_active:
                return

            logger.info(f"LLM 검증 시작: {stage} | {reason}")

            # OCR 텍스트는 monitor 내부에서 이미 추출됨
            # 여기서는 stage/reason 정보만 LLM에 전달 (추가 OCR 생략)
            llm_result = self.llm.analyze(
                window_title=reason,
                url_text="",
                ocr_text=reason,    # 이미 추출된 reason 텍스트 재사용
            )

            logger.info(f"LLM 판정: {llm_result}")

            if llm_result == "BLOCK":
                self.event_logger.log_block(stage, reason, llm_result)
                self._kill_active_window()
                self.overlay.show(reason)

            elif llm_result == "UNSURE":
                # UNSURE는 일단 로그만 남기고 통과
                # 정책에 따라 BLOCK으로 강화할 수 있음
                logger.warning(f"LLM UNSURE → 통과 처리: {reason}")
                self.event_logger.log_allow(reason)

            else:
                self.event_logger.log_allow(reason)

    # ──────────────────────────────────────────
    # 해제 요청 콜백 (BlockOverlay → 여기로)
    # ──────────────────────────────────────────

    def _on_unlock(self, block_reason: str):
        """
        코드 인증 성공 시 호출
        현재: 로컬 로그 저장
        추후: 클라우드 서버에 해제 이벤트 전송
        """
        self.event_logger.log_unlock_request(block_reason, "코드 인증 성공")
        logger.info(f"[차단 해제] {block_reason}")

    # ──────────────────────────────────────────
    # 프로세스 강제 종료
    # ──────────────────────────────────────────

    def _kill_active_window(self):
        """차단 판정 시 현재 활성 창의 프로세스를 종료"""
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if not hwnd:
                logger.warning("활성 창 핸들을 찾을 수 없음")
                return

            pid = ctypes.c_ulong()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            pid = pid.value

            if pid == 0:
                logger.warning("PID 획득 실패")
                return

            proc = psutil.Process(pid)
            proc_name = proc.name()

            # FocusGuard 자신은 절대 종료하지 않음
            if "python" in proc_name.lower():
                logger.warning(f"Python 프로세스 종료 차단: {proc_name} (PID {pid})")
                return

            proc.terminate()
            logger.info(f"[프로세스 종료] {proc_name} (PID {pid})")
            self.event_logger.log_block("PROCESS_KILL", f"{proc_name} (PID {pid})")

        except psutil.NoSuchProcess:
            logger.warning("종료 대상 프로세스가 이미 없음")
        except psutil.AccessDenied:
            logger.error("프로세스 종료 권한 없음 — 관리자 권한으로 실행 필요")
        except Exception as e:
            logger.error(f"프로세스 종료 오류: {e}")

    # ──────────────────────────────────────────
    # 화이트리스트 확인
    # ──────────────────────────────────────────

    def _is_whitelisted(self, text: str) -> bool:
        text_lower = text.lower()
        return any(wl.lower() in text_lower for wl in Config.URL_WHITELIST)


# ──────────────────────────────────────────────────────────────
# Entry
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    FocusGuard().run()