#!/usr/bin/env bash
# 配置项（根据需要修改）
PROJECT_NAME="aduib-mcp-router"
REPO_URL="https://github.com/chaorenex1/aduib-mcp-router.git"
BRANCH="main"
CONTAINER_NAME="${PROJECT_NAME}-app"
BASE_IMAGE_NAME="aduib-ai-base"
IMAGE_NAME="${PROJECT_NAME}"
cd ".."
WORK_DIR=$(pwd)

LOG_HOST_DIR="${WORK_DIR}/logs"
PORT=5004
EXPOSED_PORT=5004
RPC_PORT=5005
RPC_EXPOSED_PORT=5005

# 颜色输出（可选）
GREEN="\033[0;32m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
NC="\033[0m"

log() { echo -e "${GREEN}[INFO]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err() { echo -e "${RED}[ERROR]${NC} $*"; }

#trap 'err "部署失败"; exit 1' ERR

log "开始部署 ${PROJECT_NAME}"

# 克隆或更新代码
if [ -d ".git" ]; then
  log "仓库已存在，拉取远端 ${BRANCH}"
  git fetch origin "${BRANCH}"
  git checkout "${BRANCH}"
  git reset --hard "origin/${BRANCH}"
  git clean -fd
else
  log "克隆仓库 ${REPO_URL}"
  rm -rf ./*
  git clone --branch "${BRANCH}" "${REPO_URL}" .
fi

# 停止并删除旧容器（如果存在）
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  log "停止并移除旧容器 ${CONTAINER_NAME}"
  docker stop "${CONTAINER_NAME}" || true
  docker rm "${CONTAINER_NAME}" || true
else
  log "未找到名为 ${CONTAINER_NAME} 的容器"
fi

# 获取当前提交短哈希作为镜像标签
GIT_SHA=$(git rev-parse --short HEAD)

IMAGE_TAG="${IMAGE_NAME}:${GIT_SHA}"
LAST_IMAGE_TAG="${IMAGE_NAME}"
# 删除所有旧镜像
OLD_IMAGES=$(docker images --format '{{.Repository}}:{{.Tag}}' | grep "^${LAST_IMAGE_TAG}:")
if [ -n "$OLD_IMAGES" ]; then
  log "发现旧镜像，开始删除："
  echo "$OLD_IMAGES" | xargs -r docker rmi || true
else
  log "未找到旧镜像"
fi
log "当前提交 ${GIT_SHA}，镜像标签 ${IMAGE_TAG}"

# 构建新镜像
log "构建镜像 ${IMAGE_TAG}"
docker build -t "${IMAGE_TAG}" -f ./deploy/Dockerfile .

# 创建日志目录（宿主机）
mkdir -p "${LOG_HOST_DIR}"

# 运行新容器
log "启动容器 ${CONTAINER_NAME}"
docker run -d \
  --env-file ${WORK_DIR}/aduib_mcp_router/.env.production \
  --name "${CONTAINER_NAME}" \
  --restart unless-stopped \
  -p "${PORT}:${EXPOSED_PORT}" \
  -p "${RPC_PORT}:${RPC_EXPOSED_PORT}" \
  -v "${LOG_HOST_DIR}:/app/logs" \
  -v "/home/zzh/.aduib_ai:/root/.aduib_ai" \
  -v "/home/zzh/.aduib_mcp_router:/root/.aduib_mcp_router" \
  -v "/home/zzh/.cache:/root/.cache" \
  "${IMAGE_TAG}"

# 等待并检查容器状态
sleep 5
if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  log "容器 ${CONTAINER_NAME} 启动成功，映射端口 ${PORT}"
  log "访问地址: http://localhost:${PORT}"
  log "最近容器日志："
  docker logs --tail 20 "${CONTAINER_NAME}" || true
else
  err "容器启动失败，查看完整日志："
  docker logs "${CONTAINER_NAME}" || true
  exit 1
fi

log "部署完成：镜像=${IMAGE_TAG} 容器=${CONTAINER_NAME} 工作目录=${WORK_DIR}"