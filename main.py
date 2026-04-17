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

    def _get_target_info(self) -> tuple[int | None, int | None]:
        """현재 활성화된 최상단 창의 HWND와 PID를 반환합니다."""
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if not hwnd:
                return None, None

            pid = ctypes.c_ulong()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            return hwnd, pid.value
        except Exception as e:
            logger.error(f"타겟 정보 획득 실패: {e}")
            return None, None

    # _on_detect 메서드 시그니처 수정
    def _on_detect(self, stage: str, reason: str, screenshot: np.ndarray, target_hwnd: int | None, target_pid: int | None):
        """
        monitor.py에서 확정 지은 HWND와 PID를 전달받아 처리
        """
        if self._is_whitelisted(reason):
            logger.info(f"화이트리스트 통과: {reason}")
            return

        if self.overlay.is_active:
            return

        # 이제 main.py에서 PID를 캡처하지 않고, 인자로 받은 값을 그대로 넘김
        threading.Thread(
            target=self._llm_verify,
            args=(stage, reason, screenshot, target_hwnd, target_pid),
            daemon=True,
        ).start()

    def _llm_verify(self, stage: str, reason: str, screenshot: np.ndarray, target_hwnd: int | None, target_pid: int | None):
        with self._llm_lock:
            if self.overlay.is_active:
                return

            logger.info(f"LLM 검증 시작: {stage} | {reason}")

            llm_result = self.llm.analyze(window_title=reason, url_text="", ocr_text=reason)

            if llm_result == "BLOCK":
                self.event_logger.log_block(stage, reason, llm_result)
                
                # HWND와 PID를 함께 넘겨 스마트 종료 실행
                self._smart_kill_target(target_hwnd, target_pid)
                
                self.overlay.show(reason)

            elif llm_result == "UNSURE":
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

    def _smart_kill_target(self, hwnd: int | None, pid: int | None):
        """프로세스 특성에 따라 부드러운 창 닫기 또는 강제 종료를 선택적으로 수행"""
        if not hwnd or not pid:
            logger.warning("종료할 대상 정보가 부족합니다.")
            return

        try:
            import win32gui
            import win32con
            proc = psutil.Process(pid)
            proc_name = proc.name().lower()

            if "python" in proc_name:
                logger.warning(f"Python 프로세스 종료 차단 방어 성공: {proc_name}")
                return

            # 주요 브라우저 목록
            browser_list = ["chrome.exe", "msedge.exe", "whale.exe", "firefox.exe"]
            
            if any(b in proc_name for b in browser_list):
                # 브라우저: 프로세스 트리 강제 종료 대신, 해당 창에 'X' 버튼을 누른 것과 같은 효과 전송
                logger.info(f"[브라우저 창 닫기] {proc_name} (HWND: {hwnd})")
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                self.event_logger.log_block("WINDOW_CLOSE", f"{proc_name} (HWND {hwnd})")
            else:
                # 게임 및 일반 프로그램: 가차 없이 PID 킬
                proc.terminate()
                logger.info(f"[프로세스 종료 성공] {proc_name} (PID {pid})")
                self.event_logger.log_block("PROCESS_KILL", f"{proc_name} (PID {pid})")

        except psutil.NoSuchProcess:
            logger.info("대상 프로세스가 이미 닫혔습니다.")
        except Exception as e:
            logger.error(f"종료 처리 중 오류: {e}")

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