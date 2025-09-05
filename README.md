# Aduib MCP Router
## 项目简介

Aduib MCP Router 是一个多MCP聚合路由器，支持多种MCP协议，旨在简化MCP服务器的管理和使用。

## 使用
1. MCP配置
   ```json
   {
    "mcpServers": {
        "aduib-mcp-router":{
            "command": "uvx",
            "args": ["aduib-mcp-router"],
            "env": {
              "MCP_CONFIG_PATH": "./config.json"
            }
        }
      }
   }
   ```
2. json配置
    ```json
    {
        "time": {
            "command": "uvx",
            "args": [
                "mcp-server-time"
            ]
        },
        "aduib_server": {
            "type": "sse",
            "url": "http://10.0.0.169:5002",
            "headers": {
                "Authorization": "Bearer $2b$12$WB2YoxB5CQtPbqN35UDso.of2n7BmDvvQpxmIUdKe2VHO.MAY1u26"
            }
        }
    }
   ```
## 开发
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
