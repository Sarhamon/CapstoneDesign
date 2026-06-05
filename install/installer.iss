#pragma codepage 65001
; installer.iss
; Inno Setup 설치 마법사 스크립트
; 전제: build.ps1 실행 후 dist\FocusGuard\ 디렉터리가 생성되어 있어야 함

#define AppName "FocusGuard"
#define AppVersion "1.0.0"
#define AppPublisher "CapstoneDesign"
#define AppExeName "FocusGuard.exe"
#define DistDir "..\dist\FocusGuard"

[Setup]
AppId={{A3F2C1D4-8B5E-4F9A-B2C7-1D3E5F6A7B8C}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
OutputDir=..\dist
OutputBaseFilename=FocusGuard_Setup_{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
PrivilegesRequired=admin
WizardStyle=modern
; 설치 후 자동 실행
CloseApplications=yes

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\{#AppName} 제거"; Filename: "{uninstallexe}"

[Registry]
; 시작 시 자동 실행 강제 등록 — Watchdog이 FocusGuard를 시작·감시 (제거 시 자동 삭제)
Root: HKLM; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueName: "{#AppName}"; \
  ValueData: """{app}\FocusGuardWatchdog.exe"""; \
  Flags: uninsdeletevalue

[Run]
Filename: "{app}\FocusGuardWatchdog.exe"; Description: "FocusGuard 시작"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "taskkill"; Parameters: "/F /IM {#AppExeName}"; Flags: runhidden; RunOnceId: "KillFocusGuard"
