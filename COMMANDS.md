# HKG Flight Data v3 - 命令参考

## 快速参考

### CLI 查询命令

```bash
# 查询航班（默认排除代码共享）
python -m hkg_flight query <航班号> [日期]
python -m hkg_flight query CX759              # 紧凑单行输出
python -m hkg_flight query CX759 --details   # 完整航班信息
python -m hkg_flight query CX759 2026-09-07
python -m hkg_flight query BA15       # 短航班号按航班号匹配
python -m hkg_flight query W63        # 查询停机位

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
# 终端工作台（默认，auto 后端：优先增强界面，否则 plain）
python -m hkg_flight
python -m hkg_flight tui

# 明确指定后端
python -m hkg_flight tui --ui textual   # 要求增强界面（缺失则非零退出）
python -m hkg_flight tui --ui plain     # 标准库行命令降级

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
| `--force` | 本次运行绕过航司缓存读取，不删除缓存文件 |
| `--help`, `-h` | 显示帮助信息 |

### 子命令选项

**query:**
| 选项 | 说明 |
|------|------|
| `flight` | 航班号（必填） |
| `date` | 日期 YYYY-MM-DD（可选，默认今天；22:00–01:59 HKT 跨午夜时含相邻日） |
| `--codeshare` | 包含代码共享航班 |

**web / tui:**
| 选项 | 说明 |
|------|------|
| `--port`, `-p` | Web 服务器端口（默认：8080） |
| `--no-poll` | 禁用后台轮询（仅 tui） |
| `--ui` | 终端后端：`auto`（默认）、`textual`、`plain`（仅 tui） |

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
# 绕过航司缓存并显示离境航班
python -m hkg_flight --force departures

# 绕过航司缓存并查询航班
python -m hkg_flight --force query CX759

# 绕过航司缓存并启动 Web 服务器（注意：--force 是全局选项，须写在子命令之前）
python -m hkg_flight --force web
```

注意：`--force` 是全局选项，必须写在子命令之前（`--force web`，而非 `web --force`）。
`--force` 只对本次运行绕过航司缓存读取；航班请求本身直接访问 API，轮询失败时仍可使用航班缓存。它不会删除缓存文件（包括 alerts.json 告警历史）。

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
  --force               Bypass cached airline data for this run
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

---

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `HKG_CACHE_DIR` | 缓存目录 | `~/.hkg_flight_cache` |
| `HKG_WEB_PORT` | Web 服务器端口 | `8080` |

---

## TUI 界面操作

启动后为四页工作台（离港 / 到达 / 告警 / 航司）+ 详情 + 帮助。

**常用按键**：

| 按键 | 功能 |
|------|------|
| `1` / `2` / `5` / `6` | 离港 / 到达 / 告警 / 航司 |
| `/` | 进入当前页搜索 |
| `Enter` | 打开详情；航司页应用筛选并返回航班页 |
| `Esc` | 关面板 → 清筛选 → 辅助页返回最近航班页 |
| `↑` `↓` `PgUp` `PgDn` `Home` `End` | 移动选择与滚动 |
| `Tab` / `Shift+Tab` | 焦点轮转 |
| `f` / `r` / `w` / `?` / `q` | 筛选 / 刷新 / Web 开关 / 帮助 / 退出 |
| `Ctrl+Q` / `Ctrl+C` | 全局退出（输入态用 `Ctrl+Q`） |

搜索框获得焦点时，数字、`W`、`Q` 等均为普通文本，不切页、不开关 Web、不退出。

## Plain 降级

无增强界面或非交互输出时，plain 后端按“一行一个命令”工作：
`1/2/5/6`、`n`/`p`、`/ 搜索词`、`detail 序号`、`r`、`w`、`help`、`q`。
非 TTY 仅输出默认页的有限快照后退出；失败无数据时返回非零状态。

---

## 搜索逻辑

搜索范围（按香港时间 HKT）：

| 时间段 | 搜索范围 |
|--------|----------|
| 指定日期 | 仅该日期 |
| 02:00-21:59 | 仅今天 |
| 22:00-23:59 | 今天 + 明天 |
| 00:00-01:59 | 昨天 + 今天 |

匹配方式：

| 输入 | 匹配方式 |
|------|----------|
| `query 888` | 主航班号包含 "888" |
| `query CX888` | 主航班号包含 "CX888" |
| `query CX888 --codeshare` | 主航班号或代码共享包含 "CX888" |
| `query BA15` | 短航班号按主航班号匹配，不会误判为停机位 |
| `query W63` | 按 HKIA 停机位精确匹配（支持 W/N/R/S/E/D/X 前缀） |
| `query CX888 2026-09-07` | 主航班号包含 "CX888"，仅该日期 |
| `query CX` | 航空公司代码（2 字母）：主航班号前缀匹配（如 CX759） |
| `query CX --codeshare` | 航司代码前缀 + 搭载该代码的代码共享航班（如 BR258 带 CX4446） |

---

## 查询结果分页

当查询为航空公司代码（如 `query CX`）或结果超过 10 条时，以紧凑列表分页显示，**每页默认 10 条**：

| 按键 | 功能 |
|------|------|
| `Enter` / `n` | 下一页 |
| `p` | 上一页 |
| 数字（如 `3`） | 跳转到第 3 页 |
| `q` | 退出分页器 |

默认查询使用紧凑的单行表格；例如 `query CX759` 只显示一行航班摘要。
需要完整字段时使用 `query CX759 --details` 或 `query CX759 -d`。

---

## 系统要求

- **Python**: 3.9 或更高版本
- **依赖**: 基础包无第三方依赖
- **增强终端界面**: `.[tui]` 可选安装组（引入 Textual）
  ```bash
  pip install "hkg-flight-data[tui]"
  ```
