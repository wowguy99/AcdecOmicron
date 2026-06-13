; Inno Setup script for AcDec Flashcard Generator (Windows).
; Requires PyInstaller output at packaging\dist\AcDecFlashcards\

#define AppName "AcDec Flashcard Generator"
#define AppExe "AcDecFlashcards.exe"
#define AppPublisher "AcDec Flashcards"
#define AppURL "https://github.com"

[Setup]
AppId={{A7C3E9F1-2B4D-4E8A-9F6C-1D2E3F4A5B6C}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
DefaultDirName={autopf}\AcDecFlashcards
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=output
OutputBaseFilename=AcDecFlashcards-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExe}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

#ifndef AppSource
#define AppSource "dist\AcDecFlashcards"
#endif

#ifndef AppVersion
#define AppVersion "1.0.3"
#endif

[Files]
Source: "{#AppSource}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[Messages]
WelcomeLabel2=This will install [name/ver] on your computer.%n%nUser data (settings, subjects, uploads) is stored in your local AppData folder.
