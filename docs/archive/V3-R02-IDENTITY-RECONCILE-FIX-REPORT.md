# V3-R02 identity/reconcile 修复报告

**执行环境：** Windows 原生（win32 / bash），`py -3.11` = Python 3.11.9
**项目路径：** `O:\lyh\Projects\hkia\hkg-flight-data-v3`
**执行时间：** 2026-09-10

---

## 范围

仅为稳定实体 ID 与 reconcile 连续性：

| 文件 | 类型 | 说明 |
|---|---|---|
| `hkg_flight/terminal/presenter.py` | 生产 | 身份契约、重复航段序号、过滤顺序 |
| `hkg_flight/terminal/state.py` | 生产 | `reconcile()` 匹配策略、可见降级 |
| `tests/test_terminal_state.py` | 测试 | 新增 14 个 identity/reconcile 用例 |
| `tests/fixtures/terminal/data.py` | 夹具 | 注入同日同方向重复航段样本 |

未触碰：`poller.py`、`session.py`、`textual_app.py`、`plain.py`、`views.py`、`api.py`、`cache.py`、`alerts.py`、`web.py`、依赖、用户数据、Web 契约、缓存格式、告警格式。

---

## 修复前

### 冻结方法

HEAD 远早于工作区（V3 重建未提交），因此用 `build/lib/hkg_flight/terminal/` 下的字节相同原始副本在隔离目录重建修复前环境：

```
.workbuddy-ai/tmp_r02/            ← hkg_flight/ + tests/ 全量拷贝
  hkg_flight/terminal/presenter.py ← build/lib 原始版  md5 046786f1a763415c00986ab1ae3b836a
  hkg_flight/terminal/state.py     ← build/lib 原始版  md5 16ce3bc4cec6a5cdd31c57dd453ba1a6
```

### 命令与结果

```
cd .workbuddy-ai/tmp_r02
py -3.11 run_suite.py before_r02 tests
```

```
before_r02  unittest.loader._FailedTest.test_terminal_state                                  ERROR
before_r02  test_v3_g0_baseline...test_r01_session_snapshot_is_deeply_isolated               FAIL
before_r02  test_v3_g0_baseline...test_r02_mutable_flight_fields_do_not_change_entity_id     FAIL
before_r02  test_v3_g0_baseline...test_r09_airline_page_search_is_reachable                  FAIL
before_r02  TOTAL ran=100 failures=3 errors=1 skipped=0
```

- `test_r02_mutable_flight_fields_do_not_change_entity_id` **FAIL**（R02 红灯）。
- `test_terminal_state` ERROR 是预期的：新增用例 import 了修复前不存在的符号（`MUTABLE_OPERATION_FIELDS` / `duplicate_ordinals`）。

### 修复前 `ROW_ID_FIELDS`

```python
ROW_ID_FIELDS = (
    "date", "type", "flight_number", "time", "origin", "destination",
    "gate", "stand", "aisle", "hall", "belt", "terminal",
    "status", "status_code", "airline_code", "all_flight_numbers",
)
```

可变运营字段 `gate / stand / aisle / hall / belt / terminal / status / status_code` **全部在身份里**。

### 修复前行为复现（同一脚本，隔离目录运行）

```
py -3.11 repro_r02.py
FAIL C1_mutable_fields_do_not_change_id :: id changed when mutating: aisle,belt,gate,hall,stand,status,terminal
PASS C2_duplicate_segments_have_distinct_ids :: rows=22 colliding ids=0
FAIL C2b_identical_twin_is_distinguishable :: rows=23 unique=22
FAIL C3_selection_survives_status_change :: selected_id=…|77||E|||T2|Boarding||ANA|NH104 expected=…|5||E||||Departed 08:54||ANA|NH104
PASS C3b_detail_still_points_at_same_flight
FAIL C3c_no_spurious_selection_lost_message :: message='Selected flight is no longer visible'
FAIL C4_selection_survives_reorder :: selected_id=…|T2|Departed||EVA|BR108 expected=…|T2|Delayed||EVA|BR108
PASS C5_deletion_shows_visible_degradation
SUMMARY failed=5/8
```

关键事实：

- 改 gate / status 后 ID 完全变成另一条，selection 因此失配，落回 `min(index, n-1)` 并**误报**"Selected flight is no longer visible"——航班还在列表里，只是 ID 变了。
- `C2` 通过只是巧合：样本里的重复航段恰好 stand/belt 不同，靠可变字段"碰巧"区分；把重复航段做成逐字段相同时（`C2b`）立刻碰撞，23 行只有 22 个唯一 ID。

---

## 稳定身份契约

**ID = 稳定排班字段 + （仅在必要时）确定性重复序号。**

**纳入 ID（稳定，全天不变）：**

`date` `type` `flight_number` `time` `origin` `destination` `airline_code` `all_flight_numbers`

这 8 个字段回答"这是哪一个航班"：业务日期、方向、主航班号、计划时间、起终点、执飞航司、完整代码共享投影。任一变化都视为**另一个实体**。

**排除（可变运营字段，写入 `MUTABLE_OPERATION_FIELDS` 并由测试锁定）：**

`gate` `stand` `aisle` `hall` `belt` `terminal` `status` `status_code`

登机口、停机位、行李转盘、航站楼、状态在一天内反复更新，进入 ID 会让同一航班在每次刷新后变成新实体。

**重复航段策略：**

- 稳定字段仍碰撞时（同日、同方向、同航班号、同时间、同航线、同航司），追加 `dup:<ordinal>`。
- `ordinal` 由 `duplicate_ordinals()` 在**已排序、未过滤**的整页上按稳定键顺序分配 `0,1,2…`，确定性。
- 排序键由稳定字段构成 → gate/status 变化不挪动序号。
- 在未过滤页上计算 → 搜索输入、航司筛选、状态筛选都不会挪动序号。
- **不是随机值，不是每次刷新的计数器**：同一数据集永远得到同一组序号。

**禁止手段（未使用）：** 拼回可变字段造"看似唯一"的 ID；清空 selection；随机 ID；按刷新次数递增的序号。

---

## 根因

1. **身份契约错误**：`ROW_ID_FIELDS` 把 8 个可变运营字段当作身份的一部分。原注释说明了动机——真实样本里同日同方向重复航段（同航班号同时间，仅 stand/belt/hall 不同）需要区分——但选错了手段：用可变字段换取唯一性，代价是每次运营更新都重建实体。

2. **过滤发生在身份计算之前**：`visible_rows()` 先 `filter_flights()` 再逐条算 ID。由于 ID 含可变字段，筛选本身不影响 ID，但**缺少重复序号**这一层意味着一旦可变字段被移出身份，重复航段就会碰撞——所以两处必须一起改。

3. **`reconcile()` 位置兜底当作身份兜底**：找不到旧 `selected_id` 时直接 `selected_id = rows[min(index, n-1)]["id"]`，把光标所在行的 ID 当成"新的选中实体"，并统一报 "no longer visible"。当真正的成因只是 ID 被重建时，这就是一次**静默错位**：光标没动，但选中的其实是同一条航班的新 ID，或者被邻行顶替；而当记录真被删除时，又无法与前者区分。

4. **无降级可观测性**：丢selection 后 `state` 上没有任何字段记录"丢了什么"，UI 无法说明"你原来选的航班没了"，只能显示另一条航班的详情。

---

## 最小修复

### `hkg_flight/terminal/presenter.py`

| 符号 | 改动 |
|---|---|
| `ROW_ID_FIELDS` | 收敛为 8 个稳定字段；新增 `airline_code` / `all_flight_numbers`，移除 8 个可变字段 |
| `MUTABLE_OPERATION_FIELDS` | 新增常量，显式记录被排除的可变字段，供测试断言"契约里没有它们" |
| `DUPLICATE_MARKER` | `"dup"` |
| `_stable_key(rec)` | 新增：稳定字段的元组形式，用于分组重复航段 |
| `row_identity(rec, duplicate_ordinal=0)` | 新增可选序号参数，非 0 时追加 `dup:<n>`；默认行为（单参调用）不变 |
| `duplicate_ordinals(records)` | 新增：在已排序整页上按稳定键分配 `0,1,2…`，确定性 |
| `matches_filters(rec, airline, status)` | 新增：把原 `filter_flights` 的逐条判定抽出来 |
| `filter_flights()` | 改为委托 `matches_filters`，行为不变 |
| `visible_rows()` | 在**排序后、过滤前**的整页上算 `ordinals`，再过滤并发出 `row_identity(rec, ordinal)` |
| `project_flight(rec, duplicate_ordinal=0)` | 同步新签名 |

`visible_rows` 核心：

```python
records = sort_flights(page_flights(snapshot, page_name))
ordinals = duplicate_ordinals(records)          # 未过滤 → 不受 search/filter 影响
tokens = tokenize(search_text)
for rec, ordinal in zip(records, ordinals):
    if not matches_filters(rec, airline=airline, status=status):
        continue
    if not match_record(rec, tokens):
        continue
    rows.append({"id": row_identity(rec, ordinal), "record": rec})
```

### `hkg_flight/terminal/state.py`

| 符号 | 改动 |
|---|---|
| `SELECTION_LOST_MESSAGE` | 新增常量 `"Selected flight is no longer available"` |
| `PageState.lost_selection_id` | 新增字段，默认 `None` |
| `reconcile()` | 按**稳定 ID** 匹配；命中则只更新 `selected_index`；未命中才降级 |
| `_switch_page()` | 切页时清 `lost_selection_id` |

降级路径（仅当实体真消失）：

```python
fallback = max(0, min(page.selected_index, n - 1))
state.lost_selection_id = page.selected_id      # 记录丢了什么
state.message = SELECTION_LOST_MESSAGE          # 可见降级
page.selected_index = fallback
page.selected_id = rows[fallback]["id"]         # 采用该行自己的 ID，绝不复用丢失的 ID
```

三条硬约束的落点：

- **不通过清空 selection 掩盖**：只要 `n > 0`，`selected_id` 永不为 `None`；`reconcile` 的 `n == 0` 分支沿用原语义。
- **不复用他人 ID**：降级时写入的是 `rows[fallback]["id"]`，是光标行的自有 ID；`lost_selection_id` 单独保留原 ID。
- **详情不被重新指向**：`state.detail_id` 由调用方维护，`reconcile` 从不改写它——删除后详情仍指向已消失的实体，渲染层据此显示 "Flight no longer available"，而不是悄悄换成另一航班。

### 测试

`tests/test_terminal_state.py` 16 → **30 OK**，新增两个类：

- `TestStableIdentity`（7）
  - `test_mutable_fields_are_excluded_from_the_contract` — `MUTABLE_OPERATION_FIELDS` 与 `ROW_ID_FIELDS` 无交集
  - `test_identity_ignores_every_mutable_field` — 逐个变异 8 个可变字段，ID 不变
  - `test_identity_changes_with_every_schedule_field` — 逐个变异 8 个稳定字段，ID 必变
  - `test_same_day_duplicate_segments_stay_distinct`
  - `test_duplicate_ids_survive_mutable_updates`
  - `test_duplicate_ordinals_are_deterministic` — 同页序号序列确定性 `[0,1,0,2]`
  - `test_identity_is_independent_of_search_filter` — 搜索/筛选不改变 ID

- `TestReconcileContinuity`（7）
  - `test_selection_survives_status_and_gate_change`
  - `test_selection_survives_reordering`
  - `test_selection_survives_search_typing`
  - `test_selection_survives_status_filter_when_flight_still_matches`
  - `test_reconcile_never_clears_selection_while_rows_exist`
  - `test_deleted_record_degrades_visibly_and_is_never_reused`
  - `test_detail_of_a_deleted_flight_is_not_repointed`

`tests/fixtures/terminal/data.py`：`make_flights(count>=30)` 追加两条同日同方向重复航段（不同的 stand/belt），让真实样本形状进入测试。

---

## 修复后

### 同一复现脚本

```
py -3.11 repro_r02.py
PASS C1_mutable_fields_do_not_change_id :: id changed when mutating: none
PASS C2_duplicate_segments_have_distinct_ids :: rows=22 colliding ids=0
PASS C2b_identical_twin_is_distinguishable :: rows=23 unique=23
PASS C3_selection_survives_status_change :: selected_id=2026-09-09|departure|NH104|04:44|HKG|BKK|ANA|NH104
PASS C3b_detail_still_points_at_same_flight
PASS C3c_no_spurious_selection_lost_message :: message=''
PASS C4_selection_survives_reorder :: selected_id=2026-09-09|departure|BR108|08:28|HKG|DXB|EVA|BR108
PASS C5_deletion_shows_visible_degradation :: message='Selected flight is no longer available'
SUMMARY failed=0/8
```

### 命令与计数

| 命令 | 结果 |
|---|---|
| `py -3.11 -m unittest tests.test_v3_g0_baseline -v` | Ran 11 — failures=2（R01、R09） |
| `py -3.11 -m unittest tests.test_terminal_state -v` | Ran 30 — **OK**（修复前 16） |
| `py -3.11 -m unittest tests.test_terminal_views -v` | Ran 26 — OK |
| `py -3.11 -m unittest tests.test_terminal_textual -v` | Ran 5 — OK |
| `py -3.11 -m unittest tests.test_terminal_entrypoint -v` | Ran 4 — OK |
| `py -3.11 -m unittest discover -s tests -v` | Ran 129 — **failures=2 errors=0**（修复前 100/3/1） |
| `py -3.11 -m unittest test_hkg_flight` | Ran 89 — OK |
| `ruff check hkg_flight tests test_hkg_flight.py cleanup_alerts.py` | **All checks passed!** |

`tests.test_terminal_plain` 未在上表单列，但已纳入 discover：22 OK。

### 重复航段实证

`make_flights_snapshot(40)` 到达页 22 行，其中 2 行带 `dup:1` 后缀：

```
2026-09-09|arrival|HX101|07:11|LHR|HKG|CRK|HX101|dup:1
2026-09-09|arrival|KA103|21:33|NRT|HKG|HDA|KA103|dup:1
all unique? True
ids stable after mutating stand/belt/status/gate/terminal/hall/aisle? True
```

---

## R02

**PASS**

`test_r02_mutable_flight_fields_do_not_change_entity_id` FAIL → OK。8 个可变字段逐个变异后 `row_identity()` 不变；8 个稳定字段逐个变异后必变。

---

## 重复航段

同日、同方向、同航班号、同时间、同航线、同航司的重复航段通过 `dup:<ordinal>` 稳定区分。`ordinal` 在已排序、未过滤的整页上分配，因此：

- 不随 gate/stand/belt/status 更新而挪动；
- 不随搜索输入、航司筛选、状态筛选而挪动；
- 不随刷新次数变化，同一数据集永远同一结果。

有直接测试：`test_same_day_duplicate_segments_stay_distinct`、`test_duplicate_ids_survive_mutable_updates`、`test_duplicate_ordinals_are_deterministic`、`test_identity_is_independent_of_search_filter`，外加复现脚本 `C2`/`C2b`。

---

## selection/detail/filter 连续性

| 场景 | 结果 |
|---|---|
| status + gate + terminal 同时变化 | `selected_id` 不变，`detail_id` 不变，`message` 为空 |
| 记录重排 | 按稳定 ID 重新定位 `selected_index`，仍是同一航班 |
| 搜索逐字输入 | ID 在未过滤页计算，不因 search 重建 |
| 状态筛选（该航班仍命中） | selection 保持 |
| 光标位置兜底 | 仅当稳定 ID 在整页中查不到时才触发 |

有直接测试：`TestReconcileContinuity` 7 个用例 + 复现脚本 `C3`/`C3b`/`C3c`/`C4`。

---

## 删除降级

记录真正消失时才降级，且**可见**：

- `state.message = SELECTION_LOST_MESSAGE`（"Selected flight is no longer available"）
- `state.lost_selection_id` 记录丢失的实体 ID，供 UI / 测试区分"被邻行顶替"与"仍在原处"
- 光标停在 `min(selected_index, n-1)`，并采用**该行自己的** ID，绝不复用丢失的 ID
- `state.detail_id` 不被 `reconcile` 改写 → 详情保留在已消失的实体上，渲染层显示 unavailable，而不是悄悄换成另一航班

反例已消除：航班仍在列表里时不再出现 "no longer visible"（复现脚本 `C3c` 修复前 FAIL / 修复后 PASS）。

有直接测试：`test_deleted_record_degrades_visibly_and_is_never_reused`、`test_detail_of_a_deleted_flight_is_not_repointed`、`test_reconcile_never_clears_selection_while_rows_exist`。

---

## R03/R04/R05/R08/R10 保持状态

全部 **PASS**，与 R02 修复前一致：

| 项 | 测试 | 状态 |
|---|---|---|
| R03 | `test_r03_pending_requests_are_coalesced` | OK |
| R04 | `test_r04_closed_refresh_cannot_publish_late_result` | OK |
| R05 | `test_r05_airline_worker_cannot_publish_after_session_close` | OK |
| R08 | `test_r08_display_cell_width_is_bounded` | OK |
| R10 | `test_r10_closed_poller_rejects_new_refresh`、`test_r10_previous_date_is_explicit` | OK |
| R10 | `test_v3_g0_r10_scenarios` 全部 5 个 | OK |
| R07 | `test_r07_external_markup_is_literal` | OK |

---

## R01/R06/R09 保留状态

| 项 | 状态 | 说明 |
|---|---|---|
| R01 | **FAIL（保留）** | `test_r01_session_snapshot_is_deeply_isolated` — 快照深隔离，属 `session.py`，本任务越界，未处理 |
| R06 | **PASS（保留）** | `test_r06_empty_api_success_is_zero_in_plain_mode` — G3b 已修复，本次无回归 |
| R09 | **FAIL（保留）** | `test_r09_airline_page_search_is_reachable` — `state.focus` 期望 `search` 实为 `list`，属 adapter 边界，未处理 |

红灯集合：修复前 5（R01/R02/R06/R08/R09）→ G2 后 4 → G3b 后 3 → **R02 后 2（R01、R09）**。

---

## 核心/终端回归

- `discover -s tests`：修复前 `ran=100 failures=3 errors=1` → 修复后 `ran=129 failures=2 errors=0 skipped=0`。**无新增失败**；用例数增加来自本次新增的 14 个 identity/reconcile 用例。
- `test_hkg_flight`：89 OK（全程未变）。
- `tests.test_terminal_state`：16 → 30 OK。
- `tests.test_terminal_views`：26 OK（G2 成果，未受影响）。
- `tests.test_terminal_plain`：22 OK（G3b 成果，未受影响）。
- `tests.test_terminal_textual`：5 OK。
- `tests.test_terminal_entrypoint`：4 OK。
- `ruff check hkg_flight tests test_hkg_flight.py cleanup_alerts.py`：`All checks passed!`

---

## 未验证/阻塞

1. **真实终端手工证据（R13）未做**。全部结论来自 unittest 与隔离目录复现脚本，未启动真实 TUI 肉眼确认。按约束不伪造此类证据。
2. **整页清空场景无降级提示**。当 `n == 0`（如筛选后无结果、或整页记录全被删）时，`reconcile` 沿用原语义：只把 `selected_id` 置 `None`，不设 `message`、不记 `lost_selection_id`。这里无法区分"该页本来就空"与"记录全被删除"——若强行加提示，切到一个空页会误报。属已知取舍，未改。
3. **跨业务日期行为未验证**。ID 含 `date`，跨日切换会换 ID（符合契约：另一天的航班是另一实体），但没有针对跨日的连续性测试。
4. **`build/lib` 作为原始基线**。HEAD 远早于工作区，原始副本取自 `build/lib`（md5 已记录）。若 `build/` 曾被本次 V3 修复之外的动作污染，冻结基线会偏移；未做二次交叉验证。
5. **重复序号依赖排序稳定性**。`duplicate_ordinals` 的正确性依赖 `sort_flights` 的键完全由稳定字段构成。已由 `test_duplicate_ids_survive_mutable_updates` 覆盖，但若将来给排序键加入可变字段，序号会开始漂移。

---

## 未触碰

`poller.py`、`session.py`、`textual_app.py`、`plain.py`、`views.py`、`api.py`、`cache.py`、`alerts.py`、`web.py`、`cli.py`、`utils.py`、`pyproject.toml`、依赖、用户数据、缓存格式、告警格式、Web 契约、对外 API。

---

## 是否提交/推送

**否。** 未执行 `git add` / `commit` / `push`，未执行 `reset` / `clean` / `stash`。改动全部留在工作区。

---

## 是否建议进入 G3a

由主 agent 决定。本报告只陈述事实：R02 已 FAIL → PASS，红灯集合收敛到 R01、R09 两项，均为本任务范围外（`session.py` 快照深隔离 / adapter 焦点语义）。
