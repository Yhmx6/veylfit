#define AppVersion "0.2.0"
[Setup]
AppId={{2F92DC94-F6A9-4B80-BFA0-CB6A97B75DC8}
AppName=映衣间 · Veylfit
AppVersion={#AppVersion}
AppPublisher=Veylfit
AppPublisherURL=https://github.com/Yhmx6/veylfit
DefaultDirName={localappdata}\Programs\Veylfit
DefaultGroupName=映衣间 Veylfit
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\release
OutputBaseFilename=Veylfit-Setup-{#AppVersion}-windows-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\Veylfit.exe
DisableProgramGroupPage=yes
CloseApplications=yes
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\Veylfit\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\docs\Windows使用说明.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\映衣间 Veylfit"; Filename: "{app}\Veylfit.exe"
Name: "{autodesktop}\映衣间 Veylfit"; Filename: "{app}\Veylfit.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Veylfit.exe"; Description: "Launch Veylfit"; Flags: nowait postinstall skipifsilent

; User-selected person archives and AppData/Veylfit are deliberately never deleted.
