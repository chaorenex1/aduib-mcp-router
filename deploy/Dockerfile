# dockerfile
FROM aduib-ai-base:latest

# 基本设置
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV TZ=Asia/Shanghai
ENV DOCKER_ENV=true
ENV APP_HOST=10.0.0.96
WORKDIR /app

# 先复制依赖描述文件以利用缓存
# COPY pyproject.toml uv.lock* .env.production ./
# 复制项目源码
COPY . .

# 安装 uv 包管理器并使用 uv 安装依赖（只安装非 dev 依赖）
RUN  pip install uv \
    && uv venv \
    && uv sync --frozen --no-dev

ENTRYPOINT [".venv/bin/python", "-m", "aduib_mcp_router"]