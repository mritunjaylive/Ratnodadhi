; Inno Setup Script for Ratnodadhi (BookLib)
; To compile: Download Inno Setup (https://jrsoftware.org/isdl.php)
; and compile with Inno Setup Compiler or run: iscc installer.iss

#define MyAppName "Ratnodadhi"
#define MyAppVersion "6.0"
#define MyAppPublisher "Mritunjay Pandey"
#define MyAppURL "https://mritunjaylive.in"
#define MyAppExeName "Ratnodadhi.exe"
#define MyAppId "{{D37F02A4-95E3-4E87-8A2F-43BBF75F109E}"

[Setup]
; AppId uniquely identifies this application.
; Keep this identical across all future versions so the installer detects existing installations and performs seamless in-place upgrades.
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} v{#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes

; In-place Upgrade Configuration:
; - UsePreviousAppDir: Installs directly into the existing path without prompting if already installed.
; - CloseApplications: Uses Windows Restart Manager to gracefully close running Ratnodadhi instances before upgrading.
; - RestartApplications: Restarts the app after upgrade if it was automatically closed.
UsePreviousAppDir=yes
CloseApplications=yes
RestartApplications=yes
CloseApplicationsFilter=*.exe,*.dll

; 64-bit architecture support (installs into Program Files rather than Program Files (x86))
ArchitecturesInstallIn64BitMode=x64compatible

; Dual-mode installation: allows user to install system-wide (all users) or for current user only
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; Output configuration
OutputDir=dist-installer
OutputBaseFilename=Ratnodadhi-Setup-v{#MyAppVersion}
SetupIconFile=booklib\resources\ratnodadhi-logo.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}

; Version metadata embedded into the Setup.exe binary
VersionInfoVersion={#MyAppVersion}
VersionInfoDescription={#MyAppName} Setup Wizard
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}

; High-ratio LZMA2 compression for smallest installer file size
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Clean obsolete binaries and caches from previous version before extracting new files
Type: filesandordirs; Name: "{app}\_internal"

[Files]
; Source files built by PyInstaller in dist/Ratnodadhi
; ignoreversion ensures that updated files overwrite older ones regardless of timestamp
Source: "dist\Ratnodadhi\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

