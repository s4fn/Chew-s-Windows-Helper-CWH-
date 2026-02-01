; Inno Setup script - creates installer for WinSys Utility
[Setup]
AppName=WinSys Utility
AppVersion=1.0
DefaultDirName={pf}\WinSys Utility
DefaultGroupName=WinSys Utility
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64

[Files]
Source: "dist\main.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "scripts\*"; DestDir: "{app}\scripts"; Flags: recursesubdirs createallsubdirs
Source: "assets\*"; DestDir: "{app}\assets"; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{group}\WinSys Utility"; Filename: "{app}\main.exe"; Tasks: desktopicon
Name: "{commondesktop}\WinSys Utility (Run as Administrator)"; Filename: "{app}\main.exe"; IconFilename: "{app}\assets\icon.ico"; Parameters: ""; Flags: runascurrentuser

[Tasks]
Name: desktopicon; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"