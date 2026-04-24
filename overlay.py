"""
overlay.py
차단 오버레이 UI

[구조]
  root(tk.Tk) 자체를 오버레이 창으로 사용합니다.
  - 평소: root.withdraw()로 숨김
  - 차단 시: root를 전체화면으로 펼침
  - 해제 시: 다시 withdraw()로 숨김

  Toplevel을 쓰면 withdraw()된 root 기준으로 크기가 잡혀
  전체화면을 못 덮는 문제가 있으므로 root를 직접 사용합니다.
  모든 UI 조작은 root.after()를 통해 메인 스레드에서만 실행합니다.
"""

import tkinter as tk
import threading
import logging
from datetime import datetime
from config import Config

logger = logging.getLogger(__name__)


class BlockOverlay:
    def __init__(self, root: tk.Tk, on_unlock_callback=None):
        self.root = root
        self.on_unlock = on_unlock_callback

        self._active = False
        self._reason = ""
        self._lock = threading.Lock()
        self._time_label: tk.Label | None = None
        self._content_frame: tk.Frame | None = None

        # root를 오버레이 전용으로 미리 설정
        self._setup_root()

    # ──────────────────────────────────────────
    # 초기 root 설정 (메인 스레드, __init__ 시)
    # ──────────────────────────────────────────

    def _setup_root(self):
        """root를 오버레이 창 전용으로 설정합니다. 평소엔 숨깁니다."""
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{sw}x{sh}+0+0")
        self.root.configure(bg="#1a1a2e")
        self.root.overrideredirect(True)          # 타이틀바 제거
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.93)
        self.root.protocol("WM_DELETE_WINDOW", lambda: None)
        self.root.withdraw()                      # 처음엔 숨김

    # ──────────────────────────────────────────
    # Public API (모든 스레드에서 호출 가능)
    # ──────────────────────────────────────────

    def show(self, reason: str):
        with self._lock:
            if self._active:
                return
            self._active = True
            self._reason = reason
        self.root.after(0, self._show_ui)

    def hide(self):
        with self._lock:
            self._active = False
        self.root.after(0, self._hide_ui)

    @property
    def is_active(self) -> bool:
        return self._active

    # ──────────────────────────────────────────
    # UI 표시 / 숨김 (메인 스레드에서만 실행)
    # ──────────────────────────────────────────

    def _show_ui(self):
        # 기존 콘텐츠 제거
        if self._content_frame:
            self._content_frame.destroy()
            self._content_frame = None

        # root를 전체화면으로 표시
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self.root.grab_set()

        # 콘텐츠 빌드
        self._content_frame = tk.Frame(self.root, bg="#1a1a2e")
        self._content_frame.place(relx=0.5, rely=0.5, anchor="center")

        frame = self._content_frame

        tk.Label(frame, text="🚫", font=("Arial", 64), bg="#1a1a2e").pack(pady=(0, 10))

        tk.Label(
            frame,
            text="수업에 방해되는 화면이 감지되었습니다",
            font=("맑은 고딕", 22, "bold"),
            fg="#e94560", bg="#1a1a2e",
        ).pack(pady=(0, 8))

        reason_short = self._reason[:80] + "..." if len(self._reason) > 80 else self._reason
        tk.Label(
            frame,
            text=f"사유: {reason_short}",
            font=("맑은 고딕", 13),
            fg="#a8a8b3", bg="#1a1a2e",
            wraplength=700,
        ).pack(pady=(0, 30))

        tk.Frame(frame, bg="#e94560", height=2, width=500).pack(pady=(0, 30))

        tk.Label(
            frame,
            text="교수자로부터 해제 코드를 받아 입력하세요.",
            font=("맑은 고딕", 12),
            fg="#c0c0c0", bg="#1a1a2e",
        ).pack(pady=(0, 16))

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

        self._time_label = tk.Label(
            frame, text="",
            font=("맑은 고딕", 11),
            fg="#555577", bg="#1a1a2e",
        )
        self._time_label.pack(pady=(24, 0))
        self._tick_time()

    def _hide_ui(self):
        try:
            self.root.grab_release()
        except Exception:
            pass
        if self._content_frame:
            self._content_frame.destroy()
            self._content_frame = None
        self.root.withdraw()

    def _tick_time(self):
        if self._content_frame and self._time_label:
            try:
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self._time_label.config(text=f"차단 시각: {now}")
                self.root.after(1000, self._tick_time)
            except tk.TclError:
                pass

    # ──────────────────────────────────────────
    # 해제 코드 입력 팝업
    # ──────────────────────────────────────────

    def _open_code_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("해제 코드 입력")
        dialog.attributes("-topmost", True)
        dialog.resizable(False, False)
        dialog.configure(bg="#16213e")

        w, h = 420, 260
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        dialog.geometry(f"{w}x{h}+{(sw - w)//2}+{(sh - h)//2}")
        dialog.grab_set()

        frame = tk.Frame(dialog, bg="#16213e", padx=30, pady=24)
        frame.pack(fill="both", expand=True)

        tk.Label(
            frame,
            text="🔑  해제 코드를 입력하세요",
            font=("맑은 고딕", 14, "bold"),
            fg="#ffffff", bg="#16213e",
        ).pack(pady=(0, 20))

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
            show="●",
        )
        code_entry.pack(pady=(0, 8))
        code_entry.focus_set()

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

        code_entry.bind("<Return>", lambda e: attempt_unlock())
        dialog.protocol("WM_DELETE_WINDOW", lambda: None)