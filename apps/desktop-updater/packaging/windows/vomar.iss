[Setup]
AppId=org.openvimar.updater.desktop
AppName=Vomar
AppVersion={#NativeVersion}
VersionInfoVersion={#NativeVersion}
VersionInfoTextVersion={#NativeVersion}
VersionInfoProductVersion={#NativeVersion}
VersionInfoProductTextVersion={#NativeVersion}
DefaultDirName={localappdata}\Programs\Vomar
DefaultGroupName=Vomar
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputBaseFilename=vomar-desktop-{#DistributionVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
SetupIconFile={#BrandIcon}
UninstallDisplayIcon={app}\Vomar.exe
[Files]
Source: "{#Runtime}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\Vomar"; Filename: "{app}\Vomar.exe"
[Run]
Filename: "{app}\Vomar.exe"; Description: "Open Vomar"; Flags: nowait postinstall skipifsilent
; No UninstallDelete entries: private state/backups/credentials remain untouched.
