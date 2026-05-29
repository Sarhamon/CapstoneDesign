# build.ps1
# FocusGuard Windows 설치 파일 빌드 스크립트
# 실행: powershell -ExecutionPolicy Bypass -File install\build.ps1 (프로젝트 루트에서)
#
# 전제 조건:
#   pip install pyinstaller
#   Inno Setup 6 설치 (https://jrsoftware.org/isdl.php)

$ROOT = Split-Path $PSScriptRoot -Parent
$ISCC = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"

Set-Location $ROOT

Write-Host "=== 1단계: PyInstaller 빌드 ===" -ForegroundColor Cyan
pyinstaller install\focusguard.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) { Write-Host "PyInstaller 실패" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "=== 2단계: .env 복사 ===" -ForegroundColor Cyan
if (Test-Path "install\.env") {
    Copy-Item "install\.env" "dist\FocusGuard\.env"
    Write-Host ".env 복사 완료"
} else {
    Write-Host "오류: install\.env 파일 없음" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=== 3단계: Inno Setup 설치 마법사 생성 ===" -ForegroundColor Cyan
if (-not (Test-Path $ISCC)) {
    Write-Host "Inno Setup을 찾을 수 없습니다: $ISCC" -ForegroundColor Red
    Write-Host "https://jrsoftware.org/isdl.php 에서 설치 후 재실행하세요."
    exit 1
}
& $ISCC "install\installer.iss"
if ($LASTEXITCODE -ne 0) { Write-Host "Inno Setup 실패" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "=== 빌드 완료 ===" -ForegroundColor Green
Write-Host "설치 파일: dist\FocusGuard_Setup_1.0.0.exe"
