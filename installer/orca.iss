; Установщик Orca. Сборка: ISCC.exe orca.iss  (или python make_installer.py)
#define AppName "Orca"
#include "version.iss"
#define AppPublisher "Maxim"
; SrcDir задаётся в version.iss (его пишет build_all.py)

[Setup]
AppId={{7B1F2B52-0C4E-4C3E-9E0B-4F0A5A1D0C21}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\
OutputBaseFilename=Orca-Setup-{#AppVersion}
SetupIconFile=..\icon.ico
UninstallDisplayIcon={app}\Orca.exe
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Ярлыки:"
Name: "startmenu"; Description: "Добавить в меню «Пуск»"; GroupDescription: "Ярлыки:"

[Files]
Source: "{#SrcDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\Orca.exe"; Tasks: startmenu
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\Orca.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Orca.exe"; Description: "Запустить Orca"; Flags: nowait postinstall skipifsilent
