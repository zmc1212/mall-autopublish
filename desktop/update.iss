#define MyAppName "千牛自动上架"
#define MyAppVersion "1.1.0"
#define MyAppExeName "千牛自动上架.exe"
#define MyAppIconFile "..\logo\40c40691-9747-453a-a1d1-f2c94d393f34.ico"

[Setup]
AppId={{9C6A1E2B-4F70-4A91-9D33-B7E1C0A4D812}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
; 优先使用已安装版本的目录。GetDefaultDirName 会读取卸载注册表中的
; InstallLocation，并在目录确实包含完整运行环境时返回该目录。
DefaultDirName={code:GetDefaultDirName}
UsePreviousAppDir=yes
DefaultGroupName={#MyAppName}
DisableDirPage=no
OutputDir=..\dist
OutputBaseFilename=千牛自动上架-Update
Compression=lzma2
SolidCompression=yes
; 更新需要替换已安装目录中的 Qt/WebView 等 DLL。若用户把程序安装到
; D:\根目录等受保护位置，使用管理员权限可避免 MoveFile code 5。
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
SetupIconFile={#MyAppIconFile}
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes
RestartApplications=no
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\dist\千牛自动上架\千牛自动上架.exe"; DestDir: "{app}"; Flags: ignoreversion restartreplace
Source: "..\dist\千牛自动上架\*.py"; DestDir: "{app}"; Flags: ignoreversion restartreplace
Source: "..\dist\千牛自动上架\千牛字段映射.json"; DestDir: "{app}"; Flags: ignoreversion restartreplace
Source: "..\dist\千牛自动上架\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion restartreplace recursesubdirs createallsubdirs
Source: "..\dist\千牛自动上架\web\*"; DestDir: "{app}\web"; Flags: ignoreversion restartreplace recursesubdirs createallsubdirs
Source: "..\dist\千牛自动上架\templates\*"; DestDir: "{app}\templates"; Flags: ignoreversion restartreplace recursesubdirs createallsubdirs
Source: "..\dist\千牛自动上架\web_fill\*"; DestDir: "{app}\web_fill"; Flags: ignoreversion restartreplace recursesubdirs createallsubdirs

[Code]
var
  DetectedInstallDir: String;

function IsCompleteInstall(const Dir: String): Boolean;
begin
  Result :=
    (Dir <> '') and DirExists(Dir) and
    FileExists(AddBackslash(Dir) + '{#MyAppExeName}') and
    FileExists(AddBackslash(Dir) + 'runtime-manifest.json') and
    FileExists(AddBackslash(Dir) + 'node\node.exe') and
    FileExists(AddBackslash(Dir) + 'playwright-core\lib\tools\cli-client\cli.js') and
    FileExists(AddBackslash(Dir) + 'browser\chromium\chrome.exe') and
    FileExists(AddBackslash(Dir) + 'webview2\msedgewebview2.exe');
end;

function FindInstalledDir(): String;
var
  Candidate: String;
begin
  Result := '';

  { Per-user installs are the default, but also check the machine hives so
    an updater launched elevated can find an older all-users installation. }
  if RegQueryStringValue(HKCU,
       'Software\Microsoft\Windows\CurrentVersion\Uninstall\{9C6A1E2B-4F70-4A91-9D33-B7E1C0A4D812}_is1',
       'InstallLocation', Candidate) and IsCompleteInstall(Candidate) then
    Result := AddBackslash(Candidate);

  if (Result = '') and RegQueryStringValue(HKLM,
       'Software\Microsoft\Windows\CurrentVersion\Uninstall\{9C6A1E2B-4F70-4A91-9D33-B7E1C0A4D812}_is1',
       'InstallLocation', Candidate) and IsCompleteInstall(Candidate) then
    Result := AddBackslash(Candidate);
end;

function GetDefaultDirName(Param: String): String;
begin
  DetectedInstallDir := FindInstalledDir();
  if DetectedInstallDir <> '' then
    Result := DetectedInstallDir
  else
    Result := ExpandConstant('{localappdata}\Programs\{#MyAppName}');
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  { A valid installed directory is authoritative; avoid making users browse
    for it again. If detection fails, keep the directory page as a fallback. }
  Result := (PageID = wpSelectDir) and (DetectedInstallDir <> '');
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  AppDir: String;
  ResultCode: Integer;
begin
  Result := '';
  AppDir := AddBackslash(ExpandConstant('{app}'));

  { CloseApplications only handles applications that respond to the normal
    Windows close notification. The packaged app can leave a child process
    (or a hidden helper) holding a Qt DLL, so terminate its process tree once
    before Inno starts replacing files. A missing process is harmless. }
  Exec(ExpandConstant('{sys}\taskkill.exe'),
    '/F /T /IM "{#MyAppExeName}"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(500);

  if not FileExists(AppDir + 'runtime-manifest.json') or
     not FileExists(AppDir + 'node\node.exe') or
     not FileExists(AppDir + 'playwright-core\lib\tools\cli-client\cli.js') or
     not FileExists(AppDir + 'browser\chromium\chrome.exe') or
     not FileExists(AppDir + 'webview2\msedgewebview2.exe') then
    Result := '未找到完整安装的运行环境。请先使用 千牛自动上架-Setup.exe 安装完整版本。';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    if (not Exec(ExpandConstant('{app}\{#MyAppExeName}'), '--self-test', '', SW_HIDE,
      ewWaitUntilTerminated, ResultCode)) or (ResultCode <> 0) then
    begin
      MsgBox('更新后的运行环境自检未通过，请检查程序日志。', mbError, MB_OK);
      RaiseException('千牛自动上架更新自检失败');
    end;
  end;
end;
