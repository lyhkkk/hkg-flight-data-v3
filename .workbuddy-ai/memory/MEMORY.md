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
- **告警存储**: `alerts.json` 是一个列表（最新在前，上限 500，仅当前数据日期）。
  没有 active/history 双表，不要加回来。

## 测试约定

- 测试面向**公开行为**，不触碰 poller / session 的私有机制。
- 历史上存在"锁定死代码的测试"（如 `test_read_write_state`、`test_status_pair`），
  以及第三方 agent 的 gate 基线测试，均已删除。新增测试不要为私有实现写断言。
- 离线夹具在 `tests/fixtures/terminal/data.py`。
- 增强 UI 测试在未安装 Textual 时自动 skip。**本机已装 Textual 8.2.8，但只装在
  系统 Python 3.14**（`C:\Users\avery\AppData\Local\Programs\Python\Python314\python.exe`）；
  WorkBuddy 托管的 3.13 没有 Textual。要跑真机 TUI 测试就用 3.14，
  期望 **286 用例、0 skipped**；用 3.13 跑是 **12 skipped**。
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
- **写回归测试后反向验证一次**：把 bug 打回去，确认测试确实失败。否则可能只是
  "恰好通过"。反证（negative control）也要反向验证一次：让「本该发生的事」不发生，
  确认断言会挂。
- **给渲染加"输出 ≤ 请求宽度"的不变量测试**，扫一串宽度（120…1）。这条不变量
  曾顺带挖出两处别处的同类 bug（见 2026-09-11 第四轮、2026-09-12）。
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
# 基础包（WorkBuddy 托管 Python 3.13，无 Textual）—— 期望 286 用例、12 skipped
C:/Users/avery/.workbuddy-ai/binaries/python/versions/3.13.12/python.exe -m compileall -q hkg_flight tests cleanup_alerts.py test_hkg_flight.py
C:/Users/avery/.workbuddy-ai/binaries/python/versions/3.13.12/python.exe -m unittest discover -s . -p "test*.py"

# ruff 只在系统 3.14 里（托管 3.13 没装）
C:/Users/avery/AppData/Local/Programs/Python/Python314/python.exe -m ruff check .

# 真机 TUI（系统 Python 3.14，有 Textual 8.2.8）—— 期望 286 用例、0 skipped
C:/Users/avery/AppData/Local/Programs/Python/Python314/python.exe -m unittest discover -s . -p "test*.py"

# 复现 cp1252 控制台上的编码问题（默认环境有 PYTHONUTF8=1，看不到）
PYTHONUTF8=0 PYTHONIOENCODING=cp1252 <3.13 解释器> -m unittest test_hkg_flight.TestCLIRendering
```

两个解释器都要跑：3.13 证明基础包零依赖，3.14 证明增强 UI 真的能渲染。
