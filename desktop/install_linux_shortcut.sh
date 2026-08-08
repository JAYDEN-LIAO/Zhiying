#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════
#  智影桌面端 · Linux 桌面快捷方式安装（仅 Linux 开发机用）
#  Windows 桌面机用 create_desktop_shortcut.vbs（无黑框 + .ico）
#  用法: bash desktop/install_linux_shortcut.sh
# ═══════════════════════════════════════════════════════════
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${ROOT}/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python || true)"
if [ -z "${PY}" ]; then
  echo "[FAIL] 找不到 python（.venv/bin/python 或 PATH）" >&2
  exit 1
fi

APP_DIR="${HOME}/.local/share/applications"
DESKTOP_FILE="${APP_DIR}/zhiying.desktop"
mkdir -p "${APP_DIR}"

cat > "${DESKTOP_FILE}" <<EOF
[Desktop Entry]
Type=Application
Name=智影视频分析
Comment=Zhiying 桌面端启动器（管理本地后端生命周期）
Exec=${PY} ${ROOT}/desktop/app.py --gui qt
Icon=${ROOT}/desktop/assets/zhiying.png
Terminal=false
Categories=Utility;AudioVideo;
EOF
chmod +x "${DESKTOP_FILE}"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "${APP_DIR}" >/dev/null 2>&1 || true
fi

echo "已安装 Linux 桌面入口: ${DESKTOP_FILE}"
echo "应用菜单/桌面搜索「智影」即可启动"
echo "命令行快速启动: ${PY} ${ROOT}/desktop/app.py --gui qt"
