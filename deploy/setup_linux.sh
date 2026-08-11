#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════
# 智影 Linux 一键安装器（裸机 → 环境就绪）
# 目标：在全新 Linux + NVIDIA GPU 机器上，git clone 项目后一条命令装齐
#   系统级  python3 / ffmpeg / exiftool / docker（缺失时）
#   依赖级  CUDA torch(按 GPU/驱动选源) + torchvision + requirements 全部包
#   模型级  embedding / yolo / reid / face / plate / segmenter
#   前端级  Node + frontend-desktop/frontend dist
# 产物与本机参考形态一致：.venv / models/ / config/config.yaml / 两个 dist。
#
# 特性（与 deploy/setup_windows.ps1 同规格）：
#   - 智能探测：已有且兼容的组件直接复用；缺失/不兼容才装
#   - 网络智能：代理必填；GitHub/PyTorch 走代理、国内镜像直连
#   - 交互：开始提示注意事项 + 输入代理地址并实测
#   - 健壮：探测命令不中断；每步失败给出步骤+原因，绝不静默闪退
#   - 幂等：重跑自动跳过已完成组件（断点续跑）
#
# 用法：
#   bash deploy/setup_linux.sh                                     # 交互式（输入代理）
#   bash deploy/setup_linux.sh --proxy http://127.0.0.1:7897 --non-interactive  # 全自动
#   bash deploy/setup_linux.sh --skip-deps --skip-models --skip-docker --skip-frontend  # 排障
# ═══════════════════════════════════════════════════════════
set -u
set -o pipefail

# ── 参数 ───────────────────────────────────────────────────
PROXY=""
NON_INTERACTIVE=0
SKIP_DEPS=0
SKIP_MODELS=0
SKIP_DOCKER=0
SKIP_FRONTEND=0
RETRIES=3
while [[ $# -gt 0 ]]; do
    case "$1" in
        --proxy) PROXY="$2"; shift 2 ;;
        --non-interactive) NON_INTERACTIVE=1; shift ;;
        --skip-deps) SKIP_DEPS=1; shift ;;
        --skip-models) SKIP_MODELS=1; shift ;;
        --skip-docker) SKIP_DOCKER=1; shift ;;
        --skip-frontend) SKIP_FRONTEND=1; shift ;;
        --retries) RETRIES="$2"; shift 2 ;;
        *) echo "未知参数: $1"; exit 2 ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VPY="$ROOT/.venv/bin/python"

# 是 root 时无需 sudo
if [[ "$(id -u)" == "0" ]]; then SUDO=""; else SUDO="sudo"; fi

# ── 颜色 / 输出 ────────────────────────────────────────────
C_CYAN='\033[0;36m'; C_GRN='\033[0;32m'; C_YEL='\033[0;33m'
C_RED='\033[0;31m'; C_DIM='\033[0;90m'; C_OFF='\033[0m'
write_step() { echo; echo "────────────────────────────────────────"; echo -e "[${C_CYAN}$1/$2${C_OFF}] $3"; echo "────────────────────────────────────────"; }
write_info() { echo -e "  ${C_DIM}$1${C_OFF}"; }
write_ok()   { echo -e "  ${C_GRN}[ok] $1${C_OFF}"; }
write_warn() { echo -e "  ${C_YEL}[warn] $1${C_OFF}"; }
write_fail() { echo -e "  ${C_RED}[error] $1${C_OFF}"; }
error() { write_fail "$1"; exit 1; }

# 流式运行并返回真实退出码（stdout/stderr 逐行缩进显示，不吞输出）
stream() {
    local rc
    "$@" 2>&1 | sed 's/^/  /'
    rc=${PIPESTATUS[0]}
    return $rc
}

# 代理开关（子进程下载时生效）
with_proxy()   { export HTTP_PROXY="$PROXY" HTTPS_PROXY="$PROXY" http_proxy="$PROXY" https_proxy="$PROXY"; }
without_proxy() { unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy; }

# 真实 CUDA 内核验证（is_available 会假通过，kernel 缺失才炸）
torch_cuda_kernel_ok() {
    "$VPY" -c "import torch;x=torch.randn(1024,1024,device='cuda');(x@x).sum().item();print('cuda-ok')" >/dev/null 2>&1
}

# torch CUDA 源选择（与 Windows 版逻辑一致：Blackwell→cu130，驱动版本分级）
pick_torch_index() {
    local gpu="$1" cuda="$2"
    if [[ "$gpu" =~ RTX[[:space:]]*5|Blackwell ]]; then echo "https://download.pytorch.org/whl/cu130"; return; fi
    if [[ -z "$cuda" ]]; then echo "https://download.pytorch.org/whl/cu126"; return; fi
    local maj="${cuda%%.*}"; local min="${cuda#*.}"; min="${min%%.*}"
    if (( maj >= 13 )); then echo "https://download.pytorch.org/whl/cu130"
    elif (( maj >= 12 && min >= 8 )); then echo "https://download.pytorch.org/whl/cu128"
    elif (( maj >= 12 && min >= 6 )); then echo "https://download.pytorch.org/whl/cu126"
    elif (( maj >= 12 && min >= 4 )); then echo "https://download.pytorch.org/whl/cu124"
    elif (( maj >= 12 && min >= 1 )); then echo "https://download.pytorch.org/whl/cu121"
    else echo ""; fi
}

# ═══════════════════════════════════════════════════════════
# 0. 交互：注意事项 + 代理输入
# ═══════════════════════════════════════════════════════════
echo -e "${C_CYAN}智影 Linux 一键安装器（裸机 → 环境就绪）${C_OFF}"
echo "目标：自动安装 Python venv / FFmpeg / Docker / CUDA torch / 全部依赖 / 全部模型 / 前端 dist"
echo ""
echo -e "${C_YEL}━━━━ 注意事项（请先阅读）━━━━${C_OFF}"
echo "  1. 部分步骤需要 sudo（系统依赖/安装 docker）；脚本会在用到时提示输入密码"
echo "  2. 需要 NVIDIA GPU + 驱动（脚本会检测 CUDA 版本）"
echo "  3. 需要可用的代理（脚本强制要求，用于 GitHub / PyTorch 下载）"
echo "  4. 总下载量约 25GB+（torch ~2.6GB + embedding 16GB + 其余模型），请保证磁盘空间"
echo "  5. 数据库用 Docker（docker compose up -d db，pgvector/pg17）"
echo "  6. 装完仅打印启动指令；数据库/后端/前端由你自己启动"
echo "  7. 摘要 API key（DashScope/DeepSeek）请在启动后于前端「设置页」填写"
echo -e "${C_YEL}━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_OFF}"

if [[ -z "$PROXY" ]]; then
    if [[ "$NON_INTERACTIVE" == "1" ]]; then error "-NonInteractive 模式必须同时传 --proxy"; fi
    echo ""
    read -rp "请输入代理地址（必填，如 http://127.0.0.1:7897）: " PROXY
fi
PROXY="${PROXY%/}"
[[ -z "$PROXY" ]] && error "代理地址不能为空"

if ! curl -x "$PROXY" -s -o /dev/null -w "%{http_code}" --max-time 15 https://github.com 2>/dev/null | grep -qE "^[23]"; then
    error "代理测试失败（github.com）。请确认代理软件已启动且地址正确。"
fi
write_ok "代理可用：$PROXY"

# ═══════════════════════════════════════════════════════════
# 1. 环境探测
# ═══════════════════════════════════════════════════════════
write_step 1 10 "探测现有环境"
ARCH="$(uname -m)"
GPU_NAME=""; DRIVER_CUDA=""
if command -v nvidia-smi >/dev/null 2>&1; then
    GPU_NAME="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || true)"
    DRIVER_CUDA="$(nvidia-smi 2>/dev/null | grep -oP 'CUDA Version:\s*\K[0-9.]+' | head -1 || true)"
    write_ok "GPU: ${GPU_NAME:-未知} | 驱动 CUDA: ${DRIVER_CUDA:-未知}"
else
    write_fail "未检测到 nvidia-smi（NVIDIA 驱动）。智影依赖 GPU 推理，请先安装 NVIDIA 驱动。"
    error "缺少 NVIDIA GPU / 驱动"
fi
write_ok "平台: $ARCH | Python: $(python3 --version 2>/dev/null || echo 缺失) | FFmpeg: $(command -v ffmpeg >/dev/null && echo 已装 || echo 缺失) | Docker: $(docker info >/dev/null 2>&1 && echo 可用 || echo 缺失) | Node: $(node -v 2>/dev/null || echo 缺失)"

# ═══════════════════════════════════════════════════════════
# 2. 系统依赖（apt：python3/ffmpeg/exiftool/curl/git；docker 缺失时装 docker.io）
# ═══════════════════════════════════════════════════════════
write_step 2 10 "系统依赖"
if command -v apt-get >/dev/null 2>&1; then
    need=""
    for p in python3 ffmpeg exiftool curl git; do
        command -v "$p" >/dev/null 2>&1 || need="$need $p"
    done
    # python3-venv 是包不是命令，用 import 探测
    python3 -c "import venv" >/dev/null 2>&1 || need="$need python3-venv"
    if [[ -n "$need" ]]; then
        write_info "安装系统依赖（apt）：$need ..."
        if ! stream $SUDO apt-get update; then error "apt-get update 失败（检查网络/源）"; fi
        if ! stream $SUDO apt-get install -y python3 python3-venv ffmpeg exiftool curl git; then
            error "系统依赖安装失败（见上方输出）"
        fi
        write_ok "系统依赖就绪"
    else
        write_ok "系统依赖已具备，跳过"
    fi
else
    write_warn "未检测到 apt-get（非 Debian/Ubuntu？）。请手动确保：python3+venv / ffmpeg / exiftool / curl / git"
fi

# ═══════════════════════════════════════════════════════════
# 3. Python venv + config.yaml
# ═══════════════════════════════════════════════════════════
write_step 3 10 "Python 虚拟环境 + config.yaml"
if [[ -x "$VPY" ]]; then
    write_ok "venv 已存在，跳过创建"
else
    pyver=""
    for v in 3.13 3.12 3.11; do command -v "python$v" >/dev/null 2>&1 && pyver="$v" && break; done
    if [[ -z "$pyver" ]]; then
        pyver="$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo 3.12)"
    fi
    if command -v "python$pyver" >/dev/null 2>&1; then pycmd="python$pyver"; else pycmd="python3"; fi
    write_info "创建 .venv（$pycmd，Python $pyver）..."
    if ! "$pycmd" -m venv "$ROOT/.venv"; then error "venv 创建失败（缺 python3-venv？先跑系统依赖步骤）"; fi
    write_ok "已创建 .venv"
fi

# config.yaml（缺失时从 example 生成；桌面启动器/后端必需品）
if [[ -f "$ROOT/config/config.yaml" ]]; then
    write_ok "config/config.yaml 已存在，跳过生成"
elif [[ -f "$ROOT/config/config.yaml.example" ]]; then
    cp "$ROOT/config/config.yaml.example" "$ROOT/config/config.yaml"
    write_ok "已生成 config/config.yaml（复制 example；路径/密钥按机器改，见文件内注释）"
else
    write_warn "config/config.yaml.example 不存在（仓库文件缺失？），后端启动前需手动配置 config"
fi

# ═══════════════════════════════════════════════════════════
# 4. CUDA torch + torchvision
# ═══════════════════════════════════════════════════════════
write_step 4 10 "CUDA PyTorch + torchvision"
if [[ "$SKIP_DEPS" == "1" ]]; then write_info "已跳过（--skip-deps）"; else
    # 复用探测：已有可用 CUDA torch 则直接跳过
    if "$VPY" -c "import torch;print(torch.cuda.is_available())" 2>/dev/null | grep -q True; then
        write_ok "PyTorch 已可用（CUDA），跳过安装"
    else
        IDX="$(pick_torch_index "$GPU_NAME" "$DRIVER_CUDA")"
        if [[ -z "$IDX" ]]; then error "驱动过旧（CUDA ${DRIVER_CUDA:-?} < 12.1），请升级 NVIDIA 驱动到 550+"; fi
        if [[ "$ARCH" == "aarch64" || "$ARCH" == "arm64" ]]; then
            write_warn "aarch64（如 DGX Spark/GB10）的 CUDA torch wheel 可能不齐全，先尝试 pip 源；失败请看下方提示"
        fi
        write_info "安装 CUDA 版 PyTorch（$IDX，走代理）..."
        with_proxy
        if ! stream "$VPY" -m pip install torch torchvision --index-url "$IDX"; then
            without_proxy
            if [[ "$ARCH" == "aarch64" || "$ARCH" == "arm64" ]]; then
                error "torch 安装失败（aarch64）。参考机（GB10）用的是 conda：conda install pytorch torchvision pytorch-cuda -c pytorch -c nvidia"
            else
                error "torch 安装失败（见上方输出，检查代理）"
            fi
        fi
        without_proxy
        write_ok "torch 已安装"
    fi

    # 真实 CUDA kernel 验证（is_available 假通过、kernel 缺失才炸）
    write_info "验证真实 CUDA kernel ..."
    if ! torch_cuda_kernel_ok; then
        error "CUDA kernel 验证失败——torch 版本与该 GPU 不兼容，请升级驱动后重跑（aarch64 可试 conda 源）"
    fi
    write_ok "PyTorch GPU 就绪"
fi

# ═══════════════════════════════════════════════════════════
# 5. requirements + onnxruntime-gpu 处理
# ═══════════════════════════════════════════════════════════
write_step 5 10 "Python 依赖"
if [[ "$SKIP_DEPS" == "1" ]]; then write_info "已跳过（--skip-deps）"; else
    # Aliyun 国内镜像直连（免代理）
    "$VPY" -m pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ >/dev/null 2>&1 || true
    # onnxruntime(CPU) 与 onnxruntime-gpu 是不同发行版，同装会让 CPU 版抢占 import；
    # 生成剔除 onnxruntime 行的临时 requirements，gpu 版由下面逻辑统一处理（幂等）。
    tmp_req="$(mktemp)"
    grep -vE "^\s*onnxruntime" "$ROOT/requirements.txt" > "$tmp_req" || true
    write_info "安装 requirements（Aliyun 镜像直连，排除 onnxruntime）..."
    without_proxy
    if ! stream "$VPY" -m pip install -r "$tmp_req"; then rm -f "$tmp_req"; error "requirements 安装失败（见上方实时输出）"; fi
    rm -f "$tmp_req"

    # ── onnxruntime：x86_64 用 GPU 版；aarch64 无 GPU wheel → CPU 版 ──
    if [[ "$ARCH" == "x86_64" || "$ARCH" == "AMD64" ]]; then
        if "$VPY" -c "import onnxruntime as ort;print('CUDAExecutionProvider' in ort.get_available_providers())" 2>/dev/null | grep -q True; then
            write_ok "onnxruntime-gpu 已就绪"
        else
            write_info "替换 onnxruntime → onnxruntime-gpu（需代理拉 CUDA provider）..."
            without_proxy
            "$VPY" -m pip uninstall -y onnxruntime onnxruntime-gpu >/dev/null 2>&1 || true
            with_proxy
            if ! stream "$VPY" -m pip install onnxruntime-gpu; then
                without_proxy
                error "onnxruntime-gpu 安装失败（检查代理）"
            fi
            without_proxy
            write_ok "onnxruntime-gpu 已安装"
        fi
        # 虚拟 dist-info 桩：hyperlpr3/insightface 声明依赖 onnxruntime 发行版，
        # 但只用 gpu 版。建"无文件"桩让 pip 认为 onnxruntime 已装，避免以后把 CPU 版拉回来抢占。
        stub_py="$(mktemp)"
        cat > "$stub_py" <<'PY'
import importlib.metadata as m
from pathlib import Path
import sysconfig
site = Path(sysconfig.get_paths()["purelib"])
ver = m.version("onnxruntime-gpu")
distinfo = site / f"onnxruntime-{ver}.dist-info"
distinfo.mkdir(exist_ok=True)
(distinfo / "METADATA").write_text(
    f"Metadata-Version: 2.1\nName: onnxruntime\nVersion: {ver}\n"
    "Summary: Virtual package provided by onnxruntime-gpu\n", encoding="utf-8")
(distinfo / "top_level.txt").write_text("", encoding="utf-8")
(distinfo / "RECORD").write_text("METADATA,,\ntop_level.txt,,\nRECORD,,\n", encoding="utf-8")
print(f"onnxruntime virtual stub OK ({ver})")
PY
        if ! stream "$VPY" "$stub_py"; then
            write_warn "onnxruntime 虚拟桩创建失败（pip check 会警告 onnxruntime 缺失，不影响运行）"
        fi
        rm -f "$stub_py"
        write_ok "onnxruntime-gpu + 桩就绪"
    else
        write_info "aarch64：安装 onnxruntime CPU 版（无 GPU wheel，人脸/车牌走 CPU）..."
        without_proxy
        if ! stream "$VPY" -m pip install onnxruntime; then
            write_warn "onnxruntime CPU 安装失败（人脸/车牌会不可用，可稍后手动 pip install onnxruntime）"
        fi
        write_ok "onnxruntime CPU 就绪"
    fi

    # accelerate（embedder device_map 必需）+ lap（BoT-SORT）
    if ! stream "$VPY" -m pip install accelerate lap; then error "accelerate/lap 安装失败"; fi
    write_ok "accelerate + lap 已安装"

    # 桌面启动器依赖（pywebview；Linux 需 GTK/WebKit2 系统库，仅桌面启动器需要，失败可忽略）
    if command -v apt-get >/dev/null 2>&1; then
        if ! "$VPY" -c "import webview" >/dev/null 2>&1; then
            write_info "安装桌面启动器依赖（pywebview + GTK/WebKit2 系统库，可选）..."
            if ! stream $SUDO apt-get install -y libgtk-3-dev libwebkit2gtk-4.1-dev; then
                write_warn "GTK/WebKit2 安装失败（仅桌面启动器需要；纯后端/浏览器开发可忽略）"
            fi
            if ! stream "$VPY" -m pip install -r "$ROOT/desktop/requirements.txt"; then
                write_warn "pywebview 安装失败（仅桌面启动器需要，可忽略）"
            fi
        else
            write_ok "pywebview 已就绪"
        fi
    fi
fi

# ═══════════════════════════════════════════════════════════
# 6. 模型下载（embedding 国内源直连 / yolo+reid+face 走代理）
# ═══════════════════════════════════════════════════════════
write_step 6 10 "模型准备"
if [[ "$SKIP_MODELS" == "1" ]]; then write_info "已跳过（--skip-models）"; else
    dlpy="$ROOT/deploy/download_models.py"
    # 国内源直连组件：embedding + plate + segmenter
    write_info "下载国内源模型（embedding / plate / segmenter）..."
    without_proxy
    if ! stream "$VPY" "$dlpy" --component embedding --component plate --component segmenter \
            --model-root "$ROOT/models" --retries "$RETRIES"; then
        write_warn "国内源下载失败，带代理重试..."
        with_proxy
        if ! stream "$VPY" "$dlpy" --component embedding --component plate --component segmenter \
                --model-root "$ROOT/models" --retries "$RETRIES"; then
            without_proxy
            error "国内源模型下载失败（见上方实时输出）"
        fi
        without_proxy
    fi
    # 代理组件：yolo + reid + face（GitHub 源 / 库自带）
    write_info "下载 GitHub 源模型（yolo / reid / face，走代理）..."
    with_proxy
    if ! stream "$VPY" "$dlpy" --component yolo --component reid --component face \
            --model-root "$ROOT/models" --retries "$RETRIES"; then
        without_proxy
        error "GitHub 源模型下载失败（检查代理，见上方实时输出）"
    fi
    without_proxy
    write_ok "全部模型就绪"
fi

# ═══════════════════════════════════════════════════════════
# 7. 数据库 + Docker（缺失时装 docker.io）
# ═══════════════════════════════════════════════════════════
write_step 7 10 "数据库（PostgreSQL + pgvector）"
if [[ "$SKIP_DOCKER" == "1" ]]; then write_info "已跳过（--skip-docker）"; else
    if ! docker info >/dev/null 2>&1; then
        write_warn "Docker 引擎未就绪，尝试安装 docker.io ..."
        if command -v apt-get >/dev/null 2>&1; then
            if ! stream $SUDO apt-get install -y docker.io; then
                write_warn "docker.io 安装失败——请手动安装 Docker 引擎后重跑本脚本"
                write_warn "（开发机需能跑 docker compose up -d db 提供 PostgreSQL+pgvector）"
            else
                $SUDO systemctl enable --now docker 2>/dev/null || true
                sleep 3
            fi
        fi
    fi
    if docker info >/dev/null 2>&1; then
        write_ok "Docker 引擎就绪"
        write_info "启动数据库容器（pgvector/pg17）..."
        # compose 拉镜像是 daemon 行为，不走本脚本的 HTTP_PROXY；被墙时给提示
        if ! stream docker compose -f "$ROOT/docker-compose.yaml" up -d db; then
            write_warn "docker compose up -d db 失败（拉镜像可能需要 Docker daemon 代理，见 docker 文档；可稍后手动重跑）"
        else
            st=""
            for _ in $(seq 1 24); do
                st="$(docker inspect --format '{{.State.Health.Status}}' zhiying_postgres 2>/dev/null || true)"
                [[ "$st" == "healthy" ]] && break
                sleep 5
            done
            if [[ "$st" == "healthy" ]]; then
                write_ok "数据库容器 healthy"
            else
                write_warn "数据库未在超时内 healthy（当前: ${st:-未知}）——可稍后手动 docker compose up -d db"
            fi
        fi
    else
        write_warn "Docker 不可用，跳过数据库启动（装好 docker 后手动 docker compose up -d db）"
    fi
fi

# ═══════════════════════════════════════════════════════════
# 8. 前端构建（Node + 前端 dist）：桌面启动器 + 后端静态托管都需要
# ═══════════════════════════════════════════════════════════
write_step 8 10 "前端构建（Node + 前端 dist）"
if [[ "$SKIP_FRONTEND" == "1" ]]; then write_info "已跳过（--skip-frontend）"; else
    node_major="$(node -v 2>/dev/null | sed 's/^v//;s/\..*//')"
    if ! command -v node >/dev/null 2>&1 || [[ "${node_major:-0}" -lt 20 ]]; then
        write_info "Node.js 缺失或过旧（${node_major:-无}），通过 NodeSource 安装 v22（走代理）..."
        with_proxy
        if ! stream bash -c "curl -fsSL https://deb.nodesource.com/setup_22.x | $SUDO -E bash -"; then
            without_proxy
            write_warn "NodeSource 安装失败（网络/代理问题）——请手动安装 node≥20 后重跑本脚本（或 --skip-frontend）"
        elif ! stream $SUDO apt-get install -y nodejs; then
            without_proxy
            write_warn "nodejs 安装失败——请手动安装 node≥20 后重跑（或 --skip-frontend）"
        else
            without_proxy
            write_ok "Node.js 已安装"
        fi
        without_proxy
    else
        write_ok "Node.js: $(node -v)"
    fi

    if command -v node >/dev/null 2>&1; then
        for fe in frontend-desktop frontend; do
            fe_dir="$ROOT/$fe"
            if [[ ! -f "$fe_dir/package.json" ]]; then write_warn "$fe 无 package.json，跳过构建"; continue; fi
            write_info "构建 $fe ..."
            without_proxy
            if ! (cd "$fe_dir" && npm install --registry=https://registry.npmmirror.com --no-audit --no-fund >/dev/null 2>&1); then
                write_warn "$fe npm install 失败——跳过（可 cd $fe && npm install 手动排障）"
                continue
            fi
            if ! (cd "$fe_dir" && npm run build >/dev/null 2>&1); then
                write_warn "$fe npm run build 失败——跳过（可 cd $fe && npm run build 手动排障）"
                continue
            fi
            if [[ -f "$fe_dir/dist/index.html" ]]; then write_ok "$fe/dist 构建完成"; else write_warn "$fe build 结束但未生成 dist/index.html"; fi
        done
    fi
fi

# ═══════════════════════════════════════════════════════════
# 9. 校验
# ═══════════════════════════════════════════════════════════
write_step 9 10 "校验"
if [[ "$SKIP_MODELS" != "1" ]]; then
    write_info "校验模型 ..."
    if ! stream "$VPY" "$ROOT/deploy/download_models.py" --component all --model-root "$ROOT/models" --verify-only; then
        error "模型校验失败（缺失模型；可 --skip-models 跳过重跑）"
    fi
    write_ok "模型校验通过"
fi
"$VPY" -c "import torch;print('torch',torch.__version__,'cuda',torch.cuda.is_available())" 2>/dev/null | sed 's/^/  /' || true
"$VPY" -c "import fastapi,uvicorn;print('fastapi',fastapi.__version__)" 2>/dev/null | sed 's/^/  /' || true

# ═══════════════════════════════════════════════════════════
# 10. 完成：启动指令
# ═══════════════════════════════════════════════════════════
write_step 10 10 "完成"
echo ""
echo -e "  ${C_GRN}✅ 环境安装完成。以下服务由你自己启动：${C_OFF}"
echo ""
echo "  【0】桌面端（装完即用，推荐）"
echo -e "  ${C_DIM}      .venv/bin/python desktop/app.py${C_OFF}"
echo ""
echo "  【1】数据库（PostgreSQL + pgvector）"
echo -e "  ${C_DIM}      docker compose up -d db${C_OFF}"
echo -e "  ${C_DIM}      等待 healthy：docker inspect --format '{{.State.Health.Status}}' zhiying_postgres${C_OFF}"
echo ""
echo "  【2】后端"
echo -e "  ${C_DIM}      .venv/bin/python run.py     # 读 config.yaml server 段（默认 8011）${C_OFF}"
echo -e "  ${C_DIM}      健康检查：curl http://127.0.0.1:8011/health${C_OFF}"
echo ""
echo "  【3】前端（开发态，可选）"
echo -e "  ${C_DIM}      cd frontend && npm run dev  # 或 frontend-desktop${C_OFF}"
echo ""
echo "  【4】API key（可选但推荐）"
echo -e "  ${C_DIM}      前端 → 设置页 → 系统设置，填 DashScope + DeepSeek key（保存即生效）${C_OFF}"
echo ""
