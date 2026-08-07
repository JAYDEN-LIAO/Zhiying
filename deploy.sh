#!/bin/bash
# deploy.sh — 服务器一键部署到指定版本 tag
#
# 用法（服务器 /home/services/zhiying 下，root）：
#   bash deploy.sh v0.25.1
#
# 流程：git fetch --tags → 迁移 config（首次）→ checkout 版本号
#       → requirements 变化才 pip → 前端构建 → 重启 → 健康检查
set -euo pipefail

VERSION="${1:?用法: bash deploy.sh <版本tag，如 v0.25.1>}"
REPO_DIR="/home/services/zhiying"
cd "$REPO_DIR"

echo "==> [1/6] git fetch --tags"
git fetch --tags origin

# config/config.yaml 机器相关、已 gitignore。首次（v0.25.1 起）从跟踪中解除，
# 文件保留在磁盘不被覆盖——避免 checkout 因"本地修改被覆盖"而拒绝。
if git ls-files --error-unmatch config/config.yaml >/dev/null 2>&1; then
    echo "==> [2/6] config/config.yaml 仍被 git 跟踪，解除跟踪（文件保留磁盘）"
    git rm --cached config/config.yaml
else
    echo "==> [2/6] config/config.yaml 未跟踪，跳过迁移"
fi

PREV=$(git rev-parse HEAD 2>/dev/null || echo none)
echo "==> [3/6] git checkout $VERSION"
git checkout "$VERSION"

if [ "$PREV" != "none" ] && git diff --quiet "$PREV" "$VERSION" -- requirements.txt 2>/dev/null; then
    echo "==> [4/6] requirements.txt 无变化，跳过 pip install"
else
    echo "==> [4/6] pip install -r requirements.txt"
    "$REPO_DIR/conda-env/bin/pip" install -r requirements.txt
fi

echo "==> [5/6] 前端构建"
cd "$REPO_DIR/frontend" && npm run build

echo "==> [6/6] 重启服务"
systemctl restart zhiying

echo "==> 健康检查（等待模型加载，最多 90s）"
for _ in $(seq 1 18); do
    sleep 5
    if curl -sf --max-time 3 http://127.0.0.1:8011/health >/dev/null 2>&1; then
        echo "  服务已就绪："
        curl -s --max-time 3 http://127.0.0.1:8011/health
        echo
        exit 0
    fi
done
echo "!! 90s 内未就绪，请检查：systemctl status zhiying / tail -f /home/services/zhiying/logs/server.log"
exit 1
