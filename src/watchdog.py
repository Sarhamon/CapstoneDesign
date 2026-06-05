"""
watchdog.py
FocusGuard 감시 프로세스
- FocusGuard.exe를 시작하고, 종료되면 재시작한다.
- 자기 자신에도 DACL 보호를 적용하여 작업 관리자에서 종료를 막는다.
"""

import logging
import subprocess
import sys
import time
from pathlib import Path

if sys.stdout is None:
    # console=False 빌드: stdout/stderr 모두 None이므로 NullHandler로 대체
    logging.getLogger().addHandler(logging.NullHandler())
else:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] watchdog: %(message)s",
    )
logger = logging.getLogger("watchdog")

_EXE_DIR = Path(sys.executable).parent
_TARGET  = _EXE_DIR / "FocusGuard.exe"


def _protect_self() -> None:
    """DACL에서 PROCESS_TERMINATE 권한을 제거하여 작업 관리자 종료를 차단한다."""
    try:
        import win32api
        import win32security
        PROCESS_TERMINATE = 0x0001
        PROCESS_ALL_ACCESS = 0x1F0FFF
        handle = win32api.GetCurrentProcess()
        dacl = win32security.ACL()
        system_sid = win32security.CreateWellKnownSid(win32security.WinLocalSystemSid, None)
        dacl.AddAccessAllowedAce(win32security.ACL_REVISION, PROCESS_ALL_ACCESS, system_sid)
        everyone_sid = win32security.CreateWellKnownSid(win32security.WinWorldSid, None)
        dacl.AddAccessDeniedAce(win32security.ACL_REVISION, PROCESS_TERMINATE, everyone_sid)
        win32security.SetSecurityInfo(
            handle, win32security.SE_KERNEL_OBJECT,
            win32security.DACL_SECURITY_INFORMATION,
            None, None, dacl, None,  # type: ignore[reportArgumentType]
        )
        logger.info("DACL 보호 완료")
    except Exception as e:
        logger.warning(f"DACL 보호 실패: {e}")


def _is_running() -> bool:
    try:
        import psutil
        return any(
            p.name().lower() == "focusguard.exe"
            for p in psutil.process_iter(["name"])
        )
    except Exception:
        return False


def _start() -> None:
    if not _TARGET.exists():
        logger.error(f"FocusGuard.exe 없음: {_TARGET}")
        return
    subprocess.Popen([str(_TARGET)])
    logger.info("FocusGuard 시작")


_BACKOFF_BASE = 2   # 최초 재시작 대기 (초)
_BACKOFF_MAX  = 60  # 최대 대기 상한
_STABLE_SECS  = 30  # 이 시간 이상 실행됐으면 안정적 → 백오프 초기화


if __name__ == "__main__":
    _protect_self()
    logger.info("감시 시작")

    backoff = _BACKOFF_BASE
    last_start = time.monotonic()

    if not _is_running():
        _start()

    while True:
        time.sleep(2)
        if not _is_running():
            uptime = time.monotonic() - last_start
            if uptime >= _STABLE_SECS:
                # 안정적으로 실행되다 종료된 경우 → 백오프 초기화
                backoff = _BACKOFF_BASE
            extra_wait = backoff - 2  # 루프 상단 sleep(2)이미 소진
            if extra_wait > 0:
                logger.warning(
                    f"FocusGuard 조기 종료 ({uptime:.0f}초 실행) → {backoff}초 후 재시작"
                )
                time.sleep(extra_wait)
            else:
                logger.info("FocusGuard 종료 감지 → 재시작")
            _start()
            last_start = time.monotonic()
            backoff = min(backoff * 2, _BACKOFF_MAX)
