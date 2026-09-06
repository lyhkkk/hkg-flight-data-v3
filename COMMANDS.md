# HKG Flight Data v3 - 命令参考

## 快速参考

### CLI 查询命令

```bash
# 查询航班
python -m hkg_flight query <航班号> [日期]
python -m hkg_flight query CX759
python -m hkg_flight query CX759 2026-09-07

# 今日离境航班
python -m hkg_flight departures
python -m hkg_flight departures 2026-09-07

# 今日到达航班
python -m hkg_flight arrivals
python -m hkg_flight arrivals 2026-09-07

# 查看告警
python -m hkg_flight alerts

# 清除缓存
python -m hkg_flight clear-cache
python -m hkg_flight clear-cache 2026-09-07
```

### 交互式模式

```bash
# TUI 模式（默认）
python -m hkg_flight

# TUI 模式（禁用后台轮询）
python -m hkg_flight --no-poll
```

### Web 服务器

```bash
# 启动 Web 服务器（默认端口 8080）
python -m hkg_flight --web

# 指定端口
python -m hkg_flight --web --port 9000
```

---

## 选项说明

| 选项 | 说明 |
|------|------|
| `--web` | 启动 Web 服务器模式 |
| `--port N` | 指定 Web 服务器端口（默认：8080） |
| `--no-poll` | 禁用后台轮询（仅 TUI 模式） |
| `--force` | 强制刷新（清除缓存后重新获取） |
| `--cache-dir DIR` | 指定自定义缓存目录 |

---

## 关于"强制刷新"

### 当前行为

| 命令 | 数据行为 |
|------|----------|
| `query` | 每次调用 API 获取最新数据 |
| `departures` | 每次调用 API 获取最新数据 |
| `arrivals` | 每次调用 API 获取最新数据 |
| `alerts` | 读取本地缓存（不调用 API） |

### 缓存机制

代码有缓存机制：
- **今日数据**：缓存 5 分钟
- **历史数据**：缓存 24 小时
- **航空公司数据**：缓存 24 小时

### 如何强制刷新

使用 `--force` 选项：

```bash
# 强制刷新并显示离境航班
python -m hkg_flight --force departures

# 强制刷新并查询航班
python -m hkg_flight --force query CX759

# 强制刷新并启动 Web 服务器
python -m hkg_flight --web --force
```

或者清除特定日期的缓存：

```bash
# 清除所有缓存
python -m hkg_flight clear-cache

# 清除特定日期的缓存
python -m hkg_flight clear-cache 2026-09-07
```

---

## 完整命令列表

```
HKG Flight Data v3

Usage:
  python -m hkg_flight                     # Start TUI (default)
  python -m hkg_flight --web [--port N]    # Start web server
  python -m hkg_flight --no-poll           # TUI without live polling
  python -m hkg_flight --force             # Force refresh (ignore cache)

Commands:
  python -m hkg_flight query <flight> [date]
  python -m hkg_flight departures [date]
  python -m hkg_flight arrivals [date]
  python -m hkg_flight alerts
  python -m hkg_flight clear-cache [date]

Options:
  --web           Start web server mode
  --port N        Web server port (default: 8080)
  --no-poll       Disable live polling
  --force         Force refresh (clear cache before fetching)
  --cache-dir DIR Custom cache directory
```

---

## Web API 端点

启动 Web 服务器后，可以使用以下 API：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET | Web UI 页面 |
| `/api/flights?date=YYYY-MM-DD` | GET | 获取航班列表 |
| `/api/search?flight=CX759` | GET | 搜索航班 |
| `/api/alerts` | GET | 获取活跃告警 |
| `/api/stats` | GET | 获取服务器统计 |
| `/api/airlines` | GET | 获取航空公司列表 |
| `/api/stream` | GET | SSE 实时更新流 |

---

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `HKG_CACHE_DIR` | 缓存目录 | `~/.hkg_flight_cache` |
| `HKG_WEB_PORT` | Web 服务器端口 | `8080` |
| `HKG_API_INTERVAL` | API 调用最小间隔（秒） | `0.6` |
