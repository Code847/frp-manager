; ============================================================================
;  FRP Manager · Windows 安装包脚本（Inno Setup 6）
;
;  编译方式（装好 Inno Setup 6 后，在项目根目录执行）：
;      iscc installer.iss
;  或：开始菜单 → Inno Setup Compiler → 打开 installer.iss → 编译。
;  常用：iscc installer.iss /DMyAppVersion=1.15.0.0
;
;  产物：Output\FRP-Manager-<版本>-Setup.exe
;
;  前置条件：先跑 `python build_exe.py`，dist\ 下要有 FRP-Manager-<时间戳>.exe。
;            [Files] 段用通配符匹配，会自动取到最新那次构建。
;
;  注意：本文件请用 UTF-8 with BOM 保存，否则中文文案会变乱码。
; ============================================================================

#ifndef MyAppVersion
  #define MyAppVersion "1.15.0.0"
#endif

#define MyAppName "FRP Manager"
#define MyAppPublisher "FRP Manager"
#define MyAppURL "https://github.com/Code847/frp-manager"

[Setup]
AppId={{8B7A2E5C-3D41-4F6A-9C10-2D5E7F8A1B34}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} - frp visualization panel
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputBaseFilename=FRP-Manager-{#MyAppVersion}-Setup
OutputDir=Output
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ChangesEnvironment=no
UninstallDisplayName={#MyAppName} {#MyAppVersion}
; exe 要写 Program Files 并建开始菜单项，所以需要管理员权限
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "zh"; MessagesFile: "compiler:Default.isl, lang\ChineseSimplified.isl"
Name: "en"; MessagesFile: "compiler:Default.isl, lang\English.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startupreg"; Description: "开机自动启动 FRP Manager"; GroupDescription: "附加选项"

[Files]
; 安装目录只放程序本体；configs / bin / logs / temp 由程序首次运行自动生成，
; 因此不会被打进安装包、也不会被卸载器删除。
Source: "dist\FRP-Manager-*.exe"; DestDir: "{app}"; Flags: ignoreversion
; 打包资源里的干净种子（仅 configs/README.md），其余运行时由程序自己写
Source: "configs\README.md"; DestDir: "{app}\configs"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\FRP-Manager.exe"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\FRP-Manager.exe"; Tasks: desktopicon

[Registry]
; 开机启动写到当前用户 Run 项，不需要管理员。数据目录就落在 {app} 内，
; 卸载时随程序一起消失。
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "FRP-Manager"; ValueData: "{app}\FRP-Manager.exe"; \
    Tasks: startupreg

; 「添加/删除程序」里补上发布者与链接
Root: HKLM; Subkey: "Software\Microsoft\Windows\CurrentVersion\Uninstall\{#emit SetupSetting("AppId")}"; \
    ValueType: string; ValueName: "Publisher"; ValueData: "{#MyAppPublisher}"
Root: HKLM; Subkey: "Software\Microsoft\Windows\CurrentVersion\Uninstall\{#emit SetupSetting("AppId")}"; \
    ValueType: string; ValueName: "URLInfoAbout"; ValueData: "{#MyAppURL}"

[Run]
Filename: "{app}\FRP-Manager.exe"; Description: "启动 FRP Manager"; Flags: nowait postinstall skipifsilent
