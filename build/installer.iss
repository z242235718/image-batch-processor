; 图片批量处理工具安装程序
; 使用 Inno Setup 6 编译: ISCC.exe installer.iss
; 下载: https://jrsoftware.org/isdl.php

#define MyAppName "图片批量处理工具"
#define MyAppVersion "0.0.5"
#define MyAppPublisher "w2422"
#define MyAppURL "http://127.0.0.1:8000"
#define MyAppExeName "ImageBatchProcessor.exe"

[Setup]
; 应用信息
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; 安装目录
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes

; 输出
OutputDir=.\dist
OutputBaseFilename=ImageBatchProcessor_Setup_v{#MyAppVersion}

; 压缩（PyInstaller 产出较大，使用最高压缩比）
Compression=lzma2/ultra
SolidCompression=yes
InternalCompressLevel=ultra

; 卸载
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}

; 权限（写 Program Files 需要管理员）
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog

; 其他
DisableProgramGroupPage=yes
CloseApplications=no
RestartApplications=no

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："; Flags: checkedonce

[Files]
; 主程序文件（PyInstaller 构建输出）
Source: ".\dist\ImageBatchProcessor\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; 注意：AI 模型文件（~1GB+）不包含在安装包中。
; 首次使用"背景移除"功能时，程序会自动下载模型文件到 %LOCALAPPDATA%\.u2net\
; 如需离线部署，请将 .onnx 模型文件放入 models\ 目录，并取消注释以下行：
; Source: "..\models\*"; DestDir: "{localappdata}\{#MyAppName}\models"; Flags: ignoreversion recursesubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
; 安装后可选启动
Filename: "{app}\{#MyAppExeName}"; Description: "运行 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; 卸载时删除用户数据（用户数据目录）
Filename: "{cmd}"; Parameters: "/c rmdir /s /q ""{localappdata}\{#MyAppName}"""; Flags: runhidden runascurrentuser; RunOnceId: "RemoveUserData"

[Code]
function InitializeUninstall(): Boolean;
begin
  if MsgBox('是否删除所有用户数据（上传的图片、处理结果、配置等）？'#13#13'选择"是"将完全清理，选择"否"将保留数据。', mbConfirmation, MB_YESNO) = IDYES then
  begin
    // 由 [UninstallRun] 中的 RemoveUserData 处理
  end;
  Result := True;
end;
