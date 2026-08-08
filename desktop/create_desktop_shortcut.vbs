' ═══════════════════════════════════════════════════════════
'  智影视频分析 · 创建桌面快捷方式（无控制台黑框）
'  双击运行本脚本 → 桌面生成「智影视频分析.lnk」
'  快捷方式指向 pythonw（不弹 cmd 黑框），带应用图标
'  运行一次即可；删除快捷方式不影响启动器本身
' ═══════════════════════════════════════════════════════════
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")

' desktop/ 的上级 = 项目根
root    = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
icon    = root & "\desktop\assets\zhiying.ico"

' 定位 pythonw：优先 .venv，其次 PATH
pythonw = root & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(pythonw) Then pythonw = "pythonw.exe"

desktop  = sh.SpecialFolders("Desktop")
lnkPath  = desktop & "\智影视频分析.lnk"

Set sc = sh.CreateShortcut(lnkPath)
sc.TargetPath       = pythonw
sc.Arguments        = "desktop\app.py"
sc.WorkingDirectory = root
sc.Description      = "智影视频分析 · 桌面端（本地启动器）"
If fso.FileExists(icon) Then
    sc.IconLocation = icon & ",0"
End If
sc.Save

WScript.Echo "已创建桌面快捷方式：" & lnkPath
WScript.Echo "提示：请确认 Docker Desktop 设为开机自启（Settings → General → Start Docker Desktop when you sign in）"
