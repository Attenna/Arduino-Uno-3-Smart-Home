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

# The repository excludes runtime state and credentials, so overlaying PC_Test
# updates source files while preserving data, models, .env and .auth files.
cp -a "$REPO_DIR/PC_Test/." "$RUNTIME_DIR/"
printf '%s\n' "$commit" > "$RUNTIME_DIR/.deployed-git-commit"

cd "$RUNTIME_DIR"
docker compose up -d --build
docker compose ps
curl --fail --silent --show-error --max-time 10 \
  http://127.0.0.1:5000/api/ready
printf '\nAnonymous hardware API status: '
curl --silent --output /dev/null --write-out '%{http_code}\n' \
  http://127.0.0.1:5000/api/hardware/tools
printf '\nDeployed %s\n' "$commit"
