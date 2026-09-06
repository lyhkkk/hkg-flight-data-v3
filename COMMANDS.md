# HKG Flight Data v3 - 命令参考

## 快速参考

### CLI 查询命令

```bash
# 查询航班（默认排除代码共享）
python -m hkg_flight query <航班号> [日期]
python -m hkg_flight query CX759
python -m hkg_flight query CX759 2026-09-07

# 包含代码共享航班
python -m hkg_flight query <航班号> --codeshare
python -m hkg_flight query 30 --codeshare

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
python -m hkg_flight clear-cache --yes  # 跳过确认
```

### 交互式模式

```bash
# TUI 模式（默认）
python -m hkg_flight
python -m hkg_flight tui

# TUI 模式（禁用后台轮询）
python -m hkg_flight tui --no-poll
```

### Web 服务器

```bash
# 启动 Web 服务器（默认端口 8080）
python -m hkg_flight web

# 指定端口
python -m hkg_flight web --port 9000
python -m hkg_flight web -p 9000
```

---

## 选项说明

| 选项 | 说明 |
|------|------|
| `--cache-dir DIR` | 自定义缓存目录（默认：`~/.hkg_flight_cache`） |
| `--force` | 强制刷新（清除缓存后重新获取） |
| `--help`, `-h` | 显示帮助信息 |

### 子命令选项

**query:**
| 选项 | 说明 |
|------|------|
| `flight` | 航班号（必填） |
| `date` | 日期 YYYY-MM-DD（可选，默认搜索 D-1/D/D+1） |
| `--codeshare` | 包含代码共享航班 |

**web / tui:**
| 选项 | 说明 |
|------|------|
| `--port`, `-p` | Web 服务器端口（默认：8080） |
| `--no-poll` | 禁用后台轮询（仅 tui） |

**clear-cache:**
| 选项 | 说明 |
|------|------|
| `date` | 特定日期（可选，默认全部） |
| `--yes`, `-y` | 跳过确认提示 |

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
python -m hkg_flight web --force
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
HKG Flight Data v3 - Flight information system for Hong Kong International Airport

positional arguments:
  {query,departures,arrivals,alerts,clear-cache,web,tui}
                        Available commands
    query               Search for a flight by number
    departures          List departures
    arrivals            List arrivals
    alerts              Show active alerts
    clear-cache         Clear cached data
    web                 Start web server
    tui                 Start TUI interface

options:
  -h, --help            show this help message and exit
  --cache-dir CACHE_DIR
                        Custom cache directory (default: ~/.hkg_flight_cache)
  --force               Force refresh (clear cache before fetching)
```

---

## Web API 端点

启动 `python -m hkg_flight web` 后：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET | Web UI 界面 |
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

---

## TUI 界面操作

启动后会看到：

```
================================================================================
  HKG Flight Data - 2026-09-07
================================================================================

  Departures — 408 flights | Page 1/21

  TIME   FLIGHT     REG    ROUTE                STATUS             GATE/STAND   TERM
  ---------------------------------------------------------------------------
  00:05  CX261      -      HKG → CDG            Dep 00:08          Gate 64      T1
  00:05  CX880      -      HKG → LAX            Dep 00:00          Gate 32      T1
  ...

  [N]ext [P]revious [1]Departures [2]Arrivals [5]Alerts [6]Airlines [Q]uit
```

**常用按键**：

| 按键 | 功能 |
|------|------|
| `1` | 查看离境航班 |
| `2` | 查看到达航班 |
| `5` | 查看告警 |
| `6` | 查看航空公司 |
| `N` | 下一页 |
| `P` | 上一页 |
| `Q` | 退出 |

---

## 搜索逻辑

| 输入 | 匹配方式 | 搜索范围 |
|------|----------|----------|
| `query 888` | 主航班号包含 "888" | D-1, D, D+1 |
| `query CX888` | 主航班号包含 "CX888" | D-1, D, D+1 |
| `query CX888 --codeshare` | 主航班号或代码共享包含 "CX888" | D-1, D, D+1 |
| `query CX888 2026-09-07` | 主航班号包含 "CX888" | 仅 2026-09-07 |

---

## 系统要求

- **Python**: 3.7 或更高版本
- **依赖**: 无（仅使用 Python 标准库）
- **Windows TUI**: 建议安装 `windows-curses`（可选）
  ```bash
  pip install windows-curses
  ```
