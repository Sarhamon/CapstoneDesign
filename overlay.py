"""
overlay.py
차단 오버레이 UI
- 화면 전체를 덮는 반투명 차단 레이어
- 차단 사유 표시
- 해제 요청 버튼 (현재: 로컬 로그 / 추후: 클라우드 알림 전송)
"""

import tkinter as tk
from tkinter import messagebox
import threading
import logging
from datetime import datetime
from config import Config

logger = logging.getLogger(__name__)


class BlockOverlay:
    def __init__(self, on_request_callback=None):
        """
        on_request_callback: 해제 요청 버튼 클릭 시 호출
            signature: (reason: str, student_note: str)
        """
        self.on_request = on_request_callback
        self.root = None
        self._active = False
        self._reason = ""
        self._lock = threading.Lock()

    # ──────────────────────────────────────────
    # Public
    # ──────────────────────────────────────────

    def show(self, reason: str):
        with self._lock:
            if self._active:
                return
            self._active = True
            self._reason = reason

        # Tk는 메인 스레드에서만 실행 가능
        threading.Thread(target=self._run_ui, daemon=True).start()

    def hide(self):
        with self._lock:
            self._active = False
        if self.root:
            try:
                self.root.after(0, self.root.destroy)
            except Exception:
                pass
            self.root = None

    @property
    def is_active(self):
        return self._active

    # ──────────────────────────────────────────
    # UI
    # ──────────────────────────────────────────

    def _run_ui(self):
        self.root = tk.Tk()
        root = self.root

        # ── 창 설정 ──
        root.title("FocusGuard")
        root.attributes("-fullscreen", True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.93)
        root.configure(bg="#1a1a2e")
        root.protocol("WM_DELETE_WINDOW", lambda: None)  # 닫기 버튼 비활성화

        # ── 레이아웃 ──
        frame = tk.Frame(root, bg="#1a1a2e")
        frame.place(relx=0.5, rely=0.5, anchor="center")

        # 아이콘 라벨
        tk.Label(
            frame,
            text="🚫",
            font=("Arial", 64),
            bg="#1a1a2e",
        ).pack(pady=(0, 10))

        # 제목
        tk.Label(
            frame,
            text="수업에 방해되는 화면이 감지되었습니다",
            font=("맑은 고딕", 22, "bold"),
            fg="#e94560",
            bg="#1a1a2e",
        ).pack(pady=(0, 8))

        # 탐지 사유
        reason_short = self._reason[:80] + "..." if len(self._reason) > 80 else self._reason
        tk.Label(
            frame,
            text=f"사유: {reason_short}",
            font=("맑은 고딕", 13),
            fg="#a8a8b3",
            bg="#1a1a2e",
            wraplength=700,
        ).pack(pady=(0, 30))

        # 구분선
        tk.Frame(frame, bg="#e94560", height=2, width=500).pack(pady=(0, 30))

        # 안내 텍스트
        tk.Label(
            frame,
            text="수업과 관련된 내용이라면 아래 버튼으로 해제를 요청하세요.",
            font=("맑은 고딕", 12),
            fg="#c0c0c0",
            bg="#1a1a2e",
        ).pack(pady=(0, 16))

        # 사유 입력창
        tk.Label(
            frame,
            text="요청 사유 (선택)",
            font=("맑은 고딕", 11),
            fg="#a8a8b3",
            bg="#1a1a2e",
        ).pack()

        note_entry = tk.Entry(
            frame,
            font=("맑은 고딕", 12),
            width=45,
            bg="#16213e",
            fg="#ffffff",
            insertbackground="white",
            relief="flat",
            bd=8,
        )
        note_entry.pack(pady=(4, 20))

        # 버튼 영역
        btn_frame = tk.Frame(frame, bg="#1a1a2e")
        btn_frame.pack()

        # 해제 요청 버튼
        tk.Button(
            btn_frame,
            text="📩  교수자에게 해제 요청",
            font=("맑은 고딕", 13, "bold"),
            bg="#0f3460",
            fg="#ffffff",
            activebackground="#1a5276",
            relief="flat",
            padx=24,
            pady=12,
            cursor="hand2",
            command=lambda: self._request_unlock(note_entry.get()),
        ).pack(side="left", padx=10)

        # 시간 표시
        self._time_label = tk.Label(
            frame,
            text="",
            font=("맑은 고딕", 11),
            fg="#555577",
            bg="#1a1a2e",
        )
        self._time_label.pack(pady=(20, 0))
        self._update_time()

        root.mainloop()

    def _update_time(self):
        if self.root:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._time_label.config(text=f"차단 시각: {now}")
            self.root.after(1000, self._update_time)

    def _request_unlock(self, note: str):
        logger.info(f"[해제 요청] 사유: {note or '없음'} | 차단 원인: {self._reason}")

        # 요청 콜백 실행 (추후 클라우드 알림으로 연결)
        if self.on_request:
            self.on_request(self._reason, note)

        messagebox.showinfo(
            "요청 완료",
            "교수자에게 해제 요청이 전송되었습니다.\n승인 시 자동으로 해제됩니다.",
            parent=self.root,
        )
