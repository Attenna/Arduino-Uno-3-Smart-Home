#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-/home/HwHiAiUser/Arduino-Uno-3-Smart-Home}"
RUNTIME_DIR="${RUNTIME_DIR:-/home/HwHiAiUser/smart-home}"
REPO_URL="${REPO_URL:-https://github.com/Attenna/Arduino-Uno-3-Smart-Home.git}"
BRANCH="${BRANCH:-main}"
BUNDLE_PATH="${BUNDLE_PATH:-}"

if [ ! -d "$RUNTIME_DIR" ] || [ ! -f "$RUNTIME_DIR/docker-compose.yml" ]; then
  echo "Runtime directory is missing or invalid: $RUNTIME_DIR" >&2
  exit 1
fi

if [ -n "$BUNDLE_PATH" ]; then
  if [ ! -f "$BUNDLE_PATH" ]; then
    echo "Git bundle does not exist: $BUNDLE_PATH" >&2
    exit 1
  fi
  if [ ! -d "$REPO_DIR/.git" ]; then
    git clone --branch "$BRANCH" --single-branch "$BUNDLE_PATH" "$REPO_DIR"
  else
    git -C "$REPO_DIR" fetch "$BUNDLE_PATH" "$BRANCH"
    git -C "$REPO_DIR" checkout "$BRANCH"
    git -C "$REPO_DIR" reset --hard FETCH_HEAD
  fi
  if git -C "$REPO_DIR" remote get-url origin >/dev/null 2>&1; then
    git -C "$REPO_DIR" remote set-url origin "$REPO_URL"
  else
    git -C "$REPO_DIR" remote add origin "$REPO_URL"
  fi
elif [ ! -d "$REPO_DIR/.git" ]; then
  git clone --branch "$BRANCH" --single-branch "$REPO_URL" "$REPO_DIR"
else
  git -C "$REPO_DIR" fetch origin "$BRANCH"
  git -C "$REPO_DIR" checkout "$BRANCH"
  git -C "$REPO_DIR" reset --hard "origin/$BRANCH"
fi

commit="$(git -C "$REPO_DIR" rev-parse HEAD)"
backup="$RUNTIME_DIR/../smart-home-backups/pre-deploy-${commit:0:12}"
mkdir -p "$backup"
cp "$RUNTIME_DIR/docker-compose.yml" "$backup/docker-compose.yml"

# Snapshot SQLite and face/config state before changing application files.  The
# backup helper reads the live runtime tree, never the source checkout.
python3 "$RUNTIME_DIR/scripts/backup_state.py"

# Export exactly the files tracked by this commit.  A long-lived checkout can
# contain ignored runtime files (for example PC_Test/data/smart_home.db); cp -a
# would silently copy those stale files over the persistent runtime volume.
git -C "$REPO_DIR" archive --format=tar "$commit:PC_Test" \
  | tar -xf - -C "$RUNTIME_DIR"
printf '%s\n' "$commit" > "$RUNTIME_DIR/.deployed-git-commit"

cd "$RUNTIME_DIR"
docker compose up -d --build
docker compose ps
# 就绪检查要有等待窗口：容器刚起时 /api/ready 会在启动窗口内短暂 503
# （sensor_fresh / output_fresh 尚未满足），立刻 curl 会把「正在启动」误判成部署失败。
# 这里最多等 90s（每 3s 一次）；窗口内始终不就绪才失败退出，不放宽 /api/ready 本身。
ready_ok=0
for _ in $(seq 1 30); do
  if curl --fail --silent --show-error --max-time 10 \
       http://127.0.0.1:5000/api/ready; then
    ready_ok=1
    break
  fi
  printf '\n/api/ready 尚未就绪，3 秒后重试...\n'
  sleep 3
done
if [ "$ready_ok" -ne 1 ]; then
  echo "readiness check did not pass within 90s" >&2
  exit 1
fi
printf '\nAnonymous hardware API status: '
curl --silent --output /dev/null --write-out '%{http_code}\n' \
  http://127.0.0.1:5000/api/hardware/tools
printf '\nDeployed %s\n' "$commit"
