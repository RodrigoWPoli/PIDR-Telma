; TELMA Dashboard — Inno Setup script
; Bundles the PyInstaller onedir output plus the MongoDB MSI and the
; Microsoft Edge WebView2 bootstrapper. Build with:
;     iscc installer\pidr.iss

#define MyAppName      "TELMA Dashboard"
#define MyAppPublisher "CRAN — Universite de Lorraine"
#define MyAppVersion   "1.0.0"
#define MyAppExeName   "telma-dashboard.exe"

[Setup]
AppId={{C6F0F0F8-2D4D-4D4F-9E2C-6B7F2E2E2E2E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\TELMA Dashboard
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist-installer
OutputBaseFilename=TELMA-Dashboard-Setup
Compression=lzma2/ultra
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayIcon={app}\app\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: checkedonce
Name: "installmongo"; Description: "Install MongoDB Community Server 8.0 (skip if already installed)"; GroupDescription: "Prerequisites:"; Flags: checkedonce
Name: "installwebview"; Description: "Install Microsoft Edge WebView2 runtime (skip if already installed)"; GroupDescription: "Prerequisites:"; Flags: unchecked

[Files]
; PyInstaller onedir output: ..\dist\pidr\* gets installed under {app}\app\
Source: "..\dist\telma\*"; DestDir: "{app}\app"; Flags: ignoreversion recursesubdirs createallsubdirs
; Redistributables shipped inside the installer.
Source: "redist\mongodb-windows-x86_64-8.0.4-signed.msi"; DestDir: "{tmp}"; Flags: deleteafterinstall; Tasks: installmongo
Source: "redist\MicrosoftEdgeWebView2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Tasks: installwebview

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\app\{#MyAppExeName}"; WorkingDir: "{app}\app"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\app\{#MyAppExeName}"; WorkingDir: "{app}\app"; Tasks: desktopicon

[Run]
Filename: "msiexec.exe"; \
    Parameters: "/i ""{tmp}\mongodb-windows-x86_64-8.0.4-signed.msi"" /quiet /norestart ADDLOCAL=ServerNoService,Client SHOULD_INSTALL_COMPASS=0"; \
    StatusMsg: "Installing MongoDB 8.0..."; \
    Flags: waituntilterminated; \
    Tasks: installmongo
Filename: "sc.exe"; \
    Parameters: "create MongoDB binPath= ""\""{pf}\MongoDB\Server\8.0\bin\mongod.exe\"" --service --config=\""{pf}\MongoDB\Server\8.0\bin\mongod.cfg\"""" DisplayName= ""MongoDB Server"" start= auto"; \
    Flags: runhidden; \
    Tasks: installmongo
Filename: "sc.exe"; Parameters: "start MongoDB"; Flags: runhidden; Tasks: installmongo
Filename: "{tmp}\MicrosoftEdgeWebView2Setup.exe"; \
    Parameters: "/silent /install"; \
    StatusMsg: "Installing Edge WebView2 runtime..."; \
    Flags: waituntilterminated; \
    Tasks: installwebview
Filename: "{app}\app\{#MyAppExeName}"; \
    Description: "Launch {#MyAppName} now"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\app"
