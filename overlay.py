"""
overlay.py
차단 오버레이 UI
- 화면 전체를 덮는 차단 레이어
- 해제 버튼 클릭 → 해제 코드 입력 팝업
- 코드 일치 시 차단 해제
"""

import tkinter as tk
from tkinter import messagebox
import threading
import logging
from datetime import datetime
from config import Config

logger = logging.getLogger(__name__)


class BlockOverlay:
    def __init__(self, on_unlock_callback=None):
        """
        on_unlock_callback: 코드 인증 성공 시 호출
            signature: (reason: str)
        """
        self.on_unlock = on_unlock_callback
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
    # 메인 오버레이 UI
    # ──────────────────────────────────────────

    def _run_ui(self):
        self.root = tk.Tk()
        root = self.root

        root.title("FocusGuard")
        root.attributes("-fullscreen", True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.93)
        root.configure(bg="#1a1a2e")
        root.protocol("WM_DELETE_WINDOW", lambda: None)

        frame = tk.Frame(root, bg="#1a1a2e")
        frame.place(relx=0.5, rely=0.5, anchor="center")

        # 아이콘
        tk.Label(
            frame, text="🚫",
            font=("Arial", 64), bg="#1a1a2e",
        ).pack(pady=(0, 10))

        # 제목
        tk.Label(
            frame,
            text="수업에 방해되는 화면이 감지되었습니다",
            font=("맑은 고딕", 22, "bold"),
            fg="#e94560", bg="#1a1a2e",
        ).pack(pady=(0, 8))

        # 탐지 사유
        reason_short = self._reason[:80] + "..." if len(self._reason) > 80 else self._reason
        tk.Label(
            frame,
            text=f"사유: {reason_short}",
            font=("맑은 고딕", 13),
            fg="#a8a8b3", bg="#1a1a2e",
            wraplength=700,
        ).pack(pady=(0, 30))

        # 구분선
        tk.Frame(frame, bg="#e94560", height=2, width=500).pack(pady=(0, 30))

        # 안내 텍스트
        tk.Label(
            frame,
            text="교수자로부터 해제 코드를 받아 입력하세요.",
            font=("맑은 고딕", 12),
            fg="#c0c0c0", bg="#1a1a2e",
        ).pack(pady=(0, 16))

        # 해제 요청 버튼
        tk.Button(
            frame,
            text="🔓  해제 코드 입력",
            font=("맑은 고딕", 13, "bold"),
            bg="#0f3460", fg="#ffffff",
            activebackground="#1a5276",
            relief="flat", padx=24, pady=12,
            cursor="hand2",
            command=self._open_code_dialog,
        ).pack()

        # 시간 표시
        self._time_label = tk.Label(
            frame, text="",
            font=("맑은 고딕", 11),
            fg="#555577", bg="#1a1a2e",
        )
        self._time_label.pack(pady=(24, 0))
        self._update_time()

        root.mainloop()

    def _update_time(self):
        if self.root:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._time_label.config(text=f"차단 시각: {now}")
            self.root.after(1000, self._update_time)

    # ──────────────────────────────────────────
    # 해제 코드 입력 팝업
    # ──────────────────────────────────────────

    def _open_code_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("해제 코드 입력")
        dialog.attributes("-topmost", True)
        dialog.resizable(False, False)
        dialog.configure(bg="#16213e")
        dialog.grab_set()  # 다른 창 조작 불가

        # 팝업 중앙 배치
        dialog.update_idletasks()
        w, h = 420, 260
        sw = dialog.winfo_screenwidth()
        sh = dialog.winfo_screenheight()
        dialog.geometry(f"{w}x{h}+{(sw - w)//2}+{(sh - h)//2}")

        frame = tk.Frame(dialog, bg="#16213e", padx=30, pady=24)
        frame.pack(fill="both", expand=True)

        tk.Label(
            frame,
            text="🔑  해제 코드를 입력하세요",
            font=("맑은 고딕", 14, "bold"),
            fg="#ffffff", bg="#16213e",
        ).pack(pady=(0, 20))

        # 코드 입력란 (입력 내용 숨김)
        code_var = tk.StringVar()
        code_entry = tk.Entry(
            frame,
            textvariable=code_var,
            font=("맑은 고딕", 18),
            width=16,
            bg="#0f3460", fg="#ffffff",
            insertbackground="white",
            relief="flat", bd=10,
            justify="center",
            show="●",  # 입력값 숨김
        )
        code_entry.pack(pady=(0, 8))
        code_entry.focus_set()

        # 오류 메시지 라벨 (초기엔 빈칸)
        error_label = tk.Label(
            frame, text="",
            font=("맑은 고딕", 11),
            fg="#e94560", bg="#16213e",
        )
        error_label.pack(pady=(0, 16))

        def attempt_unlock():
            code = code_var.get().strip()
            if code == Config.UNLOCK_CODE:
                logger.info(f"[해제 성공] 코드 인증 완료 | 차단 원인: {self._reason}")
                dialog.destroy()
                if self.on_unlock:
                    self.on_unlock(self._reason)
                self.hide()
            else:
                logger.warning(f"[해제 실패] 잘못된 코드 입력: '{code}'")
                error_label.config(text="코드가 올바르지 않습니다. 다시 확인하세요.")
                code_var.set("")
                code_entry.focus_set()

        # 확인 버튼
        tk.Button(
            frame,
            text="확인",
            font=("맑은 고딕", 12, "bold"),
            bg="#e94560", fg="#ffffff",
            activebackground="#c0392b",
            relief="flat", padx=20, pady=8,
            cursor="hand2",
            command=attempt_unlock,
        ).pack()

        # 엔터키 바인딩
        code_entry.bind("<Return>", lambda e: attempt_unlock())

        # 닫기 버튼 비활성화
        dialog.protocol("WM_DELETE_WINDOW", lambda: None)