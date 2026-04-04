"""
monitor.py
화면 캡처 + 창 타이틀 감지 + OCR 파이프라인
"""

import time
import threading
import mss
import numpy as np
import cv2
from PIL import Image
import pygetwindow as gw
from paddleocr import PaddleOCR
from config import Config
import logging

logger = logging.getLogger(__name__)


class ScreenMonitor:
    def __init__(self, on_detect_callback):
        """
        on_detect_callback: 탐지 시 호출할 함수
            signature: (reason: str, detail: str, screenshot: np.ndarray)
        """
        self.callback = on_detect_callback
        self.ocr = PaddleOCR(use_angle_cls=True, lang="korean", show_log=False)
        self.running = False
        self._thread = None
        self._last_window_title = ""

    # ──────────────────────────────────────────
    # Public
    # ──────────────────────────────────────────

    def start(self):
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("모니터링 시작")

    def stop(self):
        self.running = False
        logger.info("모니터링 중지")

    # ──────────────────────────────────────────
    # Core loop
    # ──────────────────────────────────────────

    def _loop(self):
        while self.running:
            try:
                self._check()
            except Exception as e:
                logger.error(f"모니터링 루프 오류: {e}")
            time.sleep(Config.POLL_INTERVAL)

    def _check(self):
        # 1단계: 창 타이틀 매칭
        title = self._get_active_window_title()
        if title and title != self._last_window_title:
            logger.debug(f"활성 창: {title}")
            self._last_window_title = title

        result = self._check_window_title(title)
        if result:
            screenshot = self._capture_screen()
            self.callback("TITLE_MATCH", result, screenshot)
            return

        # 2단계: OCR 분석
        screenshot = self._capture_screen()
        ocr_result = self._run_ocr(screenshot)
        url_text, body_text = self._split_zones(screenshot)

        result = self._check_url_keywords(url_text)
        if result:
            self.callback("URL_MATCH", result, screenshot)
            return

        result = self._check_content_keywords(body_text)
        if result:
            self.callback("KEYWORD_MATCH", result, screenshot)
            return

        logger.debug("탐지 없음 — 허용")

    # ──────────────────────────────────────────
    # 창 타이틀
    # ──────────────────────────────────────────

    def _get_active_window_title(self) -> str:
        try:
            wins = gw.getActiveWindow()
            return wins.title if wins else ""
        except Exception:
            return ""

    def _check_window_title(self, title: str):
        if not title:
            return None
        title_lower = title.lower()
        for keyword in Config.TITLE_BLACKLIST:
            if keyword.lower() in title_lower:
                return f"창 타이틀 감지: '{keyword}' in '{title}'"
        return None

    # ──────────────────────────────────────────
    # 화면 캡처
    # ──────────────────────────────────────────

    def _capture_screen(self) -> np.ndarray:
        with mss.mss() as sct:
            monitor = sct.monitors[1]  # 주 모니터
            raw = sct.grab(monitor)
            img = np.array(raw)
            return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

    # ──────────────────────────────────────────
    # OCR
    # ──────────────────────────────────────────

    def _split_zones(self, img: np.ndarray):
        """
        Zone A: 상단 URL 바 영역 (전체 높이의 상위 8%)
        Zone C: 나머지 본문 영역
        """
        h, w = img.shape[:2]
        url_zone = img[0: int(h * 0.08), :]
        body_zone = img[int(h * 0.08): int(h * 0.85), :]

        url_text = self._ocr_to_text(url_zone)
        body_text = self._ocr_to_text(body_zone)
        return url_text, body_text

    def _run_ocr(self, img: np.ndarray) -> str:
        return self._ocr_to_text(img)

    def _ocr_to_text(self, img: np.ndarray) -> str:
        try:
            result = self.ocr.ocr(img, cls=True)
            if not result or not result[0]:
                return ""
            lines = [
                line[1][0]
                for line in result[0]
                if line and line[1][1] > Config.OCR_CONFIDENCE_THRESHOLD
            ]
            return " ".join(lines)
        except Exception as e:
            logger.error(f"OCR 오류: {e}")
            return ""

    # ──────────────────────────────────────────
    # 키워드 매칭
    # ──────────────────────────────────────────

    def _check_url_keywords(self, url_text: str):
        if not url_text:
            return None
        url_lower = url_text.lower()
        for keyword in Config.URL_BLACKLIST:
            if keyword.lower() in url_lower:
                return f"URL 키워드 감지: '{keyword}'"
        return None

    def _check_content_keywords(self, body_text: str):
        if not body_text:
            return None
        matched = [kw for kw in Config.CONTENT_KEYWORDS if kw in body_text]
        if len(matched) >= Config.KEYWORD_THRESHOLD:
            return f"콘텐츠 키워드 감지: {matched}"
        return None