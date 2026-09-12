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

# 查看门/廊桥变动（首次分配不告警，仅 release / change 告警）
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
| `date` | 日期 YYYY-MM-DD（可选，默认看板窗口；22:00–01:59 HKT 跨午夜时含相邻日） |
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

### 告警规则

告警只标记"**偏离最初分配**"的门/廊桥。首次分配是基线，不算变化——每个正常航班都会分到机位，若为此告警，一天会产生几百条噪音：

```
N24 -> -         释放（机位被收回）      → 告警
N24 -> S47       改到其他机位            → 告警
N24 -> - -> S47  释放后重新分配          → 告警，显示为 N24 -> S47
-   -> N24       首次分配                → 不告警
N24 -> S47 -> N24  回到原机位            → 清除该告警
```

告警始终显示"原始分配 → 当前值"。航班起飞 / 降落 / 取消后，其告警自动清除。

### 缓存机制

- **航班数据**：无 TTL。每次请求都直接访问 API，成功结果写穿到 `flights_YYYY-MM-DD.json`；API 失败时由轮询器回退读取该文件。
- **航空公司数据**：缓存 24 小时（`--force` 可绕过）。
- **告警**：写入 `alerts.json`（最新在前，上限 500，仅保留看板窗口内的日期）。

轮询每轮取一次时钟，按窗口规则决定要抓 1 天还是 2 天，把结果合并成同一张看板。
两种情况都不会被当成"完全成功"：**窗口里只要有一天来自缓存**，整轮来源标记为 `cache`
（一半实时一半记忆不能自称实时）；**某一天抓取失败**时，另一天照常发布并记录错误
（半张看板好过空看板，失败在表头和退出码里可见）。

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
`--force` 只对本次运行绕过航司缓存读取；航班请求本身直接访问 API，轮询失败时仍可使用航班缓存。它不会删除缓存文件（包括 alerts.json 告警列表）。

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
    alerts              Show gate/stand changes away from the original assignment
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
| `/api/flights?date=YYYY-MM-DD` | GET | 获取航班列表；不带 `date` 时返回整个看板窗口（按日期升序） |
| `/api/search?flight=CX759` | GET | 搜索航班 |
| `/api/alerts` | GET | 获取门/廊桥变动（按时间倒序） |
| `/api/stats` | GET | 获取数据源健康状态（来源 / 日期窗口 / 航班与告警数量 / HKT 时钟） |
| `/api/airlines` | GET | 获取航空公司列表 |

不带 `date` 的 `/api/flights` 返回**整个看板窗口**并**按日期升序**。顺序是契约的一部分：
前端按行序扫描来定位锚点，乱序会让它停在错误的日期上。

### 仪表盘的时间锚点

航班表打开时停在**当前 HKT 航班**上，和终端工作台一致。时钟由服务端下发
（`hkt_now` / `hkt_minutes` / `hkt_date`），因为看板是香港的，"现在"不能取浏览器所在时区。
`/api/stats` 还带 `dates`（服务端正在提供的窗口），页面用它标注跨度（`2026-09-12 +1`）。

| 控件 | 功能 |
|------|------|
| `◀` / `▶` | 从当前锚点向前 / 向后翻一屏 |
| `Now` | 重新跟随 HKT 时钟 |
| 标签 `Now HH:MM` / `Pinned HH:MM` | 列表是否仍在跟随时钟；锚点不在看板自身日期上时会带日期（`Pinned 09-13 01:30`） |

手动滚动或用 `◀`/`▶` 翻页即视为接管，锚点固定；此后每 30 秒的自动刷新不再把列表拽回
"现在"。按 `Now` 交还控制权。

---

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `NO_COLOR` | 设置后禁用彩色输出（终端工作台） | 未设置（即启用颜色） |

缓存目录用 `--cache-dir`，Web 端口用 `web --port` / `tui --port`，均无环境变量开关。

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
| `[` / `]` | 从当前锚点向前 / 向后翻一屏（整屏行数） |
| `t` | 重新跟随 HKT 时钟（锚点回到"现在"） |
| `Tab` / `Shift+Tab` | 焦点轮转 |
| `f` / `r` / `w` / `?` / `q` | 筛选 / 刷新 / Web 开关 / 帮助 / 退出 |
| `Ctrl+Q` / `Ctrl+C` | 全局退出（输入态用 `Ctrl+Q`） |

搜索框获得焦点时，数字、`W`、`Q`、`[`、`]`、`t` 等均为普通文本，不切页、不翻页、不开关 Web、不退出。

### 时间锚点

离港 / 到达页打开时停在**当前 HKT 航班**上（第一条时间 ≥ 现在的航班）。搜索行左侧显示
`Now HH:MM`，说明列表仍跟着时钟走：每次刷新落地都会重新锚定。

锚点是**服务日期 + 时刻**，不只是时刻。跨午夜时看板同时带着两天的航班（见下节），
单凭 `01:30` 会指向两个不同的航班；只看时刻会把视口停在**昨天**的 01:30 上。
行本身不带日期时，视为属于正在锚定的那一天。

一旦手动移动（`↑`/`↓`/`PgUp`/`PgDn`/`Home`/`End`）或用 `[`/`]` 翻页，锚点就被**固定**，
标签变成 `Pinned HH:MM`，之后的刷新不再把列表拽回"现在"；按 `t` 交还控制权。
锚点不在看板自身日期上时，标签会带上日期：`Pinned 09-13 01:30`——"Pinned 01:30" 说不清是哪一晚。
表头则显示跨度 `Data date 2026-09-12 +1`，看板跨两天时不会看起来只装了一天。

`[`/`]` 的步长是**当前一屏能显示的行数**，所以下一屏从上一屏结束的地方接着开始，不会漏航班。
当天航班全部飞完时，列表停在末尾而不是显示空屏。

## Plain 降级

无增强界面或非交互输出时，plain 后端按“一行一个命令”工作：
`1/2/5/6`、`n`/`p`、`/ 搜索词`、`detail 序号`、`r`、`w`、`help`、`q`。
非 TTY 仅输出默认页的有限快照后退出；失败无数据时返回非零状态。

---

## 搜索逻辑

搜索范围（按香港时间 HKT）。这张表就是**看板窗口规则**本身，`query` 与看板共用同一个实现
（`utils.board_dates`），不会各算各的：

| 时间段 | 搜索范围 |
|--------|----------|
| 指定日期 | 仅该日期 |
| 02:00-21:59 | 仅今天 |
| 22:00-23:59 | 今天 + 明天 |
| 00:00-01:59 | 昨天 + 今天 |

服务日期从午夜开始，但一天的飞行不是：夜里最后几班在 00:00 之后才走，清晨最早的几班
在 02:00 之前就落地。只看"今天"会同时丢掉这两头，所以跨午夜时窗口带上相邻的那一天。
窗口永远包含今天，永远不超出一天之外，并且始终按日期升序。

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

## 输出宽度自适应

输出宽度跟随真实终端（识别 `COLUMNS` 环境变量），**任何一行都不会超过终端宽度**，
因此 shell 不会在值中间折行（例如把 `G30` 拆成 `G` 和 `30` 落到下一行）：

- **≥ 80 列**：每条航班一行，带列标题。
- **< 80 列**（手机宽度）：去掉列标题，每条航班拆成两行，
  字段顺序与单行一致（第一行：时间 / 航班号 / 状态；第二行：航线 / 闸口·机位 / 航站楼）。

`departures` / `arrivals` / `alerts` 与 plain 模式同样遵守该规则。
标题、分页脚注和 `--codeshare` 提示按「阶梯」降级：能放下的最长写法优先，
放不下就换短写法，全都放不下就整条不输出。
plain 后端没有第二行可以溢出，所以它的表头（`HKG | Data date …`，跨午夜时多出 ` +1`）
和页标题（含用户输入的搜索词）按宽度直接截断——截断只是难看，折行会拆散整张表。

---

## 查询结果分页

当查询为航空公司代码（如 `query CX`）或结果超过 10 条时，以紧凑列表分页显示，**每页默认 10 条**：

| 按键 | 功能 |
|------|------|
| `Enter` / `n` | 下一页 |
| `p` | 上一页 |
| 数字（如 `3`） | 跳转到第 3 页 |
| `q` | 退出分页器 |

默认查询使用紧凑表格；例如 `query CX759` 只显示一行航班摘要。
需要完整字段时使用 `query CX759 --details` 或 `query CX759 -d`。

---

## 系统要求

- **Python**: 3.9 或更高版本
- **依赖**: 基础包无第三方依赖
- **增强终端界面**: `.[tui]` 可选安装组（引入 Textual）
  ```bash
  pip install "hkg-flight-data[tui]"
  ```
