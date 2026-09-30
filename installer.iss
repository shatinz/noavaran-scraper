; Inno Setup Script for Noavaran Panjereh Scraper
; Compile using Inno Setup Compiler (iscc.exe installer.iss)

[Setup]
AppName=Noavaran Panjereh Scraper
AppVersion=1.0.0
AppPublisher=Noavaran Panjereh
DefaultDirName={userappdata}\Programs\NoavaranScraper
DefaultGroupName=Noavaran Panjereh
OutputDir=dist
OutputBaseFilename=NoavaranScraper-Setup
SetupIconFile=icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
PrivilegesRequired=lowest
DisableProgramGroupPage=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\NoavaranScraper.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Noavaran Panjereh Scraper"; Filename: "{app}\NoavaranScraper.exe"; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"
Name: "{group}\Uninstall Noavaran Panjereh Scraper"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Noavaran Panjereh Scraper"; Filename: "{app}\NoavaranScraper.exe"; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\NoavaranScraper.exe"; Description: "{cm:LaunchProgram,Noavaran Panjereh Scraper}"; Flags: nowait postinstall skipifsilent
