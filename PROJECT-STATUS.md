# HKG Flight Data v3 — Project Status

> 最后更新: 2026-09-12

## 项目状态: ✅ TUI 真机验证通过，283 项测试 + lint 全绿

## 第五轮修正 — 2026-09-12（装上 Textual，真机验证 + 两处结论订正）

第四轮的结论是**离线**推出来的（逐行量宽度 + 解析 `theme.tcss`）。装上 Textual
8.2.8（Python 3.14）后把 TUI 真的跑起来，发现两处需要订正。

### 订正一：`export_screenshot()` 是**按样式段**输出，不是按行

Textual 的 SVG 里每行不是 `<text>`，而是**每个样式段一个 `<text>`**。航班行的状态
是单独着色的，所以它和前半段是**同一个 `y` 上的两个 `<text>`**（状态在 `x=280.6`，
即第 23 格）。把每个 `<text>` 当成一行去读，会**凭空造出折行**——第一版测试助手就是
这么写的，于是「状态独占一行」的假象在修复后的代码上又出现了一次。

正确读法：按 `y` 分组，再用 `x` 把每段拼回它所在的格。单元格宽是字体度量
（12.2），不写死——Rich 会给每一行在右边缘补一个 marker 段，`max(x) / 终端宽度`
就是它。

### 订正二：55 列下 `padding: 0 1` 折的是**分隔线**，不是航班行

实测（`padding: 0 1`，55×30）：屏幕画出 **31 行**，逻辑行只有 25 行——多出来的 1 行
是**分隔线**。分隔线是 `"-" * width`，**没有一个空格可以吸收溢出**，所以内容宽少
2 格就立刻裂成两行；而航班行有 6 格尾部空格兜着，55 列下（有效内容 49 格）反而没折。

所以「内容宽 ≠ 渲染宽」确实是必须修的不变量违例（分隔线就是证据），但**航班行本身
在那个宽度下没折**。手机截图里日期被挤下去，主因是**缺陷三**（STATUS 列被权重饿死
到 22 格，状态先被截成残段）叠加**缺陷二**（顶栏/导航/底栏不看宽度而折行，chrome
从 4 行涨到 6 行，把 body 挤掉 2 行）。第四轮的修复方向没问题，只是归因需要修正。

### 真机验证到的几何（Textual 8.2.8）

| 断言 | 结果 |
|---|---|
| `#body.content_size.width == app.size.width` | ✅ 55 / 80 / 100 / 45 / 120 全部成立 |
| `#header` / `#nav` / `#footer` | ✅ 每个都是 `Size(width=W, height=1)` |
| `#body.size.height` | ✅ `app.size.height - 4`，即 `views.CHROME_ROWS` |
| `#body` 全部 widget padding | ✅ `0 0` |

### 新增 4 条真机测试（`TestTextualGeometry`）

| 测试 | 断言 |
|---|---|
| `test_every_rendered_line_reaches_the_screen_intact` | **最强的一条**：`views` 产出的每一行（4 条 chrome + body）都必须原样成为屏幕上的**一行**。42/55/80/120 列都扫 |
| `test_a_long_status_stays_on_its_flight_row` | 42/45/48/55/80/100/120 列下，26 格状态都和它的航班号在同一行，且没有任何一行是孤立的日期残段 |
| `test_a_word_that_does_not_fit_moves_to_its_own_row` | 反证：故意喂一个放不下的词，确认检测器真的能看见折行 |
| `test_the_old_padding_would_have_wrapped` | 反证：把 `padding: 0 1` 装回去，分隔线必须裂成两行 |

**反向验证**（把 bug 打回去，确认测试真的会失败）：

| 打回的 bug | 失败的测试 |
|---|---|
| 去掉 STATUS 列最小宽度（退回纯权重） | `test_a_long_status_stays_on_its_flight_row` |
| 把「每段当一行」的旧助手装回去 | `test_a_long_status_stays_on_its_flight_row` + `test_every_rendered_line_reaches_the_screen_intact` |
| 让渲染出的一行比 widget 宽 | `test_every_rendered_line_reaches_the_screen_intact` |
| 让溢出刚好放得下 | `test_a_word_that_does_not_fit_moves_to_its_own_row`（找不到那个词） |

### 结果

`unittest` 276 → **283**（+7：真机测试 12 条，此前 5 条被 skip，现在 0 条 skip）。

## 第四轮修正 — 2026-09-12（TUI 折行）

用户贴了手机上的 TUI 截图。表面症状是状态串里的 `(12/09/2026)` 独占一行、被
截成 `(12/09/20…`。查下来是**四个独立缺陷**。

### 缺陷一（核心）：渲染宽度 ≠ widget 内容宽

`theme.tcss` 里 `#header/#nav/#search_row/#body/#footer` 都是 `padding: 0 1`，
widget 内容宽 = `size.width - 2`；而 `body_lines` 是按 `size.width` 渲染的。
实测 **25/26 行正好顶满 `width`**，Textual 于是按词重新折行——它不会裁掉溢出
的 2 格，而是把**整个最后一个词**推到下一行。所以 `At gate 23:47 (12/09/2026)`
的日期部分被整块挤了下去。

修复：**去掉所有横向 padding**，让「渲染宽度 = 终端宽度」成为唯一来源，gutter
改由渲染层提供（header/nav/footer 自带前导空格，航班行自带两格选择标记）。
不这么做的话，CSS 的 padding 与 Python 里的宽度常量要永远手工同步。

> ⚠️ 本节的归因已在**第五轮**订正：55 列下真正被折掉的是分隔线而不是航班行，
> 且当时的测量助手把「样式段」当成了「行」。详见上文第五轮。

### 缺陷二：顶栏/导航/底栏根本不看宽度

| 行 | 修复前 | 手机 55 列下 |
|---|---|---|
| header | 65 | 折行，出现孤立的 `\|` |
| nav | 74 | 折行，`Poll ON / Web OFF` 被挤到第二行 |
| footer | 66 | 折行，`q Quit` 掉出屏幕 |

修复：三条都加 `width` 参数与阶梯写法（`views.fit`）。header 先丢源时间戳、
再丢 Web 指示、再丢字标；footer 保住 `q`；nav 退回短标签 `Dep/Arr/Alerts/Air`。
`cli._fits` 与它重复，已删掉，统一用 `views.fit`。

### 缺陷三：状态列被饿死，短字段却浪费空间

`layout` 是纯比例权重：55 列下 TIME 分到 11 格（只需 5）、TERM 分到 8 格
（只需 3），而 STATUS 只有 22 格却要放 **26 字符**的真实最长状态
`At gate 23:47 (06/09/2026)`。100 列下更糟——宽屏走 6 列布局，status 权重
4/18，反而更窄，**终端越宽状态越看不清**。

修复：列定义升级为 `(label, weight, minimum)`，每列先拿最小宽度（取自实测
最大值），余量再按权重分；放不下时退回纯权重。表头与数据行读同一张表，不会漂移。
**表头标签不给自己的最小宽度**——那会让所有列错位（`GATE/STAND` 要 10 格而数据
只要 5 格，所以把 10 写进列定义，让表头永远不出现省略号）。

### 缺陷四：body 高度多算 1 行

`available = height - 3`，但 `#body` 实际是 `height - 4`（4 个 chrome widget）。
单行档下永远多出 1 行被裁；header/nav 折行时 chrome 变 6 行，裁得更多
（截图里 `7C6014` 丢了第二行）。修复：引入 `views.CHROME_ROWS = 4`，
`textual_app._body_height()` 也改用它，并用测试解析 `theme.tcss` 锁住这个数。

### 顺带

- 紧凑档不再显示 `COMPACT` 占位表头（与 CLI 一致，两行行没有能对齐的表头）
- 空搜索时不再显示 `Search: —`，只留 `Matches 406 / Total 406`
- size-hint 文案是唯一没做自身截断的渲染器，已统一 `truncate`
- 新增 `TERM` / `GATE/STAND` 列最小宽度，保证表头永不出现省略号

### 结果

手机 55×30 下：chrome 从 6 行降到 4 行，可视航班 8 → 12 条，26 字符状态从
48 列起就完整显示（修复前 100 列都放不下）。测试 255 → **276 全绿**（+21）。

## 第三轮修正 — 2026-09-11（手机宽度的 CLI 折行）

### 背景

手机宽度下 `query` 输出会折行，`G30` 被从中间劈成 `G` 和 `30` 落到下一行。

### 根因

CLI 把宽度写死成 `DEFAULT_WIDTH = 78`，完全不看真实终端。78 列的行在 45 列的
窗口里必然被 shell 折断——折点落在哪一列是随机的，所以表现为「值被劈开」。

### 整改

宽度只有一个来源：`utils.terminal_width()`，识别 `COLUMNS`，上限 `MAX_WIDTH = 120`，
测不到时回落到 78（管道输出）。`views` / `cli` / `plain` 共用它。

| 宽度 | 形态 |
|---|---|
| ≥ 80 列 | 每条航班一行，带列标题 |
| < 80 列 | 去掉列标题，每条航班两行；字段顺序与单行一致 |

`views.is_compact(width)` 是 `layout_tier` 的「无高度」版本，给 CLI / plain 用。
标题、分页脚注、`--codeshare` 提示按阶梯降级（最长的能放下就用最长的，都放不下就不输出）。

### 顺带修掉的两个真缺陷

- **阶梯字符串不能含 markup 形态的字面量。** 原来的短格式写作 `[n] [p] [q]`，
  而 `views.text_width()` 会把 `[n]` 当 rich 标签剥掉——宽度被低估 9 cells，
  于是在 20 列终端上选中了实际 26 列的写法，照样折行。已改为 `n/p/q`，
  并加了一条断言：阶梯里每个写法都必须满足 `text_width(s) == len(s)`。
- **`flight_row` / `flight_header` / `alert_header` 是唯一没做自身截断的渲染器。**
  极窄宽度（< 2 列）下 marker 自身就超宽。已统一 `truncate` 到请求宽度，
  与 `alert_line` / `airline_line` / `_paged` 对齐。

### 验证

用真实缓存（2026-09-11，835 条记录）扫描 120/100/80/79/60/45/30/20/12/8/4/1 列，
**超宽行 0 条**。

## 第二轮修正 — 2026-09-11（数据身份 + 渲染）

### 背景

`query 862` 输出里 `ZE862 00:05 ICN` 出现两次、`query 067` 里 `MM067 23:55 KIX`
出现两次，看着像重复行。查下来是**两个独立缺陷**叠在一起。

### 缺陷一：跨日结果看不出日期

`query` 在 22:00–01:59 会搜相邻两天（设计如此，为了找到次日 00:05 的红眼航班），
但表格只渲染 `HH:MM`，于是相邻两天同一时刻的两条记录长得一模一样。

修复：结果集跨多天时按天插入日期分隔线 `-- 2026-09-11 ----`。

### 缺陷二：flight key 不含方向（会丢数据）

`make_flight_key` 是 `{date}_{flight_number}`。而 HKIA 真实存在**同号双向**航班
——同一天同一航班号既到达又出发（UA820 从 LAX 落地、再飞往 BKK）。实测 7 天
缓存里**每天稳定有 6 个**这样的航班号（UA820/UA821/UA152/UA153/ET644/ET645）。

后果：

| 位置 | 后果 |
|---|---|
| `cli.search_flights` 按 key 去重 | 同号双向只留一条，另一条静默消失（实测 `query UA820` 丢了 07:40 → BKK） |
| `poller._refresh` 的 `old_map` | 同号双向塌陷成一条，可能拿到达记录去和出发记录做 diff |
| `alerts._drop_key` | 到达航班落地会连带抹掉同号出发航班的机位告警 |
| `alerts.json` 缓存 | 6 条告警全部落在碰撞的航班号上，已被污染 |

修复：key 改为 `{date}_{ARR|DEP}_{flight_number}`；已备份并清空被污染的告警缓存。

### 顺带的渲染修正

- **stand 不再补前缀**：HKIA 的 `stand` 自带区域字母（`W69` / `D201` / `S25`），
  旧代码又拼了个 `S`，渲染出 `SW69`。现在原样显示 `W63`；web 端也去掉了冗余的
  `"Stand "` 前缀（列头已经写了 Gate / Stand）。
- **ROUTE 列标方向**：`← KIX`（到达，来自 KIX）/ `→ KIX`（出发，前往 KIX）。
  裸机场码在混合列表里有歧义，且同号双向无法区分。
- `query` 标题从 `862 flights — 5 flight(s)` 改为 `Query '862' — 5 flight(s)`。

### 数据字段事实（7 天 1928/1755 条，零例外）

| 字段 | 形状 | 出现于 |
|---|---|---|
| `gate` | 纯数字 `68` | 只有出发 |
| `stand` | 字母+数字 `W63` | 只有到达 |

### 顺带修掉的测试缺陷

`test_search_dates_covers_today_by_default` 断言"默认只搜今天"——但它只在
02:00–21:59 通过，夜里必挂（跨午夜是设计行为）。已改为注入 `now`，并补上跨午夜用例。

## 上一轮重制 — 2026-09-11（告警 + Web）

### 背景

旧告警规则是 `old_value != new_value and new_value`，把**首次分配**当成变化。
每个正常航班都会分到机位，一天几百个航班就产生几百条告警，信号被噪音淹没；
而真正的 **release**（`N24 -> -`）反而被漏掉。CLI、TUI、Web 三个前端共用这套规则。

### 新规则（`alerts.py` 重写）

以"**原始分配**"为基线：首次分配不告警，之后的 release / change 才告警。

| 序列 | 结果 |
|---|---|
| `- -> N24`（首次分配） | 不告警 |
| `N24 -> -`（release） | 告警 `N24 -> —` |
| `N24 -> S47`（change） | 告警 `N24 -> S47` |
| `N24 -> - -> S47`（释放后重分配） | 告警 `N24 -> S47`（保留原始基线） |
| `N24 -> S47 -> N24`（回到原值） | 清除告警 |
| 航班 departed / landed / cancelled | 清除该航班全部告警 |

- 告警记录形如 `{key, flight_number, date, time, type, field, old_value, new_value, status, status_category, raised_at}`，`old_value` 恒为原始分配值。
- 上限 500 条、最新在前；`retain_date()` 在每次刷新时清掉非当前数据日期的告警。
- 删除 active/history 双表：历史仅被测试与清理脚本消费，属于无消费者的设计。`alerts.json` 现在就是一个列表。

### 前端重制

- **TUI 告警页**：从裸文本行改为对齐表格 `CHANGED / FLIGHT / CHANGE / STATUS`，状态按类别着色；详情页显示变动 + 当前航班信息。
- **CLI `alerts`**：复用同一 `views` 渲染（不再另写一套），输出与工作台一致。
- **Web**：单页仪表盘重写，双视图（Flights / Gate·Stand Changes），状态药丸、数据源健康指示、30 秒自动刷新；`/api/stats` 扩展为数据源健康（来源 / 日期 / 航班与告警数量）。

### 顺带修复的失实文档

- `COMMANDS.md` 的 `HKG_CACHE_DIR` / `HKG_WEB_PORT` 两个环境变量在代码中不存在（只有 `NO_COLOR`）——已更正。
- `COMMANDS.md` 声称"今日数据缓存 5 分钟 / 历史数据 24 小时"——实际航班数据无 TTL，每次直连 API 并写穿缓存；只有航司元数据有 24 小时 TTL。已更正。

## 环境信息

| 项目 | 状态 |
|------|------|
| Python | 3.9+（基础包），3.11 / 3.13 为 CI 目标；本机 3.13 与 3.14 均通过 |
| 依赖 | 基础包仅标准库；`.[tui]` 可选引入 Textual |
| 测试 | **283 用例通过**（装了 Textual 8.2.8 时 0 skipped；未装时 12 skipped） |
| Lint | `ruff check .` 全部通过 |
| 数据源连接 | ✅ 实测（今日 417 departures / 415 arrivals） |

## 历史重构 — 2026-09-11（第一性原理）

### 背景

代码与指令由多轮第三方 agent 迭代产生，累积了大量**为不存在的威胁模型设计的防御**：
并发发布门控、全链路深拷贝、渲染层逐字符清洗、测试专用 API 泄漏进生产代码。
复杂度翻倍、性能浪费，且真实缺陷被掩盖。

### 规模变化

| | 重构前 | 重构后 | 变化 |
|---|---|---|---|
| `hkg_flight/` 源码 | 4677 行 | 3703 行 | **-974 行（-20%）** |
| 测试代码 | 3482 行 | 2113 行 | -1369 行 |
| 测试用例 | 82 收集 / 2 errors | **222 全绿** | — |
| 仓库根目录文档 | 33 份 agent 产物 | 归档至 `docs/archive/` | — |

### 移除的过度防御

| 设计 | 为什么移除 |
|---|---|
| poller 的 `_generation` / `_published_generation` / publish-gate | 只有一个写者线程，`_refresh` 从不与自身并发。"迟到/乱序/跨日结果"永远不会出现。反证：原 `_run` 里 `_refresh_pending = False` 根本没持锁 |
| 全链路 `copy.deepcopy` | `normalize_flights` 每轮产生全新 dict，发布后无人修改。快照只需浅拷贝列表 |
| `latest_revision()` 构造完整 snapshot | Textual 每 0.2 s 调用一次，每次都深拷贝全部活跃告警。改为返回轻量 tuple |
| `views.py` 的 rich-markup 白名单 + 标签平衡 + 字符簇切分（~100 行） | 信任边界画错了位置。改为：清洗下沉到数据入口 `clean_text()`，渲染层只做 `[` 转义 |
| `plain.py` 的第二套渲染（`_ANSI_RE` + 独立表格） | 与 `views.py` 双写必然漂移。合并为共用 `flight_header()` / `flight_row()` |
| session 的 airlines `generation` / `done` / `worker_error` 门控 | 单次加载，直接赋值即可 |
| session 的 `WEB_STARTING` 状态与 close 竞态处理 | bind 是同步的，没有"中间态"需要发布 |
| `airlines_worker_status()` 返回 thread 对象 | 测试专用 API 泄漏进生产代码 |
| cache 的 `_safe_cache_path` 路径穿越检查 | 日期已被 `validate_date` 严格限定为 `\d{4}-\d{2}-\d{2}`，穿越不可能发生 |

### 移除的死代码（已验证零生产调用）

- `cache.read_state` / `write_state` / `state_path` + SPEC 的 `state.json` 契约
- FVM 全套：`api.fetch_fvm_registrations`、`cache.merge_fvm_snapshot` / `read/write_fvm_registrations`、`cli._merge_fvm_data`
- `utils.format_time` / `format_raw_time` / `status_pair` / `filter_records`
- `poller.consume_new_alert_flag` / `alerts.consume_new_flag` / `new_flag` 字段
- `presenter.project_flight` / `MUTABLE_OPERATION_FIELDS` / `views.sanitize`
- normalize 产生的 `statusCode` / `status_display` / `status_label`（只写不读）
- 死代码被测试锁定的循环（原 `code-review-report-v4.md` 自承"删除会破坏测试套件，故保留"）

### 顺带修复的真实缺陷

- **`boarding_soon` 分支永远不可达**：状态匹配表把 `board` 排在 `boarding soon` 之前，`Boarding Soon` 一直被归类为 `boarding`
- **航班号可能不完整**：只给数字的 payload（`{"no": "759"}`）会让 `query CX759` 失效。实测真实 API 的 `no` 已含 IATA 前缀，现兼容两种形态
- **文档失实**：`COMMANDS.md` 记载的 `HKG_CACHE_DIR` / `HKG_WEB_PORT` 两个环境变量在代码中根本不存在；`query` 的默认日期范围描述错误

### 文档与约束

- **放弃 SPEC §9 的 Python 3.7 兼容要求**（用户授权）：全项目可用 f-string 等现代语法；`requires-python` 升至 `>=3.9`
- SPEC 由"强制实现方式"改写为"描述实际系统"：移除 defensive-snapshot 强制条款与 `state.json` 契约
- `pyproject.toml` / CI 矩阵同步为 3.9 / 3.11 / 3.13

## 验证记录

```bash
python -m compileall -q hkg_flight tests cleanup_alerts.py test_hkg_flight.py   # OK
python -m ruff check .                                                          # All checks passed
python -m unittest discover -s . -p "test*.py"                                  # 283 tests, OK
```

两个解释器都跑过：

| 解释器 | 结果 |
|---|---|
| Python 3.14 + Textual 8.2.8 | 283 tests, **OK（0 skipped）** |
| Python 3.13（无 Textual） | 283 tests, OK（skipped=12） |

本轮另做了 Web 端到端冒烟：起服务器 → `/` 返回仪表盘 → `/api/alerts` 返回
`CX759 GATE 62 → 63` → `/api/stats` 报告 `source=api, flights=1, alerts=1`。

## 已知问题

- 增强 UI 需要 `.[tui]`；本机已装 Textual 8.2.8，增强 UI 测试与真机几何均已验证
- 窄终端的**不折行**已用真实数据全宽度扫描验证，并在真机 Textual 上复现验证；
  观感仍建议在真机手机上人工看一眼
- 香港业务日期语义（Asia/Hong_Kong 统一）仍为独立待决项
- 告警上限 500 条、按当前数据日期清理，`cleanup_alerts.py` 现在只用于手工查看/清空

## 后续建议

- [x] ~~在装有 Textual 的环境跑一次增强 UI 测试与真机交互~~ —— 已完成（第五轮）
- [ ] 如需跨重启的变更检测，重新设计 state 持久化（当前仅进程内快照）
- [x] ~~考虑给 Web 仪表盘增加告警视图~~ —— 已完成

## 待用户裁定的移除项

以下设计已无消费者，建议删除（本轮未擅自删除）：

- `cleanup_alerts.py`：告警已自动限流 + 按日期清理，`clear-cache` 也能清 alerts.json，该脚本已无职责
- `state.py` 的 `state.message` / `lost_selection_id` / `SELECTION_LOST_MESSAGE`：被写入但没有任何前端渲染，只有测试在断言
- `presenter.STATUS_FILTERS` 中未被 `STATUS_COLORS` 覆盖的项（`estimated` 等）——待确认是否仍需筛选入口
