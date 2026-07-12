#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\dist-desktop\ModWatcherAgent"
#endif
#ifndef OutputDir
  #define OutputDir "..\..\release"
#endif

[Setup]
AppId={{B20CFDE2-9822-4BB7-94A7-7B661ACF7FF5}
AppName=Mod Watcher Agent
AppVersion={#AppVersion}
AppVerName=Mod Watcher Agent {#AppVersion}
AppPublisher=Mod Watcher Agent
DefaultDirName={localappdata}\Programs\ModWatcherAgent
DefaultGroupName=Mod Watcher Agent
AllowNoIcons=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=ModWatcherAgent-Setup-{#AppVersion}-win-x64
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
AppMutex=Local\ModWatcherAgentDesktop
Uninstallable=yes
UninstallDisplayIcon={app}\ModWatcherAgent.exe
SetupLogging=yes
ChangesAssociations=no
ChangesEnvironment=no

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[CustomMessages]
WebView2Requirement=Mod Watcher Agent 需要 Microsoft Edge WebView2 Runtime 才能显示桌面界面。
WebView2DownloadAddress=官方下载地址：
WebView2OpenPrompt=是否现在打开 Microsoft 官方下载页面？
WebView2InstallFailure=WebView2 Runtime 安装未成功（退出码 %1）。
WebView2InstallRetry=%1 请安装 Runtime 后重新运行安装器。
WebView2Missing=未检测到可用的 Microsoft Edge WebView2 Runtime。
UserDataDeleteFailed=未能完整删除用户数据，请稍后手动清理：%1
UserDataDeleteFirst=是否同时删除 Mod Watcher Agent 的全部用户数据？%n默认建议保留。此目录包含数据库、配置、日志、浏览器资料和快照。
UserDataDeleteSecond=此操作不可恢复。确认永久删除以下目录吗？%n%1

[Files]
#ifdef WebView2BootstrapperPath
Source: "{#WebView2BootstrapperPath}"; Flags: dontcopy noencryption
#endif
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Mod Watcher Agent"; Filename: "{app}\ModWatcherAgent.exe"
Name: "{autodesktop}\Mod Watcher Agent"; Filename: "{app}\ModWatcherAgent.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ModWatcherAgent.exe"; Description: "{cm:LaunchProgram,Mod Watcher Agent}"; Check: IsWebView2RuntimeInstalled; Flags: postinstall nowait skipifsilent

[Code]
const
  WebView2ClientKey = 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  WebView2DownloadUrl = 'https://developer.microsoft.com/microsoft-edge/webview2/';
  WebView2OfficialCommand = 'MicrosoftEdgeWebview2Setup.exe /silent /install';

function IsValidWebView2Version(const Version: String): Boolean;
var
  ParsedVersion: Int64;
begin
  Result := False;
  if (Trim(Version) = '') or (Trim(Version) = '0.0.0.0') then
    Exit;
  if not StrToVersion(Trim(Version), ParsedVersion) then
    Exit;
  Result := ParsedVersion > 0;
end;

function RegistryHasWebView2(const RootKey: HKEY): Boolean;
var
  Version: String;
begin
  Version := '';
  Result :=
    RegQueryStringValue(RootKey, WebView2ClientKey, 'pv', Version) and
    IsValidWebView2Version(Version);
end;

function IsWebView2RuntimeInstalled: Boolean;
begin
  { HKLM32 maps to the official WOW6432Node location on x64 Windows. }
  Result :=
    RegistryHasWebView2(HKCU32) or
    RegistryHasWebView2(HKCU64) or
    RegistryHasWebView2(HKLM32) or
    RegistryHasWebView2(HKLM64);
end;

procedure ShowWebView2Guidance(const Reason: String);
var
  ErrorCode: Integer;
  MessageText: String;
begin
  MessageText :=
    Reason + #13#10#13#10 +
    CustomMessage('WebView2Requirement') + #13#10 +
    CustomMessage('WebView2DownloadAddress') + WebView2DownloadUrl;
  Log(MessageText);
  if WizardSilent then
    Exit;
  if MsgBox(
    MessageText + #13#10#13#10 + CustomMessage('WebView2OpenPrompt'),
    mbError,
    MB_YESNO) = IDYES then
  begin
    ShellExec('open', WebView2DownloadUrl, '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
  end;
end;

#ifdef WebView2BootstrapperPath
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  BootstrapperPath: String;
  ExecSucceeded: Boolean;
  WebView2InstallExitCode: Integer;
  FailureText: String;
begin
  Result := '';
  if IsWebView2RuntimeInstalled then
    Exit;

  ExtractTemporaryFile('MicrosoftEdgeWebview2Setup.exe');
  BootstrapperPath := ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe');
  WebView2InstallExitCode := -1;
  Log('Running official WebView2 command: ' + WebView2OfficialCommand);
  ExecSucceeded := Exec(
    BootstrapperPath,
    '/silent /install',
    ExpandConstant('{tmp}'),
    SW_HIDE,
    ewWaitUntilTerminated,
    WebView2InstallExitCode);

  if (not ExecSucceeded) or
    (WebView2InstallExitCode <> 0) or
    (not IsWebView2RuntimeInstalled) then
  begin
    FailureText := FmtMessage(
      CustomMessage('WebView2InstallFailure'),
      [IntToStr(WebView2InstallExitCode)]);
    ShowWebView2Guidance(FailureText);
    Result := FmtMessage(
      CustomMessage('WebView2InstallRetry'),
      [FailureText]);
  end;
end;
#endif

procedure InitializeWizard;
begin
#ifndef WebView2BootstrapperPath
  if not IsWebView2RuntimeInstalled then
    ShowWebView2Guidance(CustomMessage('WebView2Missing'));
#endif
end;

procedure DeleteUserData;
begin
  if DirExists(ExpandConstant('{localappdata}\ModWatcherAgent')) and
    (not DelTree(
      ExpandConstant('{localappdata}\ModWatcherAgent'),
      True,
      True,
      True)) then
  begin
    MsgBox(
      FmtMessage(
        CustomMessage('UserDataDeleteFailed'),
        [ExpandConstant('{localappdata}\ModWatcherAgent')]),
      mbError,
      MB_OK);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;
  if UninstallSilent then
  begin
    Log('Silent uninstall preserves user data.');
    Exit;
  end;
  if not DirExists(ExpandConstant('{localappdata}\ModWatcherAgent')) then
    Exit;
  if MsgBox(
    CustomMessage('UserDataDeleteFirst'),
    mbConfirmation,
    MB_YESNO or MB_DEFBUTTON2) <> IDYES then
    Exit;
  if MsgBox(
    FmtMessage(
      CustomMessage('UserDataDeleteSecond'),
      [ExpandConstant('{localappdata}\ModWatcherAgent')]),
    mbConfirmation,
    MB_YESNO or MB_DEFBUTTON2) <> IDYES then
    Exit;
  DeleteUserData;
end;
