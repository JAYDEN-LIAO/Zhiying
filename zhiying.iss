; ═══════════════════════════════════════════════════════════
;  视频快速智能检索平台 · Inno Setup 安装脚本
;  不含后端明文源码（backend_pyc 字节码运行）与 25GB 模型（首启 MODEL_BOOT 引导下载）
;  构建：desktop/build_exe.ps1 -Deploy → ISCC zhiying.iss
; ═══════════════════════════════════════════════════════════
#define ProductCode                "A5300"   ; 产品编号（软件管家定版；校验命令 software_center.exe 1 A5300 用）
#define ProductName                "视频快速智能检索平台"   ; 产品名称（定版权威字段）
#define MyAppName                  ProductName
; 版本号兜底值（不经 build_installer.ps1 /D 传参、GUI 直编时生效）；
; ./bump 会自动同步这里的两处 define——勿手写死旧版本
#ifndef MyAppVersion
#define MyAppVersion               "0.96"
#endif
#ifndef VersionInfoVersion
#define VersionInfoVersion         "0.96"
#endif
#define AppCopyright               ""
#define AppPublisher               ""
#define MyAppExeName               "智影桌面端.exe"
#define UnistallExe                "unins000.exe"
#define DefaultEmbeddingProfile    "8b"      ; 2B 机器构建时 /DDefaultEmbeddingProfile=2b

[Setup]
AppId={{B85D2B83-9A12-4723-B8E0-A455D52EB32D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
VersionInfoVersion={#VersionInfoVersion}
AppCopyright={#AppCopyright}
AppPublisher={#AppPublisher}
; 默认落 D:\Zhiying：避开 Program Files 写入权限（models/data/config 都写应用目录）
DefaultDirName=D:\Zhiying
DisableDirPage=no
DisableProgramGroupPage=yes
DefaultGroupName={#MyAppName}
OutputDir=.\build
OutputBaseFilename=视频快速智能检索平台 Ver {#MyAppVersion}
Compression=lzma
SolidCompression=yes
PrivilegesRequired=admin
; 磁盘预检 40GB：venv ~15GB + 模型 ~25GB 落安装盘
ExtraDiskSpaceRequired=42949672960
; 6.2.1 只认 x64（x64compatible 是 6.3+ 才有）
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayIcon={app}\{#MyAppExeName}
WizardStyle=modern
SetupLogging=yes
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "chinesesimplified"; MessagesFile: "deploy\iss-lang\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}";

[InstallDelete]
Type: files; Name:"{commondesktop}\{#MyAppName}.lnk"

[Files]
; 桌面壳 + _internal（含 backend_pyc，客户机无明文源码）——取 PyInstaller dist 产物（不经根目录中转）
Source: "dist\智影桌面端\智影桌面端.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\智影桌面端\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "frontend-desktop\dist\*"; DestDir: "{app}\frontend-desktop\dist"; Flags: ignoreversion recursesubdirs createallsubdirs
; config.yaml 装机时生成，故排除；prompts/presets 运行时要读
Source: "config\*"; DestDir: "{app}\config"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "config.yaml,__pycache__"
; 安装期耗材：装完由 [Code] 清理；download_models.py 例外（首启模型引导要用）
Source: "deploy\download_models.py"; DestDir: "{app}\deploy"; Flags: ignoreversion
Source: "deploy\setup_windows.ps1"; DestDir: "{app}\deploy"; Flags: ignoreversion
Source: "deploy\stop_runtime.ps1"; DestDir: "{app}\deploy"; Flags: ignoreversion
Source: "requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
; setup 生成的 vendor\.start-pg.py 按源码路径加载 desktop\db.py
Source: "desktop\db.py"; DestDir: "{app}\desktop"; Flags: ignoreversion

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 视频快速智能检索平台"; Flags: nowait postinstall skipifsilent unchecked

[UninstallRun]
; 停桌面壳 + 内嵌 postgres，否则文件被锁删不掉；容忍全部错误不中断卸载
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\deploy\stop_runtime.ps1"" -Root ""{app}"""; Flags: runhidden

[UninstallDelete]
; .venv/vendor 是安装产物，不声明则卸载残留 10GB+；data（用户数据）与 models（自备模型）保留
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\vendor"
; 快捷方式由 [Code] 在环境安装成功后创建（不进卸载日志），卸载时手动清
Type: files; Name: "{commondesktop}\{#ProductName}.lnk"
Type: filesandordirs; Name: "{group}"

[Code]
// 向导：档位页（8B/2B/自备模型导入）+ 代理页 + 环境安装进度（自建进度条接管原生条，
// setup 离散标记 + 蠕动平滑）。setup 输出落盘 vendor\install.output，失败弹窗带日志尾部。

const
  PM_REMOVE = $0001;

type
  TMsg = record
    hwnd: HWND;
    message: Cardinal;
    wParam: Longint;
    lParam: Longint;
    time: DWORD;
    pt: TPoint;
  end;

function SendMessage(hWnd: HWND; Msg, wParam, lParam: Longint): Longint;
external 'SendMessageA@user32.dll stdcall';

function GetTickCount: DWORD;
external 'GetTickCount@kernel32.dll stdcall';

function PeekMessage(var Msg: TMsg; hWnd: HWND; Min, Max, Remove: UINT): BOOL;
external 'PeekMessageA@user32.dll stdcall';

function TranslateMessage(const Msg: TMsg): BOOL;
external 'TranslateMessage@user32.dll stdcall';

function DispatchMessage(const Msg: TMsg): Longint;
external 'DispatchMessageA@user32.dll stdcall';

// 等待循环在 UI 线程，不泵消息窗口会假死
procedure ProcessMessages();
var
  Msg: TMsg;
begin
  while PeekMessage(Msg, 0, 0, 0, PM_REMOVE) do begin
    TranslateMessage(Msg);
    DispatchMessage(Msg);
  end;
end;

var
  ProfilePage: TWizardPage;
  Radio8B: TNewRadioButton;
  Radio2B: TNewRadioButton;
  RadioSelf: TNewRadioButton;
  PathEdit: TNewEdit;
  BrowseBtn: TNewButton;
  ProxyPage: TInputQueryWizardPage;
  OutputLogPath: String;      // {app}\vendor\install.output
  EnvBar: TNewProgressBar;    // 环境安装进度条（接管原生 gauge）
  DispPct: Integer;           // 显示进度（含蠕动）
  CurCap: Integer;            // 当前阶段蠕动上限
  CurStatus: String;
  LastCreep: DWORD;
  LastSnap: String;           // 进度日志尾部快照（判断有无新输出）
  LastEvent: DWORD;           // 最近一次新输出时刻（无输出超时依据）
  TotalStart: DWORD;          // 安装开始时刻（总兜底）
  ParsedCount: Integer;       // 已解析行数（增量解析防全量重放闪旧阶段文案）

// 自备模型档位检测：Qwen\ 子目录名含 2B/8B
function DetectProfile(const SourceDir: String): String;
var
  QwenDir, Mask: String;
  SearchRec: TFindRec;
begin
  Result := '8b';
  QwenDir := AddBackslash(SourceDir) + 'Qwen';
  if not DirExists(QwenDir) then
    Exit;
  Mask := AddBackslash(QwenDir) + '*';
  if FindFirst(Mask, SearchRec) then begin
    repeat
      if (SearchRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then begin
        if Pos('2B', UpperCase(SearchRec.Name)) > 0 then begin
          Result := '2b';
          FindClose(SearchRec);
          Exit;
        end else if Pos('8B', UpperCase(SearchRec.Name)) > 0 then begin
          Result := '8b';
          FindClose(SearchRec);
          Exit;
        end;
      end;
    until not FindNext(SearchRec);
    FindClose(SearchRec);
  end;
end;

function GetEmbeddingProfile(): String;
begin
  if RadioSelf.Checked then
    Result := DetectProfile(Trim(PathEdit.Text))
  else if Radio2B.Checked then
    Result := '2b'
  else
    Result := '8b';
end;

function GetProxy(): String;
var
  P: String;
begin
  P := Trim(ProxyPage.Values[0]);
  // 只留预填前缀没输端口 → 视为未用代理
  if (P = 'http://127.0.0.1:') or (P = '127.0.0.1:') or (P = 'http://localhost:') then
    P := '';
  Result := P;
end;

function GetModelSourceText(): String;
begin
  if not Assigned(RadioSelf) then begin
    Result := '';
    Exit;
  end;
  if RadioSelf.Checked then
    Result := '自备模型（从文件夹导入）: ' + Trim(PathEdit.Text)
  else if Radio2B.Checked then
    Result := '2B（在线下载，2048 维，低显存）'
  else
    Result := '8B（在线下载，4096 维，默认）';
end;

function GetProxyText(): String;
begin
  if GetProxy() = '' then
    Result := '无（未使用代理）'
  else
    Result := GetProxy();
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfo, MemoDirInfo, MemoTypeInfo,
    MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  Result := MemoUserInfo + NewLine + MemoDirInfo;
  if MemoTypeInfo <> '' then Result := Result + NewLine + MemoTypeInfo;
  if MemoComponentsInfo <> '' then Result := Result + NewLine + MemoComponentsInfo;
  if MemoGroupInfo <> '' then Result := Result + NewLine + MemoGroupInfo;
  if MemoTasksInfo <> '' then Result := Result + NewLine + MemoTasksInfo;
  if GetModelSourceText() <> '' then
    Result := Result + NewLine + NewLine + '模型来源: ' + GetModelSourceText();
  Result := Result + NewLine + '代理配置: ' + GetProxyText();
end;

procedure BrowseModelsDir(Sender: TObject);
var
  Dir: String;
begin
  Dir := PathEdit.Text;
  if Dir = '' then
    Dir := ExpandConstant('{sd}\');
  if BrowseForFolder('请选择自备模型的 models 目录：' + #13#10 +
      '例如 D:\projects\cerno\models，或 U盘/移动硬盘中拷贝来的 models 目录。' + #13#10 +
      '该目录会被复制到安装目录下的 \models（源目录本身不动）。',
      Dir, False) then
    PathEdit.Text := Dir;
end;

procedure RadioClick(Sender: TObject);
begin
  PathEdit.Visible := RadioSelf.Checked;
  BrowseBtn.Visible := RadioSelf.Checked;
end;

// 档位页校验：自备模型必须有路径且含 Qwen 子目录（否则静默回退首启 25GB 下载）
function NextButtonClick(CurPageID: Integer): Boolean;
var
  P: String;
begin
  Result := True;
  if (CurPageID = ProfilePage.ID) and RadioSelf.Checked then begin
    P := Trim(PathEdit.Text);
    if P = '' then begin
      MsgBox('已选择「自备模型」，请填写模型所在目录（点「浏览…」选择），或改选在线下载档位。',
        mbInformation, MB_OK);
      Result := False;
    end else if not DirExists(AddBackslash(P) + 'Qwen') then begin
      if MsgBox('所选目录下未找到 Qwen 子目录（期望结构：<目录>\Qwen\Qwen3-VL-Embedding-…）。' + #13#10 +
          '目录结构不对会导致模型导入后仍被判定缺失、首启需在线补齐。' + #13#10 + #13#10 +
          '仍要继续吗？', mbConfirmation, MB_YESNO) = IDNO then
        Result := False;
    end;
  end;
end;

// 复制自备模型到 {app}\models（robocopy 0-7=成功，8+=失败）
procedure CopyModelsFromSource(const SourceDir: String);
var
  ResultCode: Integer;
  DestDir: String;
begin
  DestDir := ExpandConstant('{app}') + '\models';
  CreateDir(DestDir);
  WizardForm.ProgressGauge.Position := 0;
  WizardForm.StatusLabel.Caption := '正在导入自备模型：正在从所选目录复制到 ' + DestDir + ' …（请稍候，约 25GB）';
  WizardForm.Refresh;
  Exec('robocopy.exe', '"' + SourceDir + '" "' + DestDir + '" /E /NFL /NDL /NJH /NJS /NP /R:1 /W:1',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  if ResultCode >= 8 then
    MsgBox('模型导入未完全成功（robocopy 退出码 ' + IntToStr(ResultCode) + '）。' + #13#10 +
      '首次启动时会自动校验并补齐缺失组件（人脸/车牌小件）。', mbInformation, MB_OK);
end;

procedure InitializeWizard();
var
  L, W: Integer;
begin
  WizardForm.Width := ScaleX(980);
  WizardForm.Height := ScaleY(720);
  WizardForm.InnerNotebook.Height :=
    WizardForm.CancelButton.Top - WizardForm.InnerNotebook.Top - ScaleY(12);

  ProfilePage := CreateCustomPage(wpSelectDir, '选择模型来源', '决定模型档位与获取方式');
  W := ProfilePage.Surface.Width;
  if W < 200 then W := 434;
  L := 12;

  Radio8B := TNewRadioButton.Create(ProfilePage);
  Radio8B.Parent := ProfilePage.Surface;
  Radio8B.Left := L; Radio8B.Top := 8; Radio8B.Width := W - L * 2;
  Radio8B.Caption := '8B（推荐，默认）—— 4096 维，需 ~16GB 显存，在线下载模型';
  Radio8B.Checked := True;
  Radio8B.OnClick := @RadioClick;

  Radio2B := TNewRadioButton.Create(ProfilePage);
  Radio2B.Parent := ProfilePage.Surface;
  Radio2B.Left := L; Radio2B.Top := 34; Radio2B.Width := W - L * 2;
  Radio2B.Caption := '2B（低显存）—— 2048 维，在线下载模型';
  Radio2B.OnClick := @RadioClick;

  RadioSelf := TNewRadioButton.Create(ProfilePage);
  RadioSelf.Parent := ProfilePage.Surface;
  RadioSelf.Left := L; RadioSelf.Top := 60; RadioSelf.Width := W - L * 2;
  RadioSelf.Caption := '自备模型（从本地文件夹导入，跳过 25GB 下载）';
  RadioSelf.OnClick := @RadioClick;

  PathEdit := TNewEdit.Create(ProfilePage);
  PathEdit.Parent := ProfilePage.Surface;
  PathEdit.Left := L + 24; PathEdit.Top := 88; PathEdit.Width := W - L * 2 - 104;
  PathEdit.Text := '';
  PathEdit.Visible := False;

  BrowseBtn := TNewButton.Create(ProfilePage);
  BrowseBtn.Parent := ProfilePage.Surface;
  BrowseBtn.Left := W - L - 76; BrowseBtn.Top := 86; BrowseBtn.Width := 76; BrowseBtn.Height := 24;
  BrowseBtn.Caption := '浏览…';
  BrowseBtn.Visible := False;
  BrowseBtn.OnClick := @BrowseModelsDir;

  ProxyPage := CreateInputQueryPage(wpSelectDir,
    '代理配置', '下载 GitHub 源组件可能需要代理',
    '已预填本机代理前缀，补上端口号即可（如 7897）；内容可整体修改或清空（留空则直连，国内 modelscope 源不受影响）。');
  ProxyPage.Add('代理地址（可留空）', False);
  ProxyPage.Values[0] := 'http://127.0.0.1:';
  try   // 光标定位末尾，直接补端口号
    SendMessage(ProxyPage.Edits[0].Handle, $00B1 {EM_SETSEL},
      Length(ProxyPage.Values[0]), Length(ProxyPage.Values[0]));
  except
  end;

  // 自建进度条与原生 gauge 同位：规避原生条反复 Max/Position 赋值不重绘的问题
  EnvBar := TNewProgressBar.Create(WizardForm);
  EnvBar.Parent := WizardForm.InstallingPage;
  EnvBar.Left := WizardForm.ProgressGauge.Left;
  EnvBar.Top := WizardForm.ProgressGauge.Top;
  EnvBar.Width := WizardForm.ProgressGauge.Width;
  EnvBar.Height := WizardForm.ProgressGauge.Height;
  EnvBar.Min := 0;
  EnvBar.Max := 100;
  EnvBar.Position := 0;
  EnvBar.Visible := False;
end;

// 阶段蠕动上限（略低于下一阶段起点标记）
function CapFromSlug(const Slug: String): Integer;
begin
  if Slug = 'env' then Result := 6
  else if Slug = 'deps' then Result := 68
  else if Slug = 'db' then Result := 78
  else if Slug = 'models' then Result := 88
  else if Slug = 'config' then Result := 91
  else if Slug = 'init' then Result := 98
  else if Slug = 'done' then Result := 100
  else Result := 99;
end;

// 蠕动平滑：pip 非终端下无进度可解析，真实标记稀疏 → 每 ~2.5s +1 到阶段上限停住
procedure TickCreep();
begin
  if (DispPct < CurCap) and ((LastCreep = 0) or (GetTickCount() - LastCreep > 2500)) then begin
    DispPct := DispPct + 1;
    LastCreep := GetTickCount();
    EnvBar.Position := DispPct;
    WizardForm.StatusLabel.Caption := '正在安装运行环境 · ' + IntToStr(DispPct) + '% — ' + CurStatus;
    WizardForm.Refresh;
  end;
end;

// 解析 setup 的 "PROGRESS\t<0-100>\t<slug>" 进度行
procedure UpdateProgressFromLog(const ALog: String);
var
  Lines: TStringList;
  i: Integer;
  S, Tail, PctStr, Slug, StatusText: String;
  P1, P2: Integer;
  Pct: Integer;
begin
  if not FileExists(ALog) then
    Exit;
  Lines := TStringList.Create;
  try
    try
      Lines.LoadFromFile(ALog);
    except
      Exit;   // 文件正被写入：本次跳过
    end;
    // 有新输出 → 刷新活跃时刻（模型段单个 16GB 文件下载期间 [progress] 帧持续到来）
    if Lines.Count > 0 then begin
      S := IntToStr(Lines.Count) + '|' + Lines[Lines.Count - 1];
      if S <> LastSnap then begin
        LastSnap := S;
        LastEvent := GetTickCount();
      end;
    end;
    // 增量解析：全量重放会每轮把标题从 env→deps→db→… 依次重设一遍（重绘插入时肉眼可见地
    // 闪过旧阶段文案，客户机长时间停在 models 阶段时尤其明显）。只解析上次之后的新行；
    // 末行留待下轮复读（防读到写了一半的行）。
    if Lines.Count < ParsedCount then
      ParsedCount := 0;   // 文件被重建（新一轮安装）→ 从头解析
    for i := ParsedCount to Lines.Count - 1 do begin
      S := Lines[i];
      if Copy(S, 1, 8) <> 'PROGRESS' then
        Continue;
      Tail := Copy(S, 9, Length(S) - 8);
      P1 := Pos(#9, Tail);
      if P1 = 0 then
        Continue;
      PctStr := Copy(Tail, P1 + 1, Length(Tail) - P1);
      P2 := Pos(#9, PctStr);
      if P2 > 0 then begin
        Pct := StrToIntDef(Copy(PctStr, 1, P2 - 1), -1);
        if Pct < 0 then
          Continue;
        Slug := Copy(PctStr, P2 + 1, Length(PctStr) - P2);
        if Slug = 'env' then StatusText := '安装 Python / FFmpeg 环境'
        else if Slug = 'deps' then StatusText := '创建虚拟环境并安装 Python 依赖（最耗时，请耐心等待）'
        else if Slug = 'db' then StatusText := '组装内嵌 PostgreSQL'
        else if Slug = 'models' then StatusText := '下载模型'
        else if Slug = 'config' then StatusText := '生成配置文件'
        else if Slug = 'init' then StatusText := '初始化数据库'
        else if Slug = 'done' then StatusText := '环境安装完成'
        else StatusText := '正在安装运行环境';
        // 只前进不回退；蠕动上限随阶段切换
        if Pct > DispPct then DispPct := Pct;
        CurCap := CapFromSlug(Slug);
        CurStatus := StatusText;
        EnvBar.Position := DispPct;
        WizardForm.StatusLabel.Caption := '正在安装运行环境 · ' + IntToStr(DispPct) + '% — ' + StatusText;
      end;
    end;
    ParsedCount := Lines.Count - 1;   // 末行下轮复读（防半行）；新行已全部消费
    if ParsedCount < 0 then ParsedCount := 0;
  finally
    Lines.Free;
  end;
end;

function ReadMarker(const FileName: String): String;
var
  Lines: TStringList;
begin
  Result := '';
  if not FileExists(FileName) then
    Exit;
  Lines := TStringList.Create;
  try
    Lines.LoadFromFile(FileName);
    if Lines.Count > 0 then
      Result := Trim(Lines[0]);
  finally
    Lines.Free;
  end;
end;

// 读文件头几行（错误弹窗用）
function ReadFileHead(const FileName: String; MaxLines: Integer): String;
var
  Lines: TStringList;
  i: Integer;
begin
  Result := '';
  if not FileExists(FileName) then
    Exit;
  Lines := TStringList.Create;
  try
    try
      Lines.LoadFromFile(FileName);
      for i := 0 to Lines.Count - 1 do begin
        if i >= MaxLines then Break;
        Result := Result + Lines[i] + #13#10;
      end;
    except
    end;
  finally
    Lines.Free;
  end;
end;

// 快捷方式延后创建：[Icons] 段在解压后立即执行（早于环境安装），装一半失败会留下
// 无效图标 → 改为环境安装成功后由代码创建；卸载清理走 [UninstallDelete]
procedure MakeLnk(const LnkPath, Target, WorkDir: String);
var
  Shell, Lnk: Variant;
begin
  Shell := CreateOleObject('WScript.Shell');
  Lnk := Shell.CreateShortcut(LnkPath);
  Lnk.TargetPath := Target;
  Lnk.WorkingDirectory := WorkDir;
  Lnk.IconLocation := Target + ',0';
  Lnk.Save;
end;

procedure CreateAppShortcuts();
var
  AppDir, Exe, Group: String;
begin
  AppDir := ExpandConstant('{app}');
  Exe := AppDir + '\' + ExpandConstant('{#MyAppExeName}');
  Group := ExpandConstant('{group}');
  ForceDirectories(Group);
  MakeLnk(Group + '\' + ExpandConstant('{#ProductName}') + '.lnk', Exe, AppDir);
  MakeLnk(Group + '\卸载' + ExpandConstant('{#ProductName}') + '.lnk',
    AppDir + '\' + ExpandConstant('{#UnistallExe}'), AppDir);
  if WizardIsTaskSelected('desktopicon') then
    MakeLnk(ExpandConstant('{commondesktop}\') + ExpandConstant('{#ProductName}') + '.lnk', Exe, AppDir);
end;

procedure RunEnvSetup();
var
  ResultCode: Integer;
  Params, AppDir, ProgressLog, DoneMarker: String;
  ErrDetail: String;
  StartTick: DWORD;
  TimedOut: Boolean;
begin
  AppDir := ExpandConstant('{app}');
  ProgressLog := AppDir + '\vendor\install.progress';
  DoneMarker := ExpandConstant('{tmp}') + '\env_setup_done.txt';
  OutputLogPath := AppDir + '\vendor\install.output';
  if FileExists(ProgressLog) then DeleteFile(ProgressLog);
  if FileExists(DoneMarker) then DeleteFile(DoneMarker);
  if FileExists(OutputLogPath) then DeleteFile(OutputLogPath);
  CreateDir(AppDir + '\vendor');

  if not FileExists(AppDir + '\deploy\setup_windows.ps1') then begin
    MsgBox('环境安装脚本缺失：' + AppDir + '\deploy\setup_windows.ps1' + #13#10 +
      '安装包文件未完整解压，请重新安装。', mbError, MB_OK);
    Abort();
  end;

  WizardForm.FilenameLabel.Caption := '';
  WizardForm.ProgressGauge.Visible := False;
  EnvBar.Visible := True;
  EnvBar.Position := 0;
  DispPct := 0;
  CurCap := 6;
  CurStatus := '准备中…';
  LastCreep := 0;
  WizardForm.StatusLabel.Caption := '正在安装运行环境 · 0% — 准备中…';
  WizardForm.Refresh;

  Params := '-NoProfile -ExecutionPolicy Bypass -File "' + AppDir +
    '\deploy\setup_windows.ps1" -NoElevate -Quiet' +
    ' -EmbeddingProfile "' + GetEmbeddingProfile() + '"' +
    ' -Proxy "' + GetProxy() + '"' +
    ' -ProgressLog "' + ProgressLog + '"' +
    ' -DoneMarker "' + DoneMarker + '"' +
    ' -OutputLog "' + OutputLogPath + '"';
  // 清残留：向导 ewNoWait 不看管子进程，失败/取消会留下孤儿 setup_windows 实例；
  // 重跑时并行实例交错写 install.progress → 进度状态文字来回闪、百分比互相踩。
  // 排除自身 PID（$PID）防自噬；连同清 .venv python（模型下载重试残留）与本安装相关的 curl
  Exec('powershell.exe',
    '-NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { ($_.ProcessId -ne $PID) -and (($_.CommandLine -match ''setup_windows\.ps1'') -or ($_.CommandLine -match ''\.venv\Scripts'') -or (($_.Name -eq ''curl.exe'') -and ($_.CommandLine -match ''Zhiying''))) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"',
    AppDir, SW_HIDE, ewWaitUntilTerminated, ResultCode);

  // 启动失败立即报错（如被安全软件拦截），否则 DoneMarker 永不出现
  if not Exec('powershell.exe', Params, AppDir, SW_HIDE, ewNoWait, ResultCode) then begin
    WizardForm.StatusLabel.Caption := '环境安装失败';
    MsgBox('环境安装程序无法启动（powershell.exe 启动失败）。' + #13#10 + #13#10 +
      '常见原因：安全软件拦截。请检查后重试安装。', mbError, MB_OK);
    Abort();
  end;

  // 轮询进度 + 蠕动 + 泵消息（防 UI 假死）。
  // 超时策略（模型 25GB 在安装段内下载，不能按总时长掐）：30 分钟无任何新输出 = 卡死；
  // 总时长 12h 兜底
  StartTick := GetTickCount();
  TotalStart := StartTick;
  LastEvent := StartTick;
  LastSnap := '';
  ParsedCount := 0;   // 进度文件已在上方删除重建，从头解析
  TimedOut := False;
  repeat
    ProcessMessages();
    WizardForm.Refresh;
    UpdateProgressFromLog(ProgressLog);
    TickCreep();
    Sleep(300);
    if not FileExists(DoneMarker) then
      TimedOut := (GetTickCount() - LastEvent > 1800000) or   // 30 min 无输出
                  (GetTickCount() - TotalStart > 43200000);   // 12h 总兜底
  until FileExists(DoneMarker) or TimedOut;

  if TimedOut then begin
    WizardForm.StatusLabel.Caption := '环境安装超时';
    MsgBox('环境安装长时间无进展，已中止。' + #13#10 + #13#10 +
      '常见原因：安全软件拦截了安装脚本（进程被杀，日志会戛然而止）/ 网络中断。' + #13#10 +
      '（日志：' + AppDir + '\vendor\install.log 与 install.output）' + #13#10 +
      '重新运行安装程序可从断点续传。', mbError, MB_OK);
    Abort();
  end;

  if ReadMarker(DoneMarker) <> '0' then begin
    WizardForm.StatusLabel.Caption := '环境安装失败';
    EnvBar.Position := 0;
    ErrDetail := ReadFileHead(AppDir + '\vendor\install.log', 12);
    if ErrDetail = '' then
      ErrDetail := ReadFileHead(OutputLogPath, 12);
    MsgBox('环境安装失败。' + #13#10 + #13#10 +
      '错误信息：' + #13#10 + ErrDetail + #13#10 +
      '（完整日志：' + AppDir + '\vendor\install.log）' + #13#10 +
      '常见原因：网络不通 / 磁盘空间不足 / 代理配置错误。',
      mbError, MB_OK);
    Abort();
  end;

  // 清理安装耗材（运行期无用；在 [Files] 清单里的卸载时会自动跳过）
  DeleteFile(ExpandConstant('{app}') + '\requirements.txt');
  DeleteFile(ExpandConstant('{app}') + '\deploy\setup_windows.ps1');
  DeleteFile(ExpandConstant('{app}') + '\desktop\db.py');

  CreateAppShortcuts();   // 全部安装步骤成功后才建图标

  WizardForm.StatusLabel.Caption := '环境安装完成';
  EnvBar.Position := 100;
  DispPct := 100;
  WizardForm.Refresh;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then begin
    // 自备模型复制前置：与环境安装互不依赖，避免安装失败连坐跳过复制
    if RadioSelf.Checked and (Trim(PathEdit.Text) <> '') then
      CopyModelsFromSource(Trim(PathEdit.Text));
    RunEnvSetup();
  end;
end;
