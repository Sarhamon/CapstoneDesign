"""
모든 모듈이 import 가능한지 검증하는 smoke 테스트.

각 모듈을 별도 서브프로세스에서 import한다. 이유:
    1. monitor.py / overlay.py가 module-level에서 ctypes.windll.user32 같은
       Windows-only 부수효과를 실행하므로, 한 번 로드된 상태가 다른 테스트로 누수되면
       원인 파악이 어렵다.
    2. src/ 와 anno/ 는 동일 모듈명을 사용하므로 한 프로세스에서 공존할 수 없다.
       cwd를 분리해 sys.path[0]를 각각 잡는다.

실행:
    pytest 기반: pytest tests/
    독립 실행:    python tests/test_imports.py
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULES = [
    "config",
    "event_logger",
    "llm_client",
    "web_auth",
    "monitor",
    "overlay",
    "main",
]


def _smoke(directory: Path, module: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=directory,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"{directory.name}/{module} import 실패:\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )


# pytest가 설치돼 있을 때만 parametrize 테스트를 수집한다.
# 설치 전에도 `python tests/test_imports.py`로 standalone 검증이 가능해야 하므로
# pytest를 hard dependency로 두지 않는다.
try:
    import pytest

    @pytest.mark.parametrize("module", MODULES)
    def test_src_module_imports(module: str) -> None:
        _smoke(REPO_ROOT / "src", module)
except ImportError:
    pass


if __name__ == "__main__":
    failures: list[tuple[str, str, str]] = []
    for module in MODULES:
        try:
            _smoke(REPO_ROOT / "src", module)
            print(f"OK   src/{module}")
        except AssertionError as e:
            print(f"FAIL src/{module}")
            failures.append(("src", module, str(e)))
    if failures:
        print(f"\n{len(failures)} failure(s):")
        for d, m, msg in failures:
            print(f"\n[{d}/{m}]\n{msg}")
        sys.exit(1)
    print("\nAll imports OK")
