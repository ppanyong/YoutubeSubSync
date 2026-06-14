#!/usr/bin/env bash
#
# YoutubeSubSync 一键安装脚本
# 功能：检测 Python -> 创建虚拟环境 -> 安装依赖 -> 生成 .env -> 启动后端
# 用法：
#   ./install.sh            # 安装并启动后端
#   ./install.sh --no-start # 仅安装，不启动
#
set -euo pipefail

# ---------- 彩色输出 ----------
if [ -t 1 ]; then
  BOLD=$'\033[1m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; BLUE=$'\033[34m'; RESET=$'\033[0m'
else
  BOLD=""; GREEN=""; YELLOW=""; RED=""; BLUE=""; RESET=""
fi
info()  { echo "${BLUE}▶${RESET} $*"; }
ok()    { echo "${GREEN}✔${RESET} $*"; }
warn()  { echo "${YELLOW}⚠${RESET} $*"; }
err()   { echo "${RED}✗${RESET} $*" >&2; }

# ---------- 定位项目目录 ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
VENV_DIR="$BACKEND_DIR/.venv"
ENV_FILE="$BACKEND_DIR/.env"
ENV_EXAMPLE="$BACKEND_DIR/.env.example"

START_BACKEND=1
for arg in "$@"; do
  case "$arg" in
    --no-start) START_BACKEND=0 ;;
    -h|--help)
      echo "用法：./install.sh [--no-start]"
      echo "  --no-start  仅安装依赖与配置，不启动后端"
      exit 0 ;;
    *) warn "忽略未知参数：$arg" ;;
  esac
done

echo "${BOLD}YoutubeSubSync 一键安装${RESET}"
echo "项目目录：$SCRIPT_DIR"
echo

# ---------- 1. 检测 Python（优先 3.12，依次回退）----------
info "检测 Python 解释器…"
PYTHON=""
for cand in python3.12 python3.11 python3.13 python3; do
  if command -v "$cand" >/dev/null 2>&1; then
    PYTHON="$cand"
    break
  fi
done

if [ -z "$PYTHON" ]; then
  err "未找到 Python 3，请先安装 Python 3.11/3.12（推荐 3.12）。"
  echo "  macOS:  brew install python@3.12"
  exit 1
fi

PY_VER="$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
ok "使用 $PYTHON (Python $PY_VER)"
if [ "$PY_VER" != "3.12" ] && [ "$PY_VER" != "3.11" ]; then
  warn "推荐 Python 3.12；当前 $PY_VER 个别依赖可能缺少预编译包，安装较慢或失败。"
  warn "如安装失败，请执行：brew install python@3.12 后重试。"
fi

# ---------- 2. 创建虚拟环境 ----------
if [ -d "$VENV_DIR" ]; then
  ok "虚拟环境已存在，跳过创建：$VENV_DIR"
else
  info "创建虚拟环境：$VENV_DIR"
  "$PYTHON" -m venv "$VENV_DIR"
  ok "虚拟环境已创建"
fi

VENV_PY="$VENV_DIR/bin/python"

# ---------- 3. 安装依赖 ----------
info "升级 pip 并安装依赖…"
"$VENV_PY" -m pip install --quiet --upgrade pip
"$VENV_PY" -m pip install --quiet -r "$BACKEND_DIR/requirements.txt"
ok "依赖安装完成"

# ---------- 4. 生成 .env ----------
if [ -f "$ENV_FILE" ]; then
  ok ".env 已存在，保留现有配置：$ENV_FILE"
else
  cp "$ENV_EXAMPLE" "$ENV_FILE"
  ok "已从 .env.example 生成 .env"
  warn "请填入你的 LLM 配置（也可启动后在网页设置页填写）。"
fi

# ---------- 5. 检查是否已配置 API Key ----------
API_CONFIGURED=0
if grep -qE '^LLM_API_KEY=' "$ENV_FILE" 2>/dev/null; then
  KEY_VAL="$(grep -E '^LLM_API_KEY=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
  case "$KEY_VAL" in
    ""|sk-xxxx*) API_CONFIGURED=0 ;;
    *) API_CONFIGURED=1 ;;
  esac
fi

echo
ok "${BOLD}安装完成！${RESET}"
echo
echo "${BOLD}下一步：${RESET}"
echo "  1. 加载扩展：Chrome/Edge 打开 ${BLUE}chrome://extensions${RESET} → 开启开发者模式"
echo "     → 「加载已解压的扩展程序」→ 选择 ${BOLD}$SCRIPT_DIR/extension${RESET}"
echo "  2. 打开 YouTube 视频，按 ${BOLD}Alt+Shift+Y${RESET} 开启中文字幕"
if [ "$API_CONFIGURED" -eq 0 ]; then
  echo
  warn "尚未配置 LLM API Key —— 后端启动后请打开 ${BLUE}http://127.0.0.1:8000/${RESET} 在设置页填写。"
  warn "推荐：硅基流动 tencent/Hunyuan-MT-7B（目前限免，不产生成本）。"
fi
echo

# ---------- 6. 启动后端 ----------
if [ "$START_BACKEND" -eq 1 ]; then
  info "启动后端：http://127.0.0.1:8000  （Ctrl+C 停止）"
  echo
  cd "$BACKEND_DIR"
  exec "$VENV_PY" main.py
else
  echo "${BOLD}手动启动后端：${RESET}"
  echo "  cd backend && .venv/bin/python main.py"
fi
