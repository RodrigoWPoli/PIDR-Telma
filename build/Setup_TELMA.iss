; Setup_TELMA.iss
; Inno Setup 6 installer script for TELMA Fault Detection Dashboard
; Run via build.bat or: ISCC.exe build\Setup_TELMA.iss

#define MyAppName      "TELMA Dashboard"
#define MyAppVersion   "1.0"
#define MyAppPublisher "CRAN — Université de Lorraine"
#define MyAppExe       "venv\Scripts\pythonw.exe"
#define MyAppScript    "app.py"

[Setup]
AppId={{4F7A2B1C-9E3D-4A8F-B5C6-D2E1F0A9B8C7}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\TELMA
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=Setup_TELMA
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
; Allow non-admin install to AppData\Local\Programs if user has no admin rights
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checked

[Files]
; Python source files
Source: "..\app.py";              DestDir: "{app}"; Flags: ignoreversion
Source: "..\dashboard.py";        DestDir: "{app}"; Flags: ignoreversion
Source: "..\update_ontology.py";  DestDir: "{app}"; Flags: ignoreversion
Source: "..\swrl_engine.py";      DestDir: "{app}"; Flags: ignoreversion
Source: "..\realtime_monitor.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\ontology_builder.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\data_collection.py";  DestDir: "{app}"; Flags: ignoreversion
Source: "..\requirements.txt";    DestDir: "{app}"; Flags: ignoreversion

; Ontology
Source: "..\ontology\*"; DestDir: "{app}\ontology"; Flags: ignoreversion recursesubdirs createallsubdirs

; Pre-built Python venv (created by build.ps1)
Source: "venv\*"; DestDir: "{app}\venv"; Flags: ignoreversion recursesubdirs createallsubdirs

; Portable MongoDB binaries (manually downloaded — see README_build.md)
Source: "mongodb\*"; DestDir: "{app}\mongodb"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Start menu
Name: "{group}\{#MyAppName}";
  Filename: "{app}\{#MyAppExe}";
  Parameters: """{app}\{#MyAppScript}""";
  WorkingDir: "{app}"

; Desktop shortcut (only if task selected)
Name: "{autodesktop}\{#MyAppName}";
  Filename: "{app}\{#MyAppExe}";
  Parameters: """{app}\{#MyAppScript}""";
  WorkingDir: "{app}";
  Tasks: desktopicon

[Run]
; Offer to launch immediately after install
Filename: "{app}\{#MyAppExe}";
  Parameters: """{app}\{#MyAppScript}""";
  WorkingDir: "{app}";
  Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}";
  Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Remove __pycache__ directories left by Python at runtime
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\ontology\__pycache__"
