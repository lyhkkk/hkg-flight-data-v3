# V3-G1a Poller 修复报告

生成时间：2026-09-10 02:4x（GMT+8）
执行环境：Windows 原生，解释器 `py -3.11` → Python 3.11.9
（`C:\Users\avery\AppData\Local\Programs\Python\Python311\python.exe`）
工作目录：`O:\lyh\Projects\hkia\hkg-flight-data-v3`

```text
V3-G1a Poller 修复报告
范围：poller.py、feed 测试/夹具
修复前：命令、解释器、失败测试和关键断言
根因：
最小修复：文件、符号、行为不变量
修复后：同一命令、测试计数、关键输出
R03：PASS/FAIL/BLOCKED/NOT RUN
R04：PASS/FAIL/BLOCKED/NOT RUN
R10：PASS/FAIL/BLOCKED/NOT RUN
保留的其他红基线：
全量回归：
R05 Session 缺口：
未验证/阻塞：
未触碰：
是否进入 G1b：仅由主 agent 根据报告决定
是否提交/推送：必须为否
```

## 范围

- 修改：`hkg_flight/poller.py`、`tests/test_terminal_feed.py`（feed 测试，允许范围）
- 未修改任何 Session / Adapter / Textual / plain / views / state / presenter / API / 缓存 / 告警持久化 / Web 契约 / 依赖 / 用户数据
- 未 reset / clean / stash / commit / push

## 修复前（冻结红灯，未先改生产代码）

命令与结果（同解释器 `py -3.11`）：

| 命令 | 结果 |
| --- | --- |
| `py -3.11 -m unittest tests.test_v3_g0_baseline -v` | Ran 11 tests — **FAILED (failures=8)** |
| `py -3.11 -m unittest tests.test_v3_g0_r10_scenarios -v` | Ran 6 tests — **FAILED (failures=2)** |
| `py -3.11 -m unittest discover -s tests -p "test_v3_g0_*.py" -v` | Ran 17 tests — **FAILED (failures=10)** |

关键失败断言：

- R03 `test_r03_pending_requests_are_coalesced`：
  第二次 `poller.request_refresh()` 返回 `'accepted'`，期望 `'already_running'`（重复 pending 未合并）。
- R04 `test_r04_closed_refresh_cannot_publish_late_result`：
  `AssertionError: Lists differ: [{'key': '2026-09-09_100', ...}] != []`
  —— Poller close 后迟到结果仍发布到 `snapshot()["records"]`。
- R10 跨日 `test_r10_stale_midnight_result_cannot_overwrite_new_date`：
  `AssertionError: '2026-09-09' != '2026-09-10' : stale 2026-09-09 result overwrote the new date`。
- R10 逆序 `test_r10_out_of_order_completion_is_discarded`：
  `AssertionError: 2 != 1 : late result re-ran alert detection`。

修复前全量对照（同源码副本隔离运行，`build/lib/hkg_flight/poller.py` 与修复前工作树 `poller.py` 逐字节一致，md5 `7bcd3ac1eaee2243c9c301fe70f534b7`）：
`py -3.11 -m unittest discover -s tests` → **Ran 75 tests, FAILED (failures=10)**。

## 根因

1. **刷新槽所有权不全**：`request_refresh()` 只判断 `_refreshing`，不判断 `_refresh_pending`，重复的 pending 请求被当成新请求接受（R03）。
2. **刷新状态从不复位**：`_do_refresh()` 把 `_refreshing` 置 True 后，没有任何路径（成功 / 空成功 / 缓存回退 / 异常 / 关闭）把它复位，刷新槽永久占用。
3. **没有发布门**：`_do_refresh()` 拿到结果后无条件覆盖发布，既不比较 generation / 启动序号，也不比较请求日期，更不检查 closed，因此跨日旧结果覆盖新日期、逆序结果回退、close 后迟到结果照发（R10 / R04）。
4. **告警检测在发布门之外**：任何结果都会跑一遍 `alert_manager.process_flight`，迟到结果重复触发告警、二次抬高 alert revision（R10 逆序）。

## 最小修复：文件、符号、行为不变量

`hkg_flight/poller.py`：

- `Poller.__init__`：新增 `_generation`（已发出的刷新序号）、`_published_generation`（拥有当前快照的刷新序号）。
- 新增 `_set_refreshing_locked(value)`：只翻转快照里的 `refreshing` 位。
- 新增 `_reset_refresh_state()`：复位 `_refreshing` 与 `snapshot["refreshing"]`。
- 新增 `_is_stale_locked(generation, date_str, has_records)`：closed / 旧 generation / 旧日期 → 判旧。
- 新增 `_claim_publish_locked(generation, date_str, has_records)`：在告警检测之前抢占发布槽。
- `_do_refresh()`：启动时登记 generation 与请求日期、closed 早退、清 pending；结果出来后**先 claim，再告警，再发布**；发布前在锁内二次校验（closed + `_published_generation == generation`）；`finally` 复位刷新状态；统一返回当前已发布记录。
- `request_refresh()`：`_refreshing or _refresh_pending` 均视为槽已占用 → `already_running`。
- `stop()`：`_published_generation = _generation`，在飞刷新一律判旧。

`tests/test_terminal_feed.py`：

- 新增 `test_refresh_slot_is_released_after_completion`：锁住"刷新完成后刷新槽必须释放"这一不变量（`refreshing` 为 False、`request_refresh()` 再次返回 `accepted`）。

行为不变量：

- 一次刷新 = 一个 generation；仅当「未关闭 ∧ generation ≥ 已发布 generation ∧ 请求日期 ≥ 已发布 `records_date`」才允许发布。
- 旧 / 迟到 / 关闭后的结果**整包丢弃**：不动 `records`、`records_date`、`revision`、`last_api_success_at`、告警基线。
- 告警检测与发布共用同一道门，迟到结果不会重跑告警。
- 异常、空成功、缓存回退、关闭、丢弃五条路径都在 `finally` 中复位刷新状态。
- 公开契约不变：`request_refresh()` 仍只返回 `accepted` / `already_running` / `closed`；`snapshot()` 键集不变；API `[]` 仍为空成功而非错误；`refresh_today()` 仍返回记录列表；未用粗锁包网络请求、未清空 selection、未改业务日期语义。

## 修复后（同一命令）

| 命令 | 结果 |
| --- | --- |
| `py -3.11 -m unittest tests.test_v3_g0_r10_scenarios -v` | **Ran 6 tests — OK** |
| `py -3.11 -m unittest tests.test_v3_g0_baseline -v` | Ran 11 tests — FAILED (failures=6) |
| `py -3.11 -m unittest discover -s tests -p "test_v3_g0_*.py" -v` | Ran 17 tests — FAILED (failures=6) |
| `py -3.11 -m unittest test_hkg_flight -v` | **Ran 89 tests — OK** |
| `py -3.11 -m unittest discover -s tests -v` | Ran 76 tests — FAILED (failures=6) |
| `ruff check hkg_flight tests test_hkg_flight.py cleanup_alerts.py` | **All checks passed!** |

稳定性：`tests.test_v3_g0_r10_scenarios` + `tests.test_v3_g0_baseline` 连续复跑 10 轮，结果恒为 `FAILED (failures=6)`（6 条均为保留红基线），无 flaky。

回归对照：修复前 75 测试 / 10 失败 → 修复后 76 测试 / 6 失败（+1 为新增 feed 测试）。转绿的恰好是 R03、R04、R10×2 四条，无一条既有红灯被删、skip、放宽或改写，也未新增失败。

## R03：PASS

`test_r03_pending_requests_are_coalesced` 转绿：`accepted` → `already_running`。

## R04：PASS

`test_r04_closed_refresh_cannot_publish_late_result` 转绿：close 后 `snapshot()["records"] == []`。

## R10：PASS

- `test_r10_stale_midnight_result_cannot_overwrite_new_date` 转绿：`records_date` 保持 `2026-09-10`，记录为 `["200"]`，`last_api_success_at` 未被旧结果覆盖，告警 revision 未变。
- `test_r10_out_of_order_completion_is_discarded` 转绿：迟到结果未重跑告警（revision 1 == 1），`gate` 保持 `"2"`，`last_api_success_at` 保持 `2026-09-10T00:00:05`。

## 保留的其他红基线（未删 / 未 skip / 未放宽 / 未改写）

- R01 `tests.test_v3_g0_baseline...test_r01_session_snapshot_is_deeply_isolated` — FAIL
- R02 `tests.test_v3_g0_baseline...test_r02_mutable_flight_fields_do_not_change_entity_id` — FAIL
- R05 `tests.test_v3_g0_baseline...test_r05_airline_worker_cannot_publish_after_session_close` — FAIL
- R06 `tests.test_v3_g0_baseline...test_r06_empty_api_success_is_zero_in_plain_mode` — FAIL
- R08 `tests.test_v3_g0_baseline...test_r08_display_cell_width_is_bounded` — FAIL
- R09 `tests.test_v3_g0_baseline...test_r09_airline_page_search_is_reachable` — FAIL

## 全量回归

- 核心 `test_hkg_flight`：Ran 89 — OK（无回归）。
- 终端 `discover -s tests`：Ran 76 — 6 失败，全部为上述保留红基线（无回归）。
- Ruff：All checks passed!
- 本次仅 `hkg_flight/poller.py`、`tests/test_terminal_feed.py` 两个文件有新改动（按 mtime 核对确认）。

## R05 Session 缺口（未修复、未混入本阶段）

`hkg_flight/terminal/session.py::_load_airlines` 没有 closed 判断：Session `close()` 之后 airline worker 仍写入 `self._airlines` / `_airlines_loaded`，
表现为 `test_r05_airline_worker_cannot_publish_after_session_close` 的 `AssertionError: True is not false`。
这是 Session worker 问题，不属于 Poller 根因，本次按指令未触碰 `session.py`，留给 G1b。

## 未验证 / 阻塞

- R13 真实 Windows 人工证据仍缺失（不阻止本阶段自动化 Poller 修复，未伪造任何通过）。
- 未在 WSL 复跑（本阶段按指令 Windows 原生优先，已取得 Windows 原生证据）。
- 仅使用只读 git 命令（`git status` / `git diff` / `git show`）核对改动范围；**注意 HEAD 里的 `poller.py` 远旧于工作树**（V3 重建未提交），不能当作修复前基线，本报告的修复前对照使用的是与工作树逐字节一致的 `build/lib/hkg_flight/poller.py` 副本，在隔离目录 `.workbuddy-ai/tmp_g1a/orig` 中运行（该临时目录已清理）。

## 未触碰

`hkg_flight/terminal/session.py`、Textual / plain / views / state / presenter、`api.py`、`cache.py`、`alerts.py`、`web.py`、`cli.py`、依赖声明与 Python 支持范围、缓存与告警持久化格式、Web HTTP 契约、用户缓存与状态文档；
未执行 reset / clean / stash / commit / push；未重写 TUI、未引入新事件总线或新运行时依赖。

## 是否进入 G1b

由主 agent 根据本报告决定。
本 agent 的建议：**是** —— Poller 侧 R03 / R04 / R10 已收敛且全量无回归，剩余 6 条红灯分布在 Session（R05）、plain（R06）、views/presenter（R01/R02/R08）、Textual adapter（R09），需要 G1b 在各自边界内单独处理。

## 是否提交 / 推送

**否。** 本次未执行任何 commit / push。
