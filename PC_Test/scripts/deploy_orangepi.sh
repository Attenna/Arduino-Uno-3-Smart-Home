#!/usr/bin/env bash
# =============================================================================
# deploy_orangepi.sh —— 香橙派（arm64 Linux）Docker 部署自检 / 引导脚本
#
# 在香橙派的 PC_Test 目录下运行：
#   bash scripts/deploy_orangepi.sh                 # 只检查并给出指引
#   bash scripts/deploy_orangepi.sh --install-docker  # 顺便安装 Docker（需 sudo）
#   bash scripts/deploy_orangepi.sh --gen-env         # 按探测结果自动生成 .env
#
# 不修改系统（除 --install-docker 外）；检测结果和下一步命令直接打印。
# =============================================================================
set -u

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[X]${NC} $*"; }

INSTALL_DOCKER=0; GEN_ENV=0
for arg in "$@"; do
  case "$arg" in
    --install-docker) INSTALL_DOCKER=1 ;;
    --gen-env)        GEN_ENV=1 ;;
    *) echo "未知参数: $arg"; exit 2 ;;
  esac
done

# 必须在 PC_Test 根目录（有 docker-compose.yml）运行
if [ ! -f docker-compose.yml ]; then
  err "未找到 docker-compose.yml，请在 PC_Test 目录内运行本脚本。"
  exit 1
fi

echo "================ 1. 系统架构 ================"
ARCH="$(uname -m)"
echo "架构: $ARCH / 内核: $(uname -r)"
case "$ARCH" in
  aarch64|arm64) ok "arm64，与镜像架构匹配（香橙派 3/4/5 系列官方 Ubuntu 都是 arm64）" ;;
  armv7l|armhf)
    err "当前是 32 位 armhf 系统，Dockerfile 基于 python:3.12-slim 仅提供 arm64 镜像。"
    err "请改装 64 位系统（OrangePi 官网的 Ubuntu arm64 / Debian arm64 镜像）。"
    exit 1 ;;
  x86_64) warn "当前是 x86_64（不是香橙派？仍可部署，但与本文场景不同）" ;;
  *) warn "未识别的架构 $ARCH，继续但请自行确认" ;;
esac

echo "================ 2. Docker ================"
if ! command -v docker >/dev/null 2>&1; then
  warn "未安装 Docker。"
  if [ "$INSTALL_DOCKER" -eq 1 ]; then
    echo ">>> 使用官方脚本安装 Docker Engine + Compose 插件 ..."
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker "$USER"
    ok "Docker 已安装。需要重新登录（或 newgrp docker）后再运行本脚本。"
    exit 0
  fi
  echo "    一键安装（重新登录后再运行本脚本）："
  echo "      curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker \$USER"
else
  ok "docker $(docker --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
  if docker compose version >/dev/null 2>&1; then
    ok "compose 插件: $(docker compose version --short)"
  else
    err "缺少 docker compose 插件（v2）。安装：sudo apt-get install -y docker-compose-plugin"
  fi
  if docker info >/dev/null 2>&1; then
    ok "当前用户可访问 docker（无需 sudo）"
  else
    warn "当前用户无权访问 docker。执行： sudo usermod -aG docker \$USER 然后重新登录"
  fi
fi

echo "================ 3. 外设探测 ================"
# ---- 串口（Arduino A/B 板）----
SERIALS=()
for d in /dev/ttyUSB* /dev/ttyACM*; do
  [ -e "$d" ] && SERIALS+=("$d")
done
if [ ${#SERIALS[@]} -eq 0 ]; then
  warn "未发现 /dev/ttyUSB* 或 /dev/ttyACM*（Arduino 未插？或 CH340 驱动未加载）"
else
  ok "发现 ${#SERIALS[@]} 个串口设备："
  i=0
  for d in "${SERIALS[@]}"; do
    byid="$(ls -l /dev/serial/by-id/* 2>/dev/null | grep -oE "/dev/tty[A-Za-z0-9]+$" | grep -x "$d" >/dev/null && echo yes || echo no)"
    echo "    [$i] $d"
    # udev 型号（没有 udevadm 时静默跳过）
    model="$(udevadm info -q property -n "$d" 2>/dev/null | grep -E '^ID_MODEL=' | cut -d= -f2)"
    [ -n "$model" ] && echo "        型号: $model"
    i=$((i+1))
  done
  # 稳定的 by-id 路径（重启不变，推荐写进 .env）
  if ls /dev/serial/by-id/* >/dev/null 2>&1; then
    echo "    稳定路径（推荐用于 .env，插拔顺序变化不受影响）："
    for b in /dev/serial/by-id/*; do echo "        $b -> $(readlink -f "$b")"; done
  fi
  [ ${#SERIALS[@]} -lt 2 ] && warn "只发现 1 个串口，但系统需要 A/B 两块板。请确认两块 Uno 都已插好。"
fi

# ---- USB 摄像头 ----
if ls /dev/video* >/dev/null 2>&1; then
  ok "摄像头设备: $(ls /dev/video* | tr '\n' ' ')"
  command -v v4l2-ctl >/dev/null 2>&1 && v4l2-ctl --list-devices 2>/dev/null | head -8
else
  warn "未发现 /dev/video*（USB 摄像头未插；不影响其它服务，可先不起 camera）"
fi

# ---- 声卡（麦克风/扬声器）----
if [ -d /dev/snd ]; then
  ok "ALSA 声卡存在: /dev/snd"
  command -v arecord >/dev/null 2>&1 && arecord -l 2>/dev/null | grep -E '^card|设备|device' | head -4
else
  warn "未发现 /dev/snd（无音频设备；语音对话不可用，但 web 硬件网关 /api/hardware/tool 正常）"
fi

echo "================ 4. 模型文件 ================"
need=(
  "models/qwen/qwen2.5-3b-instruct-q4_k_m.gguf:本地 LLM（约 2GB；用硅基流动等云端可不要）"
  "models/face/yolov8n-face.pt:人脸检测"
  "models/face/recognition.onnx:ArcFace 人脸识别（约 174MB）"
  "models/sherpa/kws/tokens.txt:语音唤醒（文件名以实际为准，检查目录）"
)
for entry in "${need[@]}"; do
  f="${entry%%:*}"; desc="${entry#*:}"
  if [ -e "$f" ]; then ok "$f（$desc）"
  else warn "缺失 $f（$desc）"; fi
done
for sub in sherpa/kws sherpa/asr sherpa/tts; do
  if [ -d "models/$sub" ]; then ok "models/$sub/ 存在 ($(ls models/$sub | wc -l) 个文件)"
  else warn "缺失目录 models/$sub/（运行 download_sherpa_models.py）"; fi
done

echo "================ 5. .env 配置 ================"
if [ ! -f .env ]; then
  cp docker/.env.example .env
  ok "已从 docker/.env.example 生成 .env"
  if [ "$GEN_ENV" -eq 1 ] && [ ${#SERIALS[@]} -ge 1 ]; then
    A="${SERIALS[0]}"; B="${SERIALS[1]:-${SERIALS[0]}}"
    sed -i "s|^SERIAL_PORT_A=.*|SERIAL_PORT_A=$A|" .env
    sed -i "s|^SERIAL_PORT_B=.*|SERIAL_PORT_B=$B|" .env
    CAM="$(ls /dev/video* 2>/dev/null | head -1)"
    [ -n "$CAM" ] && sed -i "s|^CAMERA_DEVICE=.*|CAMERA_DEVICE=$CAM|" .env
    ok "已按探测结果写入 .env（串口 A=$A B=$B 摄像头=${CAM:-未填}）"
    [ ${#SERIALS[@]} -lt 2 ] && warn "只有一块板，B 暂时与 A 相同——两块板插齐后请修改 .env"
  else
    echo "    请编辑 .env，把 SERIAL_PORT_A / SERIAL_PORT_B / CAMERA_DEVICE 改为上面探测到的设备。"
    echo "    或直接运行： bash scripts/deploy_orangepi.sh --gen-env 自动填写"
  fi
else
  ok ".env 已存在（保留你的配置，未覆盖）"
fi

echo "================ 完成 ================"
cat <<'EOF'
下一步（在 PC_Test 目录）：
  默认走云端 LLM（推荐香橙派使用，免本地 3B、构建快很多；语音不再抢串口）：
    1. 在 .env 填入 LLM_API_KEY=sk-xxxx（硅基流动 Key；用阿里云百炼则同时把
       LLM_MODE 改成 dashscope、LLM_MODEL 改成 qwen-plus）
    2. sudo docker compose up -d --build
       # web 容器独占 A/B 串口并做硬件网关；voice 纯 HTTP 客户端；qwen 默认不启动

  离线 fallback（无云端 Key，在香橙派本地跑 3B GGUF，首次编译 llama 约 20~40 分钟）：
    sudo docker compose -f docker-compose.yml -f docker-compose.local-llm.yml up -d --build

  首次部署注册人脸（新增人员后同样重跑并重启 web）：
    sudo docker compose exec web python scripts/enroll_faces.py
    sudo docker compose restart web
  查看：
    sudo docker compose ps
    sudo docker compose logs -f web voice
  访问：  http://香橙派IP:5000  仪表盘/人脸/硬件网关 | :8080 摄像头 | :8101 语音控制台
EOF
