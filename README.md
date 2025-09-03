# Aduib MCP Server Template
## 项目简介

本项目为 一个基于 FastAPI 的 MCP 服务端模板，支持多种数据库和缓存后端，具有良好的扩展性和易用性。

## 快速开始
1. 安装环境
    ```bash
    pip install uv
    # Or on macOS
    brew install uv
    # Or on Windows
    choco install uv
    ```
2. 安装依赖
   ```bash
   uv sync --dev
    ```
  
3. 初始化数据库
   ```bash
    uv pip install alembic
    alembic -c ./alembic/alembic.ini revision --autogenerate -m "init table"
    alembic -c ./alembic/alembic.ini upgrade head
   ```
