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

## 配置项

### 环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `MCP_CONFIG_PATH` | - | MCP 服务器配置文件路径（本地路径或远程 URL） |
| `ROUTER_HOME` | `~/.aduib_mcp_router` | 路由器主目录 |

### 缓存配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `MCP_CACHE_TTL` | 300 | 服务器特征缓存有效期（秒） |
| `MCP_CACHE_STALE_TTL` | 600 | 过期缓存仍可用的最大时间（秒） |
| `MCP_ENABLE_AUTO_REFRESH` | true | 是否启用后台自动刷新 |

缓存采用 **Stale-While-Revalidate** 策略：
- 缓存有效期内直接返回缓存数据
- 缓存过期但未超过 stale TTL 时，立即返回旧数据并在后台刷新
- 完全过期后同步刷新

### 健康检查配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `MCP_HEALTH_CHECK_INTERVAL` | 30 | 健康检查间隔（秒） |
| `MCP_HEALTH_CHECK_TIMEOUT` | 10 | 健康检查超时（秒） |
| `MCP_MAX_CONSECUTIVE_FAILURES` | 3 | 连续失败次数阈值 |
| `MCP_AUTO_RECONNECT` | true | 自动重连开关 |
| `MCP_RECONNECT_DELAY` | 5 | 重连延迟（秒） |

### 连接配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `MCP_CONNECTION_TIMEOUT` | 600 | SSE/HTTP 连接超时（秒） |
| `MCP_REFRESH_INTERVAL` | 1800 | 配置刷新间隔（秒） |

## Playground

Playground 是一个内置的可视化调试界面，用于快速体验和验证多 MCP Server 的聚合效果。通过单页交互式工具面板，可以：

- 浏览当前路由器已加载的所有远程工具、资源和提示词
- 查看工具的名称、描述、输入 Schema 等详细信息
- 实时查看各 MCP 服务器的健康状态
- 在界面上直接触发调用，快速验证路由链路是否可用
- 观察返回数据，支持导出执行历史

访问地址：`http://localhost:<port>/playground`

![Playground](docs/playground.png)

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
