; 答题助手 Inno Setup 安装包脚本
; 构建前置：先执行 PyInstaller（build.spec）生成 dist\答题助手\，
; 并确认 dist\答题助手\models\sense-voice\ 下存在模型文件。
; 编译：& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss

#define MyAppName "答题助手"
#define MyAppVersion "2.3"
#define MyAppPublisher "zhourunnan1210"
#define MyAppURL "https://github.com/zhourunnan1210/answer-assistant"
#define MyAppExeName "答题助手.exe"

[Setup]
AppId={{7A3F2C91-4E5B-4D6A-9C2E-1F8B3A5D7E9F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
; 安装到用户目录：免管理员权限，且 config.json 可写
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=installer
OutputBaseFilename=answer-assistant-setup-v{#MyAppVersion}
Compression=lzma2/max
SolidCompression=no
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
VersionInfoVersion={#MyAppVersion}
VersionInfoDescription={#MyAppName} 安装程序
CloseApplications=force
RestartApplications=no

[Languages]
Name: "chinesesimplified"; MessagesFile: "tools\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; config.json 含用户 API Key，绝不打进安装包
Source: "dist\答题助手\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "config.json"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent
