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

[Tasks]
Name: "autostart"; Description: "Windows 시작 시 FocusGuard 자동 실행"; GroupDescription: "추가 옵션:"; Flags: checked

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\{#AppName} 제거"; Filename: "{uninstallexe}"

[Registry]
; 시작 시 자동 실행 등록 (Tasks: autostart 선택 시)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueName: "{#AppName}"; \
  ValueData: """{app}\{#AppExeName}"""; \
  Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#AppExeName}"; Description: "FocusGuard 시작"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "taskkill"; Parameters: "/F /IM {#AppExeName}"; Flags: runhidden
