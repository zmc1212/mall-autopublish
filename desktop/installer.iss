#define MyAppName "千牛自动上架"
#define MyAppVersion "1.1.0"
#define MyAppPublisher "千牛自动上架"
#define MyAppExeName "千牛自动上架.exe"
#define MyAppIconFile "..\logo\40c40691-9747-453a-a1d1-f2c94d393f34.ico"

[Setup]
AppId={{9C6A1E2B-4F70-4A91-9D33-B7E1C0A4D812}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableDirPage=no
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=千牛自动上架-Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
SetupIconFile={#MyAppIconFile}
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupLogging=yes
CloseApplications=no
UsedUserAreasWarning=no
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\dist\千牛自动上架\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "打开千牛自动上架"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  LogPath: String;
begin
  if CurStep = ssPostInstall then
  begin
    LogPath := ExpandConstant('{userappdata}\千牛自动上架\logs\self-test.log');
    if (not Exec(ExpandConstant('{app}\{#MyAppExeName}'), '--self-test', '', SW_HIDE,
      ewWaitUntilTerminated, ResultCode)) or (ResultCode <> 0) then
    begin
      MsgBox(
        '安装后的运行环境自检没有通过。安装包可能不完整，程序不会处于可用状态。' #13#10 #13#10 +
        '请将此日志交给维护人员：' #13#10 + LogPath,
        mbError, MB_OK);
      RaiseException('千牛自动上架运行环境自检失败');
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{userappdata}\千牛自动上架');
    if DirExists(DataDir) then
    begin
      if MsgBox('是否同时删除登录态、设置和本地日志？' #13#10 '选择“否”将保留 %APPDATA%\千牛自动上架，下次安装后不必重新登录。', mbConfirmation, MB_YESNO) = IDYES then
      begin
        DelTree(DataDir, True, True, True);
      end;
    end;
  end;
end;
