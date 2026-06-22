; Inno Setup script for Paper Reviewer
;
; Optional: produces a single PaperReviewer-Setup.exe installer with shortcuts +
; uninstaller, by wrapping the dist\PaperReviewer folder produced by build.bat.
;
; To use:
;   1. Run build.bat first (produces dist\PaperReviewer\)
;   2. Install Inno Setup from https://jrsoftware.org/isinfo.php (free)
;   3. Right-click this file -> Compile, or run:
;        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
;   4. The installer is written to Output\PaperReviewer-Setup.exe

#define MyAppName        "Paper Reviewer"
#define MyAppVersion     "2.0.0"
#define MyAppPublisher   "Asur"
#define MyAppExeName     "PaperReviewer.exe"
#define MyAppSourceDir   "dist\PaperReviewer"

[Setup]
AppId={{8C2F1B5E-4A7D-4E2A-9F9C-2B6E1D3F4A11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\PaperReviewer
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=PaperReviewer-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "{#MyAppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName} (opens the dashboard in your browser)"; Flags: nowait postinstall skipifsilent
