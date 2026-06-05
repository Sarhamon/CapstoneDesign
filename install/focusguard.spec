# focusguard.spec
# PyInstaller 빌드 설정
# 실행: pyinstaller install/focusguard.spec (프로젝트 루트에서)

from pathlib import Path

block_cipher = None
ROOT = Path(SPECPATH).parent  # install/ 의 상위 = 프로젝트 루트

# ── FocusGuard 메인 앱 ────────────────────────────────────────────────────────
a = Analysis(
    [str(ROOT / 'src' / 'main.py')],
    pathex=[str(ROOT / 'src')],
    binaries=[],
    datas=[
        (str(ROOT / 'data'), 'data'),
    ],
    hiddenimports=[
        'easyocr',
        'easyocr.easyocr',
        'easyocr.recognition',
        'easyocr.detection',
        'easyocr.utils',
        'PIL._tkinter_finder',
        'scipy.special._ufuncs_cxx',
        'scipy._lib.messagestream',
        'win32api',
        'win32con',
        'win32gui',
        'win32security',
        'pywintypes',
        'pkg_resources.py2_warn',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'jupyter', 'IPython'],
    cipher=block_cipher,
    noarchive=False,
)

# ── Watchdog ──────────────────────────────────────────────────────────────────
b = Analysis(
    [str(ROOT / 'src' / 'watchdog.py')],
    pathex=[str(ROOT / 'src')],
    binaries=[],
    datas=[],
    hiddenimports=[
        'win32api',
        'win32con',
        'win32security',
        'pywintypes',
        'psutil',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'easyocr', 'torch', 'torchvision', 'PIL', 'cv2',
        'numpy', 'scipy', 'matplotlib', 'jupyter', 'IPython', 'tkinter',
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
pyz_w = PYZ(b.pure, b.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FocusGuard',
    debug=False,
    strip=False,
    upx=True,
    console=False,
    uac_admin=True,
)

exe_w = EXE(
    pyz_w,
    b.scripts,
    [],
    exclude_binaries=True,
    name='FocusGuardWatchdog',
    debug=False,
    strip=False,
    upx=True,
    console=False,
    uac_admin=True,
)

coll = COLLECT(
    exe,
    exe_w,
    a.binaries,   # FocusGuard의 전체 바이너리
    a.zipfiles,
    a.datas,
    # b.binaries / b.zipfiles 는 a 의 부분집합이므로 생략 — 중복 DLL 방지
    # (b.excludes 에 torch/easyocr/cv2/numpy 등 heavy deps 가 명시됐고,
    #  나머지 win32api/psutil 등은 a.binaries 에 이미 포함됨)
    # b.datas 는 Analysis 에서 datas=[] 로 지정되어 원래 비어 있음
    strip=False,
    upx=True,
    upx_exclude=[],
    name='FocusGuard',
)
