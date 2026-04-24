"""
main.py
FocusGuard 메인 컨트롤러
실행: python main.py

[수정] Tcl_AsyncDelete 오류 해결
  tkinter(Tcl/Tk)는 생성한 스레드에서만 안전하게 실행됩니다.
  메인 스레드에서 tk.Tk()를 생성하고 root.mainloop()를 돌립니다.
  모니터링·LLM 등 블로킹 작업은 모두 daemon 스레드로 분리합니다.
  UI 조작이 필요한 경우 root.after(0, fn)으로만 메인 스레드에 위임합니다.
"""

import os
import logging
import sys
import signal
import threading
import time
import numpy as np
import psutil
import tkinter as tk

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
    def __init__(self, root: tk.Tk):
        """
        Parameters
        ----------
        root : tk.Tk
            메인 스레드에서 생성된 Tk 루트 윈도우.
            BlockOverlay가 이 root를 통해 UI를 안전하게 조작합니다.
        """
        self.root = root

        self.event_logger = EventLogger()
        self.llm = get_llm_client()
        # root를 주입해 overlay가 직접 스레드를 띄우지 않게 합니다.
        self.overlay = BlockOverlay(root=root, on_unlock_callback=self._on_unlock)
        self.monitor = ScreenMonitor(on_detect_callback=self._on_detect)

        self._llm_lock = threading.Lock()

    # ──────────────────────────────────────────
    # 시작
    # ──────────────────────────────────────────

    def start_background(self):
        """모니터링·LLM 워밍업을 백그라운드 스레드에서 시작합니다."""
        threading.Thread(target=self._background_init, daemon=True).start()

    def _background_init(self):
        logger.info("=" * 50)
        logger.info("FocusGuard 시작")
        logger.info(f"모드: {'클라우드' if Config.USE_CLOUD_LLM else '로컬'} LLM")
        logger.info(f"모델: {Config.OLLAMA_MODEL}")
        logger.info("=" * 50)

        if not Config.USE_CLOUD_LLM and isinstance(self.llm, LocalLLMClient):
            self.llm.warmup()

        self.monitor.start()

    # ──────────────────────────────────────────
    # 탐지 콜백 (ScreenMonitor → 여기로)
    # ──────────────────────────────────────────

    def _on_detect(
        self,
        stage: str,
        reason: str,
        screenshot: np.ndarray,
        target_hwnd: int | None,
        target_pid: int | None,
    ):
        if self._is_whitelisted(reason):
            logger.info(f"화이트리스트 통과: {reason}")
            return

        if self.overlay.is_active:
            return

        threading.Thread(
            target=self._llm_verify,
            args=(stage, reason, screenshot, target_hwnd, target_pid),
            daemon=True,
        ).start()

    def _llm_verify(
        self,
        stage: str,
        reason: str,
        screenshot: np.ndarray,
        target_hwnd: int | None,
        target_pid: int | None,
    ):
        with self._llm_lock:
            if self.overlay.is_active:
                return

            logger.info(f"LLM 검증 시작: {stage} | {reason}")
            llm_result = self.llm.analyze(window_title=reason, url_text="", ocr_text=reason)

            if llm_result == "BLOCK":
                self.event_logger.log_block(stage, reason, llm_result)
                self._smart_kill_target(target_hwnd, target_pid)
                # UI 조작 → 반드시 root.after()로 메인 스레드에 위임
                self.root.after(0, lambda: self.overlay.show(reason))

            elif llm_result == "UNSURE":
                logger.warning(f"LLM UNSURE → 통과 처리: {reason}")
                self.event_logger.log_allow(reason)

            else:
                self.event_logger.log_allow(reason)

    # ──────────────────────────────────────────
    # 해제 요청 콜백 (BlockOverlay → 여기로)
    # ──────────────────────────────────────────

    def _on_unlock(self, block_reason: str):
        self.event_logger.log_unlock_request(block_reason, "코드 인증 성공")
        logger.info(f"[차단 해제] {block_reason}")

    # ──────────────────────────────────────────
    # 프로세스 강제 종료
    # ──────────────────────────────────────────

    def _smart_kill_target(self, hwnd: int | None, pid: int | None):
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

            browser_list = ["chrome.exe", "msedge.exe", "whale.exe", "firefox.exe"]

            if any(b in proc_name for b in browser_list):
                logger.info(f"[브라우저 창 닫기] {proc_name} (HWND: {hwnd})")
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                self.event_logger.log_block("WINDOW_CLOSE", f"{proc_name} (HWND {hwnd})")
            else:
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
    # ❶ 메인 스레드에서 tk.Tk() 생성 — 이 스레드가 Tcl 인터프리터를 소유합니다.
    root = tk.Tk()
    # withdraw()는 BlockOverlay._setup_root()에서 처리합니다.

    # ❷ FocusGuard 초기화 (root 주입)
    guard = FocusGuard(root)

    # ❸ 모니터링·LLM은 백그라운드 스레드에서 실행
    guard.start_background()

    # ❹ Ctrl+C(SIGINT) → signal 핸들러에서 메인 스레드에 안전하게 종료 요청
    #    tkinter mainloop는 KeyboardInterrupt를 직접 받지 못하므로
    #    signal + root.after()로 우회합니다.
    def _on_sigint(signum, frame):
        logger.info("종료 요청 (Ctrl+C)")
        guard.monitor.stop()
        root.after(0, root.destroy)

    signal.signal(signal.SIGINT, _on_sigint)

    # ❺ mainloop가 SIGINT를 묻어버리지 않도록 200ms마다 Python에 제어권 반환
    def _keep_alive():
        root.after(200, _keep_alive)

    root.after(200, _keep_alive)

    # ❻ 메인 스레드 이벤트 루프
    root.mainloop()