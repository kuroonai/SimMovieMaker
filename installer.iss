[Setup]
AppName=SimMovieMaker
AppVersion=2.0.0
AppPublisher=SimMovieMaker Contributors
DefaultDirName={autopf}\SimMovieMaker
DefaultGroupName=SimMovieMaker
UninstallDisplayIcon={app}\assets\smm.ico
LicenseFile=LICENSE
OutputDir=installer
OutputBaseFilename=SimMovieMaker_Setup_2.0.0
Compression=lzma2
SolidCompression=yes
SetupIconFile=assets\smm.ico
ArchitecturesInstallIn64BitMode=x64compatible
ChangesEnvironment=yes

[Types]
Name: "full"; Description: "Full installation"
Name: "compact"; Description: "Compact installation"
Name: "custom"; Description: "Custom installation"; Flags: iscustom

[Components]
Name: "main"; Description: "SimMovieMaker application"; Types: full compact custom; Flags: fixed
Name: "addtopath"; Description: "Add application directory to PATH"; Types: full

[Files]
Source: "build\main.dist\*"; DestDir: "{app}"; Components: main; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "assets\smm.ico"; DestDir: "{app}\assets"; Components: main; Flags: ignoreversion

[Icons]
Name: "{group}\SimMovieMaker"; Filename: "{app}\SimMovieMaker.exe"; IconFilename: "{app}\assets\smm.ico"
Name: "{group}\Uninstall SimMovieMaker"; Filename: "{uninstallexe}"
Name: "{autodesktop}\SimMovieMaker"; Filename: "{app}\SimMovieMaker.exe"; IconFilename: "{app}\assets\smm.ico"

[Registry]
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; \
    ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; \
    Components: addtopath; Check: NeedsAddPath(ExpandConstant('{app}'))

[Code]
function NeedsAddPath(Param: string): Boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKEY_LOCAL_MACHINE,
    'SYSTEM\CurrentControlSet\Control\Session Manager\Environment',
    'Path', OrigPath)
  then begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Uppercase(Param) + ';', ';' + Uppercase(OrigPath) + ';') = 0;
end;

function FfmpegExists(): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec('cmd.exe', '/C ffmpeg -version', '', SW_HIDE, ewWaitUntilTerminated, ResultCode)
           and (ResultCode = 0);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    if not FfmpegExists() then
    begin
      MsgBox('ffmpeg was not found on your system.' + #13#10 + #13#10 +
             'SimMovieMaker requires ffmpeg for some features. ' +
             'Please install ffmpeg and ensure it is available on your PATH.' + #13#10 + #13#10 +
             'You can download ffmpeg from https://ffmpeg.org/download.html',
             mbInformation, MB_OK);
    end;
  end;
end;
