# V3-G2 Views/Geometry 修复报告

范围：views.py、最小共享显示工具、Views 测试
修复前：命令、解释器、R08/R02 失败
根因：
最小修复：
修复后：命令、计数、关键输出
R08：PASS/FAIL/BLOCKED/NOT RUN
R02：PASS/FAIL/BLOCKED/NOT RUN（如超出边界必须保留 FAIL）
R07：
R01/R05/R06/R09 保留状态：
核心/终端回归：
未验证/阻塞：
未触碰：
是否建议进入 G3a：仅由主 agent 决定
是否提交/推送：必须为否

---

## 范围

- `hkg_flight/terminal/views.py`（唯一被修改的生产文件）
- `tests/test_terminal_views.py`（唯一被修改的测试文件）
- 临时取证脚本 `.workbuddy-ai/tmp_g2/run_suite.py`（工作区本地 agent 数据，非交付物）

## 修复前

解释器：`py -3.11` → Python 3.11.9，Windows 原生。

冻结命令与结果：

```
py -3.11 -m unittest tests.test_v3_g0_baseline -v   → Ran 11 tests, FAILED (failures=5)
py -3.11 -m unittest tests.test_terminal_views -v   → Ran 11 tests, OK
py -3.11 -m unittest tests.test_terminal_textual -v → Ran 5 tests, OK
```

R08 失败输出：

```
AssertionError: 47 not less than or equal to 40 :
  '   北京北京北京北京北京北京北京北… --       TT1'
```

R02 失败输出（同一轮冻结）：

```
AssertionError: '2026-09-09|departure|CX100|00:00|HKG|北京|63||A|||T1|Boarding||CPA|CX100|QR9000'
             != '2026-09-09|departure|CX100|00:00|HKG|北京|||A|||T1|Scheduled||CPA|CX100|QR9000'
```

R07 冻结时通过（保持 PASS，见下）。

**修复前复现（同一命令、隔离副本）**：用 `build/lib/hkg_flight/terminal/views.py`（md5 `95c43c5738cca8703aeb3358b51c3ac1`，无 `re`/`unicodedata`、仍是旧的 `_trunc`/`_pad`，即修复前字节副本）覆盖到隔离目录 `hkg_flight/terminal/views.py` 后重跑：

```
py -3.11 -m unittest tests.test_v3_g0_baseline.TestV3G0PresentationBaseline \
    tests.test_v3_g0_baseline.TestV3G0DataAndLifecycleBaseline.test_r02_mutable_flight_fields_do_not_change_entity_id
→ Ran 4 tests, FAILED (failures=2)
  R08 FAIL: 47 not less than or equal to 40 : '   北京北京北京北京北京北京北京北… --       TT1'
  R02 FAIL: 同上
  R07 PASS / R10-previous-date PASS
```

## 根因

1. **R08 — `len()` 当宽度用。** `views.py` 的 `_trunc`/`_pad` 用 `len()` 截断/填充，CJK 与全角字符在终端占 2 个 display cell，`len()` 只算 1，因此 40 列终端上每行实际宽度可达 47 cells。
2. **R08 — 定宽 `str.format` 列排版。** `_flight_row` / `body_lines` 头行 / `_wide_body` 用 `{:<22}`、`{:<18}` 等硬编码列宽拼接，总宽随内容溢出，且完全不感知终端宽度。
3. **R08 — 行数无界。** `window = rows[offset:offset + available]` 按「记录条数」切片，而 compact 模式每条记录输出 **2 行**，40×16 时 `available=13` 会渲染出最多 26 行。
4. **R08 — 组合字符会被截断劈开。** 逐字符截断可以在基字符与其组合记号之间切断。
5. **R08 — 控制字符原样输出。** `\x07` / `\x1b` / C1 直接进渲染串。
6. **R02 — 根因在 `hkg_flight/terminal/presenter.py`，超出本阶段边界。** `ROW_ID_FIELDS`（presenter.py:53-70）把可变字段 `gate`、`stand`、`aisle`、`hall`、`belt`、`terminal`、`status`、`status_code` 一并纳入 `row_identity()`；gate 由 63 变空、status 由 Scheduled 变 Boarding 时身份串随之改变。**按指令要求只记录、不修改，R02 保留 FAIL。**

## 最小修复

仅改 `views.py`，未新增依赖、未改任何对外契约：

1. **display-cell 宽度原语**（`views.py` 顶部几何区）
   - `sanitize()`：剔除 C0/C1/DEL 控制码；只保留本模块自己会发出的颜色 markup（白名单 = `STATUS_COLORS.values()`），其余形如 `[bold red]` 的注入一律剥离。
   - `_cell_width()`：`unicodedata.east_asian_width` 为 W/F 记 2 cells，否则 1。
   - `display_width()`：markup 标签记 0 cells，控制码已剥离。
   - `_clusters()`：把「基字符 + 后续组合记号」合成一个不可分的 cluster（Mn/Me）。
   - `truncate()`：先预留省略号预算，按 cluster 截断，并把截断前已打开的标签按栈逆序闭合，**绝不输出未闭合 markup**。
   - `pad()` = 截断后右侧补空格到整宽。
   - 保留 `_trunc` / `_pad` 别名，旧调用方不受影响。
2. **`_layout(cells, width, gap=1)`**：权重列排版。表头与数据行共用同一组权重 `FLIGHT_COLUMN_WEIGHTS`（TIME 2 / FLIGHT 3 / ROUTE 5 / STATUS 4 / GATE/STAND 3 / TERM 1），剩余空间按最大余数法分配，最后再用 `truncate()` 兜底。
3. **`_window(rows, page, available, line_cost)`**：按「行数成本」切片（compact=2，其余=1），并在选中项落到窗口外时**仅为渲染**平移 offset（不回写 state，views 保持纯函数）。保证选择项始终可见。
4. **`_paged(lines, available, width, scroll=0)`**：详情区按高度分页并支持 `scroll` 位移；装不下时输出 `… N more` 计数，**不做静默丢弃**。`body_lines(..., detail_scroll=0)` 新增可选参数，既有调用方（textual_app 两处）签名不变。
5. **调用点全部改用几何原语**：`_flight_row`（compact 拆两行、marker 先行）、`_flight_header`、`_rule`、`body_lines`、`_help_block`、`_filter_block`、`_wide_body`、`_detail_overlay`、`_detail_block`、`_airline_detail`。空态文案抽到 `_empty_lines()` 原样保留（"Cannot load data, no cache available." / "No matches for current filters." / "Airlines error: …" 等）。
6. **测试**：`test_no_line_exceeds_width` 从 `len(line)` 升级为独立实现的 display-cell 计数 `cells()`；新增 `TestDisplayGeometry` 14 项断言（40×16 有界、compact 两行有界、CJK 截断、组合字符不劈开、控制字符不落地、三种尺寸下选择项可见、详情区有界、详情区分页滚动、宽屏双栏有界）。

## 修复后

```
py -3.11 -m unittest tests.test_terminal_views -v   → Ran 26 tests, OK
py -3.11 -m unittest tests.test_v3_g0_baseline -v   → Ran 11 tests, FAILED (failures=4)
py -3.11 -m unittest discover -s tests -v           → Ran 98 tests, failures=4, errors=0, skipped=0
py -3.11 -m unittest test_hkg_flight -v             → Ran 89 tests, OK
ruff check hkg_flight tests test_hkg_flight.py cleanup_alerts.py → All checks passed!
py -3.11 -m unittest tests.test_terminal_textual -v → Ran 5 tests, OK
```

关键输出（40×16，`destination="北京"*12`）：

```
[40] |COMPACT                                 |
[40] |----------------------------------------|
[40] |  CX100        00:00    Scheduled       |
[40] |   北京北京北京北京北京… --      TT1    |
```

详情区分页（ALERTS 详情，80×16，available=13，共 15 行）：

```
scroll=0 → 12 行 + "… 3 more"
scroll=6 → 从 "Raised: …" 开始，尾部完整可见
```

**R08：PASS**（同一路径，FAIL → PASS）
**R02：FAIL**（根因在 `presenter.py`，超出本阶段边界，按要求保留 FAIL，未做任何掩盖）
**R07：PASS**（冻结前 PASS，修复后 PASS；`[bold red]` 注入仍被剥离）

## R01/R05/R06/R09 保留状态

`discover -s tests` 的 4 项失败恰为 R01 / R02 / R06 / R09，与修复前的红灯集合相比只少了 R08；无任何红灯被删除、skip、放宽或改写：

| 项 | 状态 | 说明 |
|---|---|---|
| R01 `test_r01_session_snapshot_is_deeply_isolated` | FAIL | 保留 |
| R02 `test_r02_mutable_flight_fields_do_not_change_entity_id` | FAIL | 保留（根因在 presenter.py） |
| R03/R04/R05/R10（含 r10_scenarios 5 项） | PASS | G1a/G1b 成果未回退 |
| R06 `test_r06_empty_api_success_is_zero_in_plain_mode` | FAIL | 保留 |
| R07 `test_r07_external_markup_is_literal` | PASS | 未受影响 |
| R08 `test_r08_display_cell_width_is_bounded` | **PASS**（本次修复） | FAIL → PASS |
| R09 `test_r09_airline_page_search_is_reachable` | FAIL | 保留 |

## 核心/终端回归

- 核心 `test_hkg_flight`：Ran 89 OK（与 G1b 后一致，无新增失败）。
- 终端：`test_terminal_views` 26 OK（原 11 → 26，原 11 项全部保留并加强）、`test_terminal_textual` 5 OK、`test_terminal_session` 11 OK、`test_terminal_feed` 11 OK、`test_terminal_state` 15 OK、`test_terminal_plain` 5 OK、`test_terminal_entrypoint` 4 OK。
- `discover -s tests`：Ran 98 / failures=4（修复前为 Ran 83 / failures=5，新增 15 项测试，R08 清零）。
- Ruff：All checks passed。

## 未验证/阻塞

1. **R02 需另开阶段**：必须改 `presenter.py` 的 `ROW_ID_FIELDS` / `row_identity()`（把 gate/stand/aisle/hall/belt/status 等可变字段移出身份，改用 date+type+flight_number+time+origin/destination+airline_code+all_flight_numbers 之类的稳定键），并同步 `state.reconcile` 与相关测试。本阶段未触碰。
2. **详情区滚动尚未接线**：`body_lines(..., detail_scroll=N)` 已在渲染层可用并有直接断言，但 `state.py` 的 `move` 在 `detail_id` 打开时直接 return（state.py:154），没有任何按键会改变 detail_scroll。要真正可交互，需要在 state/textual_app 中新增滚动动作——超出本阶段边界，建议并入 G3a。
3. **R13 手工项未做**：未做真实 Windows Terminal / IME 的人工验证，本报告不声称任何终端实测证据。
4. **`build/` 目录**：仅作为修复前字节副本来源被读取，未修改。

## 未触碰

`poller.py`、`session.py`、`state.py`、`presenter.py`、`textual_app.py`、`plain.py`、API、缓存、告警、Web 契约、依赖、用户数据；未 reset、clean、stash、提交或推送。

## 是否建议进入 G3a

**建议进入**，但仅限主 agent 决定。建议 G3a 优先处理 R02（presenter.py 稳定实体 ID），并把「详情区滚动接线」作为同一批或紧随其后的子项——渲染层已经就绪，只差状态层的一个滚动动作。

## 是否提交/推送

**否。** 本次未执行任何 git 提交或推送。
