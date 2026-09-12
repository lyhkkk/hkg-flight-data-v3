# 项目长期记忆 — hkg-flight-data-v3

## 技术约定

- **Python**: 3.9+（2026-09-11 起）。基础包仅标准库；`.[tui]` 可选引入 Textual。
  曾要求全部源码 3.7 可解析，已由用户授权放弃（代价是不得不写 `.format()`）。
- **快照语义**: "发布后不可变"。`normalize_flights` 每轮产生全新 dict，发布后无人
  修改；读者只拿列表浅拷贝。**不要再引入 deepcopy** —— 它曾出现在每次发布和每次
  0.2s 的 UI revision 轮询上。
- **信任边界**: 不可信 API 字符串在数据入口 `utils.clean_text()` 清洗一次；渲染层
  不做二次防御（`views` 只做 `[` 转义）。不要把清洗逻辑搬回渲染层。
- **渲染单一来源**: TUI 与 plain 共用 `views.flight_header()` / `flight_row()` /
  `alert_line()` / `airline_line()`。不要为 plain 另写一套表格。
- **flight key 含方向**: `{date}_{ARR|DEP}_{flight_number}`。HKIA 每天有约 6 个
  **同号双向**航班（同一天同一航班号既到达又出发，如 UA820）。key 少了方向会
  在 `search_flights` 去重时静默丢数据、让 `poller` 的 `old_map` 塌陷、让到达航班
  落地时抹掉出发航班的告警。**任何以 flight key 为身份的代码都要意识到方向。**
- **gate/stand 渲染**: `gate` 是**裸数字**（`68`）且只出现在出发 → 显示时补 `G`
  成 `G68`；`stand` **自带区域字母**（`W63`/`D201`/`S25`）且只出现在到达 →
  **原样显示，绝不要再补前缀**（曾渲染出 `SW69`、web 端 `Stand W63`）。
- **ROUTE 列带方向**: `← KIX` 到达 / `→ KIX` 出发。裸机场码在混合列表里有歧义。
- **输出宽度单一来源**: `utils.terminal_width()`（识别 `COLUMNS`，上限 `MAX_WIDTH=120`，
  测不到回落 78）。`views` / `cli` / `plain` 共用它，**不要再硬编码宽度**。
  不变量：**任何渲染行都不超过请求宽度**（`flight_row` / `flight_header` /
  `alert_header` / `alert_line` / `airline_line` / `_paged` 都必须 `truncate`）。
  CLI 与 plain 没有终端高度，用 `views.is_compact(width)`（< 80 列为真）决定是否
  走两行紧凑形态。
  - **plain 的表头与页标题也曾漏掉这条**（2026-09-13 修）：`HKG | Data date …` 与
    `_title()` 都是拼完直接输出，30 列下最多溢出 **55 格**。现在表头走
    `views.plain_header_line(snap, width)`，页标题走 `views.truncate`。
    **plain 没有第二行可以溢出，所以只能截断**（TUI 表头是 `fit()` 阶梯，可以丢字段）。
- **陷阱：`views.text_width()` 会剥掉 rich markup。** 凡是用它量宽度、又把字符串
  原样 `print` 出去的（CLI 梯子文案），**绝不能含 `[...]` 形态的字面量** ——
  `[n]` 会被当成标签剥掉，宽度低估 9 cells，于是在窄终端上选中放不下的写法而折行。
  分页脚注 / 提示的阶梯写法保持在 `cli._PAGER_FORMS` / `_CODESHARE_FORMS`。
- **列宽 = 最小宽度 + 权重余量**（2026-09-12）。`FLIGHT_COLUMNS` / `ALERT_COLUMNS`
  的每一项是 `(label, weight, minimum)`，`minimum` 是实测的内容最大宽度。
  **不要退回纯比例权重** —— 那会让 `T1` 拿到 20 格而 26 字符的 status 被截断，
  且终端越宽状态越窄。**表头标签不能给自己单独的最小宽度**（会让所有列错位），
  把标签宽度写进列定义。
- **TUI 整宽 widget 不许有横向 padding**（2026-09-12）。`theme.tcss` 的
  `#header/#nav/#search_row/#body/#footer` 都是 `padding: 0`，因为渲染层拿到的是
  终端宽度。**不变量：widget 内容宽 == 渲染宽度。** 有 padding 时 Textual 不裁溢出，
  而是按**词**折行（把整个最后一个词推到下一行）。
  实测（真机 Textual 8.2.8，55×30，`padding: 0 1`）：真正裂开的是**分隔线**
  （`"-" * width`，没有空格可吸收溢出）；航班行有 6 格尾部空格兜着，反而没折。
  所以别用「航班行折没折」判断这条不变量——要用分隔线，或直接断言内容宽。
- **`export_screenshot()` 是按样式段输出，不是按行**（2026-09-12 踩过）。
  SVG 里每个 `<text>` 是一个**样式段**：航班行的状态单独着色，所以它和前半段是
  **同一个 `y` 上的两个 `<text>`**。把每个 `<text>` 当一行读会**凭空造出折行**。
  正确读法见 `tests/test_terminal_textual.py`：按 `y` 分组、用 `x` 拼回格位；
  单元格宽由「每行右边缘的 marker 段」标定（`max(x) / 终端宽度`，真机是 12.2）。
- **那个「右边缘 marker 段」就是 Rich 每行结尾的换行段**（`text == '\n'`，
  位于 `x = 宽度 × cell`），**不是**什么额外的装饰段（2026-09-12 实测）。
  数量 = 绘制行数 − 2（首行装饰行和最后一行没有）；空 body / 无匹配搜索 /
  20×10 / 120×30 下都存在，因为 chrome 那 4 行永远在。所以只要画了 ≥3 行，
  `max(x)` 一定来自它 —— 「空 body 会让校准失准」是**不可达**的。
  `screen_lines` 现在有守卫：右边缘段非空就报错，绝不静默用错的 cell 拼行。
- **`html.unescape` 会把 `&#160;` 变成 U+00A0，不是普通空格**（2026-09-12 踩过）。
  `screen_lines` 里换 `html.unescape` **必须**跟 `.replace("\xa0", " ")`，
  否则每一行都含 nbsp，`assertIn` 拿 `views` 的普通空格行去比会**全线挂**，
  而屏幕看起来完全一样。
- **CLI stdout 只在 `main()` 里 `reconfigure(errors="replace")`**（2026-09-12）。
  `→`/`←` 在 cp1252/cp437 下不可编码（GBK 可以），不设就抛 `UnicodeEncodeError`。
  **只改 `errors`，绝不改 encoding** —— 一个 `?` 占一格，保住「渲染行 ≤ 请求宽度」
  不变量；重编成 UTF-8 反而会破（cp1252 控制台把箭头的 3 字节渲染成 3 个字形）。
  注意 WorkBuddy 的 shell 有 `PYTHONUTF8=1`，**项目自己的验证命令看不到这个问题**，
  要复现得 `PYTHONUTF8=0 PYTHONIOENCODING=cp1252`。
- **TUI chrome 占 4 行**（`views.CHROME_ROWS`），`textual_app._body_height()` 与
  `body_lines` 都用它；`theme.tcss` 里那 4 个 widget 必须各 1 行（有测试解析 CSS 锁住）。
- **阶梯写法统一用 `views.fit()`**（CLI 与 TUI 共用），不要各写一份。
- **并发模型**: poller 只有一个写者线程，`_refresh` 串行执行。刷新期间的手动请求
  返回 `already_running`，不排队。**不要重新引入 generation / publish-gate。**
- **告警语义（2026-09-11 重制）**: 告警 = 偏离**最初分配**。首次分配是基线，不告警；
  之后 release / change 才告警；回到基线或航班结束则清除。`old_value` 恒为原始分配值，
  所以 `N24 -> - -> S47` 显示为 `N24 -> S47`。**不要改回"首次分配即告警"**，
  也不要让 release（new 为空）漏掉。状态判定用 `utils.status_category()`。
- **看板窗口（2026-09-13，step 2）**: `utils.board_dates(now)` 是**唯一**的窗口规则
  （`>=22:00` → 今天+明天；`<02:00` → 昨天+今天；否则仅今天）。`cli._search_dates`
  **委托**给它，所以搜索与看板不可能各算各的。
  - **窗口必须由一次读钟算出**：再读一次可能跨过 23:59:59，把今天的窗口标成明天的。
  - 发布**两个**字段：`records_date`（看板自己的钟面日期）与 `records_dates`（实际窗口）。
    表头只在**今天不在窗口任何一天**时才标 `(previous)`；窗口只是从昨天开始，那是
    **当前**看板，用 `Data date 2026-09-12 +1` 标跨度。
  - **`/api/flights` 不带 `date` 时返回整个窗口，并且必须排序** —— 前端按行序扫描定位
    锚点，乱序会停在错误的日期上。顺序是契约。
  - 窗口里只要有一天来自缓存，整轮 source 标 `cache`（一半实时一半记忆不能自称实时）；
    某天失败时另一天照常发布并记 `last_error`（半张看板好过空看板）。
  - **`alerts.retain_dates(dates)`** 保留窗口内日期的告警。基线剪枝取 key 里的日期用
    `pair[0].split("_", 1)[0]`，**不能用 `startswith`**（`2026-09-1` 会匹配上 `2026-09-11`）。
- **告警存储**: `alerts.json` 是一个列表（最新在前，上限 500，仅看板窗口内的日期）。
  没有 active/history 双表，不要加回来。
- **时间锚点（2026-09-13，step 1+2）**: 离港/到达打开与每次刷新都停在**当前 HKT 航班**
  上（`presenter.anchor_index` 取最早 ≥ 时钟的行）；`PageState.anchor_auto` 表示列表
  仍跟着时钟走，任何手动移动（含 `Home`/`End`）或 `[`/`]` 翻页都置 `False`，`t` 交还。
  - **锚点是 `(服务日期, 时刻)`，不是分钟数**（2026-09-13 修的真 bug）。
    `anchor_index(rows, minutes, date=None)` 比较元组；**不带 `date` 会退化并停在昨天**
    —— 两天看板上 `01:30` 有两条，整个 22:00–01:59 档都会停错。不带 `date` 的形态
    只为单日看板的向后兼容保留。**行不带日期时视为属于正在锚定的那一天。**
  - **`views.row_capacity()` 是「一屏多少行」的唯一来源**，`body_lines` 与翻页键共用。
    不要再各写一份 —— 两边不一致就等于漏航班或重复航班。
  - **`anchor_step` 必须步进 offset（`_park_index`），不能步进 selection。**
    `_select_index` 的 height 语义是「把选中行留在视窗内」，会把 offset 拉回
    `index - height + 1`，于是「翻一屏」实际只前进 **1 行**（实测 0→1→21→41）。
  - **`_window` 会把 offset 回拉到 `len(rows) - capacity`**，所以**最后一屏是满的、
    会和上一屏重叠**。这是刻意的（给整屏而不是两行余数）。断言"两屏不重叠"时
    样本必须够大，否则尾部必挂。
  - **时钟必须可注入，且返回「时刻」不是分钟**（`Session(clock=now_hkt)` /
    `Poller(clock=now_hkt)`）。`Session.start()` **不碰** UI state，所以首屏锚定只能由
    app 的 `on_mount` 做 —— 测试要 `build_session(reconcile=False)` 才测得出来
    （`reconcile()` 会顺带锚定，掩盖接线）。注入 `lambda: 9 * 60`（int）会直接
    `AttributeError: 'int' object has no attribute 'hour'`。
  - **web 端时钟由服务端下发**（`/api/stats` 的 `hkt_now` / `hkt_minutes` / `hkt_date` /
    `dates`）：看板是香港的，"现在"不能取浏览器所在时区。前端 `anchor = {minutes, date, auto}`。
  - `views.date_text(flights)` → `2026-09-12` 或 `2026-09-12 +1`；`anchor_label(page, day)`
    只在锚点日期 ≠ 看板日期时补 `MM-DD`（`Pinned 09-13 01:30`）。
- **`views.flight_row()` 返回的是行列表**（紧凑档两行），不是字符串。
- **`presenter.visible_rows(snapshot, ...)` 要的是 flights 快照**，不是 combined 快照
  （`views._rows_for` 内部做 `snap["flights"]`）。传错静默拿到空列表。

## 测试约定

- 测试面向**公开行为**，不触碰 poller / session 的私有机制。
- 历史上存在"锁定死代码的测试"（如 `test_read_write_state`、`test_status_pair`），
  以及第三方 agent 的 gate 基线测试，均已删除。新增测试不要为私有实现写断言。
- 离线夹具在 `tests/fixtures/terminal/data.py`。
- **夹具的 `flight_number` 不唯一**（`make_flights` 会注入同向重复段），
  **不要用航班号判断"某行是否在屏上"**。改用 `views.flight_row(...)` 渲染出该行的
  文本再比 —— 时间不同，重复段的渲染结果也不同。
- 增强 UI 测试在未安装 Textual 时自动 skip。**本机已装 Textual 8.2.8，但只装在
  系统 Python 3.14**（`C:\Users\avery\AppData\Local\Programs\Python\Python314\python.exe`）；
  WorkBuddy 托管的 3.13 没有 Textual。要跑真机 TUI 测试就用 3.14，
  期望 **395 用例、0 skipped**；用 3.13 跑是 **17 skipped**。
  （`ruff` 也只在 3.14 里，托管 3.13 没有 —— 用
  `C:/Users/avery/AppData/Local/Programs/Python/Python314/python.exe -m ruff check .`。）
- **真机 TUI 测试的写法**（`tests/test_terminal_textual.py`）：
  `app.run_test(size=(w, h))` + `pilot.pause()`；观察屏幕只能用
  `app.export_screenshot()`，并按 `y` 重建行（见上面 `export_screenshot` 陷阱）；
  触发重绘用 `app.revision += 1`（app 自己的 reactive），**不要调 `_refresh_view()`**；
  比较文本用 `views.strip_tags()`，**不要读 `app._color`**（`body_lines` 的 `color`
  只加 markup，可见文本相同）。
- **时间相关的纯函数要把"现在"作为可注入参数**（如 `cli._search_dates(date_str, now=None)`），
  否则测试会变成定时炸弹——`test_search_dates_covers_today_by_default` 就只在白天通过。
  **TUI / web / poller 测试同样**，且注入的是**时刻**（`build_session(clock=lambda: at(9 * 60))`，
  `at(minutes, day)` 返回带日期的 HKT datetime）。真实时钟不仅让锚点位置随小时变化，
  更会让 22:00–02:00 的用例自动去抓**两天**（`api.calls == 1` 之类的断言夜里必挂）。
- **写回归测试后反向验证一次**：把 bug 打回去，确认测试确实失败。否则可能只是
  "恰好通过"。反证（negative control）也要反向验证一次：让「本该发生的事」不发生，
  确认断言会挂。
- **给渲染加"输出 ≤ 请求宽度"的不变量测试**，扫一串宽度（120…1）。这条不变量
  已顺带挖出三处别处的同类 bug（2026-09-11 第四轮、2026-09-12、2026-09-13 的
  `plain` 表头/页标题）。**新渲染路径一律先补这条测试** —— 它比读代码便宜。
- **最强的端到端不变量：渲染器产出的每一行都必须原样成为屏幕上的「一行」**
  （`test_every_rendered_line_reaches_the_screen_intact`，扫 42/55/80/120 列）。
  折行、裁切、少一行，全都会被这一条抓到。
- **同一不变量要在两个布局档位都测**（紧凑档 / 单行档）。紧凑档的两行 row 会把
  余数 floor 掉，恰好掩盖边界错误（2026-09-12 的高度预算就中过招）。

## 文档约定

- `SPEC.md` 描述**实际系统**，不是实现约束。不要往里写"必须如何实现"的条款。
- 第三方 agent 的历史产物已归档在 `docs/archive/`，不要再往根目录堆积。

## 验证命令

```bash
# 基础包（WorkBuddy 托管 Python 3.13，无 Textual）—— 期望 395 用例、17 skipped
C:/Users/avery/.workbuddy-ai/binaries/python/versions/3.13.12/python.exe -m compileall -q hkg_flight tests cleanup_alerts.py test_hkg_flight.py
C:/Users/avery/.workbuddy-ai/binaries/python/versions/3.13.12/python.exe -m unittest discover -s . -p "test*.py"

# ruff 只在系统 3.14 里（托管 3.13 没装）
C:/Users/avery/AppData/Local/Programs/Python/Python314/python.exe -m ruff check .

# 真机 TUI（系统 Python 3.14，有 Textual 8.2.8）—— 期望 395 用例、0 skipped
C:/Users/avery/AppData/Local/Programs/Python/Python314/python.exe -m unittest discover -s . -p "test*.py"

# 复现 cp1252 控制台上的编码问题（默认环境有 PYTHONUTF8=1，看不到）
PYTHONUTF8=0 PYTHONIOENCODING=cp1252 <3.13 解释器> -m unittest test_hkg_flight.TestCLIRendering
```

两个解释器都要跑：3.13 证明基础包零依赖，3.14 证明增强 UI 真的能渲染。
