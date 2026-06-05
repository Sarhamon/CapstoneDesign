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
        win32security.SetSecurityInfo(  # type: ignore[arg-type]
            handle, win32security.SE_KERNEL_OBJECT,
            win32security.DACL_SECURITY_INFORMATION,
            None, None, dacl, None,
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


if __name__ == "__main__":
    _protect_self()
    logger.info("감시 시작")
    if not _is_running():
        _start()
    while True:
        time.sleep(5)
        if not _is_running():
            logger.info("FocusGuard 종료 감지 → 재시작")
            time.sleep(2)
            _start()
