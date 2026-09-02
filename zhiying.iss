; ═══════════════════════════════════════════════════════════
;  智影视频智能检索平台 · Inno Setup 安装脚本（仿照 云侠.iss 骨架）
;
;  打包范围（[Files]）：桌面壳 exe + _internal（含后端字节码）+ 桌面前端 dist +
;   config + deploy 脚本 + requirements。**不含任何后端明文源码**——后端由
;   _internal\backend_pyc 字节码包运行（封装模式客户端无源码，见 deploy/build_backend_pyc.py）。
;
;  环境安装（[Code]）：不弹任何命令行/PowerShell 窗口——向导内置 2B/8B 档位选择页 +
;   代理输入页，安装完成后隐藏运行 deploy/setup_windows.ps1 -SkipModels，并在向导
;   进度页实时展示安装进度（setup_windows.ps1 -ProgressLog 写进度行）。
;  模型（25GB）：不进安装包 —— 首次启动桌面壳进 State.MODEL_BOOT 引导下载。
;
;  构建：先跑 desktop/build_exe.ps1 -Deploy（exe + _internal 落到项目根），再
;        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" zhiying.iss
;        可用 /D 覆盖：#define 见下（如 /DMyAppVersion=1.0 /DDefaultEmbeddingProfile=2b）
; ═══════════════════════════════════════════════════════════
#define MyAppName                  "智影视频智能检索平台"
#define MyAppVersion               "0.9.0"   ; 默认值；构建时被 build_installer.ps1 /DMyAppVersion 覆盖（自动取 core/version.py）
#define VersionInfoVersion         "1.0"
#define AppCopyright               ""
#define AppPublisher               ""
#define MyAppExeName               "智影桌面端.exe"
#define UnistallExe                "unins000.exe"
#define DefaultEmbeddingProfile    "8b"      ; 安装器写死档位；2B 机器构建时用 /DDefaultEmbeddingProfile=2b

[Setup]
AppId={{B85D2B83-9A12-4723-B8E0-A455D52EB32D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
VersionInfoVersion={#VersionInfoVersion}
AppCopyright={#AppCopyright}
AppPublisher={#AppPublisher}
; 客户机落点：D:\Zhiying（避开 Program Files 写入权限——models/data/config 都写应用目录）。
; 无 D: 盘的机器可在安装界面改目录（DisableDirPage=no）。
DefaultDirName=D:\Zhiying
DisableDirPage=no
; 开始菜单文件夹页无意义（只有一个主快捷方式，组名已由 DefaultGroupName 定死）→ 直接跳过
DisableProgramGroupPage=yes
DefaultGroupName={#MyAppName}
OutputDir=.\Bin
OutputBaseFilename=智影视频智能检索平台 Ver {#MyAppVersion}
Compression=lzma
SolidCompression=yes
PrivilegesRequired=admin
; 磁盘预检按真实占用：安装包本体虽小，但安装后 venv 依赖（CUDA torch + 全家桶）~15GB、
; 模型 8B ~25GB、内嵌 PG 数据全部落在安装目录所在盘 → 按 ~40GB 预检，避免装到一半盘满
ExtraDiskSpaceRequired=42949672960
; 6.2.1 只认 x64（x64compatible 是 6.3+ 才有的值）
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayIcon={app}\{#MyAppExeName}
WizardStyle=modern
SetupLogging=yes
CloseApplications=yes
RestartApplications=no

[Languages]
; 中文语言包 Inno 默认不随 6.7.3 安装，从 issrc 仓库 Unofficial 目录下载到项目内 deploy\iss-lang\
Name: "chinesesimplified"; MessagesFile: "deploy\iss-lang\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}";

[InstallDelete]
Type: files; Name:"{commondesktop}\{#MyAppName}.lnk"

[Files]
; ── 桌面壳 exe + _internal（含后端字节码包 backend_pyc，客户端无明文源码）──
Source: "智影桌面端.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
; ── 构建好的桌面前端 ──
Source: "frontend-desktop\dist\*"; DestDir: "{app}\frontend-desktop\dist"; Flags: ignoreversion recursesubdirs createallsubdirs
; ── 配置（config.yaml 由安装脚本从 example 生成；prompts/presets 后端运行要读）──
Source: "config\*"; DestDir: "{app}\config"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "config.yaml,__pycache__"
; ── 部署脚本：download_models.py（首启模型下载/校验）、setup_windows.ps1（环境安装）、stop_runtime.ps1（卸载停服）──
Source: "deploy\download_models.py"; DestDir: "{app}\deploy"; Flags: ignoreversion
Source: "deploy\setup_windows.ps1"; DestDir: "{app}\deploy"; Flags: ignoreversion
Source: "deploy\stop_runtime.ps1"; DestDir: "{app}\deploy"; Flags: ignoreversion
; ── 环境安装用 ──
Source: "requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
; setup_windows.ps1 生成的 vendor\.start-pg.py 用 venv python 按源码路径加载 desktop\db.py
Source: "desktop\db.py"; DestDir: "{app}\desktop"; Flags: ignoreversion

[Run]
; 装完启动桌面端 → 首次启动引导下载模型（State.MODEL_BOOT）
Filename: "{app}\{#MyAppExeName}"; Description: "启动 智影视频智能检索平台"; Flags: nowait postinstall skipifsilent unchecked

[UninstallRun]
; 卸载前停桌面壳 + 内嵌 postgres（容忍全部错误，不因停服失败中断卸载）
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\deploy\stop_runtime.ps1"" -Root ""{app}"""; Flags: runhidden

[UninstallDelete]
; 卸载清盘：.venv / vendor 是 setup 运行期生成的安装产物，不在 [Files] 清单里，
; 不声明则卸载后残留 10GB+。data（用户数据）与 models（可能含用户自备导入的模型）保留。
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\vendor"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{group}\卸载{#MyAppName}"; Filename: "{app}\{#UnistallExe}"

[Code]
// ═══════════════════════════════════════════════════════════
//  定制向导：2B/8B 档位页 + 代理输入页 + 环境安装进度。
//  进度条从头到尾只有一根：复用 Inno 原生安装页的 ProgressGauge
//  （解压阶段 Inno 自己驱动；环境安装阶段由 -ProgressLog 进度行接管，
//  离散真实标记 + 蠕动平滑推进）。
//  setup 完整输出落盘 vendor\install.output（错误弹窗自动带日志尾部，
//  不在向导里开实时小窗——等待循环在 UI 线程，日志控件滚动/重绘不可靠）。
//  环境安装隐藏运行（SW_HIDE，无任何命令行窗口）。
// ═══════════════════════════════════════════════════════════

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

// 泵消息：等待循环跑在 UI 线程，不泵消息窗口会整体假死（点不动/拖不动）
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
  OutputLogPath: String;      // {app}\vendor\install.output（落盘日志，失败弹窗自动带尾部）
  EnvBar: TNewProgressBar;    // 环境安装进度条（接管原生 gauge，渲染行为完全自控）
  DispPct: Integer;           // 当前显示进度（含蠕动平滑）
  CurCap: Integer;            // 当前阶段蠕动上限（到点停住等真实标记）
  CurStatus: String;          // 当前阶段文案（蠕动时随 % 一起刷新）
  LastCreep: DWORD;           // 上次蠕动时刻（GetTickCount）

// 从自备模型目录检测档位：models\Qwen\ 下子目录名含 2B → 2b；8B → 8b
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
  // 只留了预填前缀、没输端口 → 视为未使用代理
  if (P = 'http://127.0.0.1:') or (P = '127.0.0.1:') or (P = 'http://localhost:') then
    P := '';
  Result := P;
end;

// ── Ready 摘要页展示模型来源 + 代理选择 ─────────────────────
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
  // 追加智影自定义摘要（模型来源 + 代理）
  if GetModelSourceText() <> '' then
    Result := Result + NewLine + NewLine + '模型来源: ' + GetModelSourceText();
  Result := Result + NewLine + '代理配置: ' + GetProxyText();
end;

// 「浏览…」：弹文件夹选择器，回填路径框
procedure BrowseModelsDir(Sender: TObject);
var
  Dir: String;
begin
  Dir := PathEdit.Text;
  if Dir = '' then
    Dir := ExpandConstant('{sd}\');   // 默认起始目录，避免空串
  if BrowseForFolder('请选择自备模型的 models 目录：' + #13#10 +
      '例如 D:\projects\cerno\models，或 U盘/移动硬盘中拷贝来的 models 目录。' + #13#10 +
      '该目录会被复制到安装目录下的 \models（源目录本身不动）。',
      Dir, False) then
    PathEdit.Text := Dir;
end;

// 自备模型选中 → 显示路径行（输入框 + 浏览按钮）；否则隐藏
procedure RadioClick(Sender: TObject);
begin
  PathEdit.Visible := RadioSelf.Checked;
  BrowseBtn.Visible := RadioSelf.Checked;
end;

// 档位页「下一步」校验：自备模型必须给路径，且目录结构可辨认（models\Qwen 为锚，
// DetectProfile 与模型导入都依赖它）——否则会静默回退首启 25GB 在线下载
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

// 复制自备模型到 {app}\models（robocopy 隐藏运行；0-7=成功，8+=失败）
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
  // 放大向导窗口（进度/日志小窗等比获得更多空间；按钮组锚定底部自动跟随）
  WizardForm.Width := ScaleX(980);
  WizardForm.Height := ScaleY(720);
  WizardForm.InnerNotebook.Height :=
    WizardForm.CancelButton.Top - WizardForm.InnerNotebook.Top - ScaleY(12);

  ProfilePage := CreateCustomPage(wpSelectDir, '选择模型来源', '决定模型档位与获取方式');
  W := ProfilePage.Surface.Width;
  if W < 200 then W := 434;   // 兜底：个别分辨率下 Surface.Width 未就绪
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
  ProxyPage.Values[0] := 'http://127.0.0.1:';   // 预填本机前缀：只补端口号，整体可改/可清空
  try   // 光标定位到末尾，进入页面即可直接输端口号
    SendMessage(ProxyPage.Edits[0].Handle, $00B1 {EM_SETSEL},
      Length(ProxyPage.Values[0]), Length(ProxyPage.Values[0]));
  except
  end;

  // 环境安装进度条：与原生 gauge 同位同宽（自建实例，Position 渲染行为自控，
  // 规避原生 gauge 反复 Max/Position 赋值不重绘的问题）。环境安装开始时接管。
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

// 阶段 → 蠕动上限（略低于下一阶段起点标记；真实标记到达即切换）
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

// 蠕动平滑：真实事件稀疏（pip 非终端下无进度条，torch 3GB 下载期间无输出），
// 每 ~2.5s 显示进度 +1，到本阶段上限停住等真实标记——条不再长时间死住
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

// 解析 "PROGRESS\t<0-100>\t<slug>" 行并更新进度页
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
      Exit;   // 文件正被写入/短时锁定：本次跳过
    end;
    for i := 0 to Lines.Count - 1 do begin
      S := Lines[i];
      if Copy(S, 1, 8) <> 'PROGRESS' then
        Continue;
      Tail := Copy(S, 9, Length(S) - 8);   // "\t<pct>\t<slug>"
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
        // 真实标记：只前进不回退；蠕动上限随阶段切换
        if Pct > DispPct then DispPct := Pct;
        CurCap := CapFromSlug(Slug);
        CurStatus := StatusText;
        EnvBar.Position := DispPct;
        WizardForm.StatusLabel.Caption := '正在安装运行环境 · ' + IntToStr(DispPct) + '% — ' + StatusText;
      end;
    end;
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

// 读文件内容前若干行（错误弹窗用）
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

  // 前置检查：setup 脚本必须已随 [Files] 解压，否则直接给清晰报错
  if not FileExists(AppDir + '\deploy\setup_windows.ps1') then begin
    MsgBox('环境安装脚本缺失：' + AppDir + '\deploy\setup_windows.ps1' + #13#10 +
      '安装包文件未完整解压，请重新安装。', mbError, MB_OK);
    Abort();
  end;

  WizardForm.FilenameLabel.Caption := '';
  WizardForm.ProgressGauge.Visible := False;   // 原生条只服务解压阶段；环境安装换自建条
  EnvBar.Visible := True;
  EnvBar.Position := 0;
  DispPct := 0;
  CurCap := 6;          // env 阶段蠕动上限
  CurStatus := '准备中…';
  LastCreep := 0;
  WizardForm.StatusLabel.Caption := '正在安装运行环境 · 0% — 准备中…';
  WizardForm.Refresh;

  // 隐藏运行（SW_HIDE + ewNoWait）：不弹任何命令行窗口；完成经 DoneMarker 判断
  Params := '-NoProfile -ExecutionPolicy Bypass -File "' + AppDir +
    '\deploy\setup_windows.ps1" -SkipModels -NoElevate -Quiet' +
    ' -EmbeddingProfile "' + GetEmbeddingProfile() + '"' +
    ' -Proxy "' + GetProxy() + '"' +
    ' -ProgressLog "' + ProgressLog + '"' +
    ' -DoneMarker "' + DoneMarker + '"' +
    ' -OutputLog "' + OutputLogPath + '"';
  // 启动失败（如被安全软件拦截 powershell）立即报错——否则 DoneMarker 永不出现
  if not Exec('powershell.exe', Params, AppDir, SW_HIDE, ewNoWait, ResultCode) then begin
    WizardForm.StatusLabel.Caption := '环境安装失败';
    MsgBox('环境安装程序无法启动（powershell.exe 启动失败）。' + #13#10 + #13#10 +
      '常见原因：安全软件拦截。请检查后重试安装。', mbError, MB_OK);
    Abort();
  end;

  // 轮询进度日志 + 蠕动平滑 + 等完成标记；每轮泵消息（否则 UI 线程被 Sleep 堵死，
  // 窗口假死点不动），保持可拖动/可取消。90 分钟总超时兜底（防脚本被杀后永久卡死）
  StartTick := GetTickCount();
  TimedOut := False;
  repeat
    ProcessMessages();
    WizardForm.Refresh;
    UpdateProgressFromLog(ProgressLog);
    TickCreep();
    Sleep(300);
    if not FileExists(DoneMarker) then
      TimedOut := GetTickCount() - StartTick > 5400000;   // 90 min
  until FileExists(DoneMarker) or TimedOut;

  if TimedOut then begin
    WizardForm.StatusLabel.Caption := '环境安装超时';
    MsgBox('环境安装超过 90 分钟未完成，已中止。' + #13#10 + #13#10 +
      '常见原因：安全软件拦截了安装脚本（进程被杀，日志会戛然而止）/ 网络极慢。' + #13#10 +
      '（日志：' + AppDir + '\vendor\install.log 与 install.output）', mbError, MB_OK);
    Abort();
  end;

  if ReadMarker(DoneMarker) <> '0' then begin
    WizardForm.StatusLabel.Caption := '环境安装失败';
    EnvBar.Position := 0;
    // 读真实错误：install.log（trap 记录）优先，其次输出日志尾部
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

  // 清理安装耗材：仅在安装期使用（pip 清单 / 环境安装脚本自身 / PG 引导依赖），
  // 运行期无用——交付面只留运行必需。文件在 [Files] 清单里的，卸载时已删过会自动跳过。
  DeleteFile(ExpandConstant('{app}') + '\requirements.txt');
  DeleteFile(ExpandConstant('{app}') + '\deploy\setup_windows.ps1');
  DeleteFile(ExpandConstant('{app}') + '\desktop\db.py');

  // 自备模型已在 CurStepChanged 前置复制；此处收尾
  WizardForm.StatusLabel.Caption := '环境安装完成';
  EnvBar.Position := 100;
  DispPct := 100;
  WizardForm.Refresh;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then begin
    // 自备模型先行复制：robocopy 与环境安装相互独立，若放在环境安装之后，
    // 任何一步失败 Abort 都会连坐跳过复制 → 首启误入 25GB 在线下载
    if RadioSelf.Checked and (Trim(PathEdit.Text) <> '') then
      CopyModelsFromSource(Trim(PathEdit.Text));
    RunEnvSetup();
  end;
end;
