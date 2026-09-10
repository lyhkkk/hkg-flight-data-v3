# V3-G3b plain 修复报告

范围：plain.py、plain 测试/夹具
修复前：命令、R06 失败断言
根因：
最小修复：
修复后：命令、计数、关键输出
R06：PASS/FAIL/BLOCKED/NOT RUN
R01/R02/R05/R08/R09 保留状态：
核心/终端回归：
EOF/NO_COLOR/控制字符/分页：
未验证/阻塞：
未触碰：
是否提交/推送：必须为否

---

## 范围

- `hkg_flight/terminal/plain.py`（唯一被修改的生产文件）
- `tests/test_terminal_plain.py`（唯一被修改的测试文件）
- 修复前复现用隔离目录（已删除）与取证脚本 `.workbuddy-ai/tmp_g2/run_suite.py`（工作区本地 agent 数据）

## 修复前

解释器：`py -3.11` → Python 3.11.9，Windows 原生。

```
py -3.11 -m unittest tests.test_v3_g0_baseline -v   → Ran 11 tests, FAILED (failures=4)
py -3.11 -m unittest tests.test_terminal_plain -v   → Ran 5 tests, OK
```

R06 失败断言：

```
FAIL: test_r06_empty_api_success_is_zero_in_plain_mode
  File "tests\test_v3_g0_baseline.py", line 123, in test_r06_...
    self.assertEqual(code, 0)
AssertionError: 1 != 0
```

**修复前复现（同一命令、隔离副本）**：用 `build/lib/hkg_flight/terminal/plain.py`
（md5 `81c4bdab643ed90485188ba174040119`，无 `from .views import`、无 `result_for`/`clamp_offset`，
即修复前字节副本）覆盖到隔离目录后重跑同一条命令 → 同样的 `AssertionError: 1 != 0`。

## 根因

1. **R06 — 用「行数」判定成功。** `run_plain()` 非 TTY 分支写的是
   `has_data = bool(snap["flights"]["records"])` / `return 0 if has_data else 1`。
   API 明确返回 `[]` 时 `source == "api"`、`last_error is None`、`last_api_success_at` 已更新——
   这是一次**成功的空结果**，但因为没有记录就被判成失败并返回 1。
2. **详情与分页边界未收敛。** `offset += page_size` / `offset = max(0, offset - page_size)`
   都不做上界钳制，`n` 可以翻到空页；`render_block` 也不钳制 offset，越界窗口直接输出空列表；
   `detail <N>` 用绝对下标，与当前页 offset 无关，翻页后行号与屏幕不一致。
3. **`print_block()` 丢 page_size。** 调用 `render_block(..., offset)` 时不传 `page_size`，
   TTY 模式永远用默认 20，与 `run_plain(page_size=…)` 不一致。
4. **输出边界没有净化。** 记录里的 `\x1b`/C0/C1 会被原样写进管道。
5. **EOF 覆盖不全。** `input_func` 抛 `StopIteration`（脚本化输入耗尽）不在
   `(EOFError, KeyboardInterrupt)` 里，会直接逃逸；`session.close()` 也不在 `finally` 中。

## 最小修复

只改 `plain.py`；`views.py` 仅被**导入**（`freshness` / `sanitize`）复用，未做任何修改：

1. **`result_for(snap)` → `(exit_code, label)`**：退出码只看「这次有没有成功交付一份数据集」，
   不看行数。
   - `source == "api"` 且无 `last_error` → **0**，标签 `OK (api)` / `OK (api returned no flights)`；
   - `source == "cache"` 且有记录 → 0，标签 `OK (cache fallback)`（API 报错时附 `; api error: …`）；
   - 有 `last_error` → 1，`ERROR (<error>)`；
   - `source == "memory"`（只有过期内存数据）→ 1；
   - `source == "none"` → 1，`ERROR (no data available)`。
   非 TTY 分支末尾打印 `Result: <label>`，五种状态在输出里可直接区分。
2. **`_status_line()` 复用 `views.freshness()`**：状态行尾部追加 `API OK / STALE / CACHE / ERROR /
   MANUAL / LOADING`，与 TUI 同一套词汇，STALE 与 MANUAL 不再混为一谈。
3. **`clamp_offset(offset, total, page_size)`**：钳到最后一页起始下标；`_flight_row_lines` /
   `_alert_lines` / `_airline_lines` / `n` / `p` / `detail` 全部走它，翻页不再出现空页。
4. **`detail <N>` 改为相对当前页**：`index = clamp_offset(offset) + N - 1`；越界时输出
   `No such row (this page shows rows A-B)` 而不是干巴巴的 `No such row`。
   `print_block()` 补传 `page_size`。
5. **输出边界净化**：新增 `_clean()`（先剥 ANSI CSI/OSC 及其参数，再交给共享 `sanitize()` 去
   C0/C1/DEL 与可疑 markup）与 `safe_out(out)` 包装器，`run_plain` 所有输出（TTY 与非 TTY）
   统一从这里出，外部控制字符无法落到管道上。
6. **有限退出**：`input_func` 的 `EOFError / KeyboardInterrupt / StopIteration` 与返回 `None`
   一律当作干净 EOF 退出 0；TTY 循环体套 `try/finally`，`session.close()` 在任何退出路径都执行。
7. **`main_plain()`** 去掉 `if "NO_COLOR": pass` 空块，改为注释说明：plain 天然无颜色，
   NO_COLOR 下信息量不变（状态行 + `Result:` 标签都是纯文本）。

## 修复后

```
py -3.11 -m unittest tests.test_terminal_plain -v   → Ran 22 tests, OK
py -3.11 -m unittest tests.test_v3_g0_baseline -v   → Ran 11 tests, FAILED (failures=3)
py -3.11 -m unittest discover -s tests -v           → Ran 115 tests, failures=3, errors=0, skipped=0
py -3.11 -m unittest test_hkg_flight -v             → Ran 89 tests, OK
ruff check hkg_flight tests test_hkg_flight.py cleanup_alerts.py → All checks passed!
```

关键输出（非 TTY，`page_size` 默认）：

```
8 flights  → code=0   Result: OK (api)
            HKG | Data date 2026-09-10 | Source API | API OK 2026-09-10T18:18:04 | MANUAL
API []     → code=0   Result: OK (api returned no flights)      ← R06
API raises → code=1   Result: ERROR (api_failed)
            HKG | Data date — | Source NONE | MANUAL
```

**R06：PASS**（同一路径，FAIL → PASS）

## R01/R02/R05/R08/R09 保留状态

| 项 | 修复前 | 修复后 | 说明 |
|---|---|---|---|
| R01 `test_r01_session_snapshot_is_deeply_isolated` | FAIL | FAIL | 保留 |
| R02 `test_r02_mutable_flight_fields_do_not_change_entity_id` | FAIL | FAIL | 保留（根因在 presenter.py，非本阶段） |
| R05 `test_r05_airline_worker_cannot_publish_after_session_close` | PASS | PASS | G1b 成果未回退 |
| R08 `test_r08_display_cell_width_is_bounded` | PASS | PASS | G2 成果未回退 |
| R09 `test_r09_airline_page_search_is_reachable` | FAIL | FAIL | 保留 |

`discover -s tests` 的 3 项失败恰为 R01 / R02 / R09。R03、R04、R05、R06、R07、R08、
R10（`test_r10_closed_poller_rejects_new_refresh`、`test_r10_previous_date_is_explicit`
及 `test_v3_g0_r10_scenarios` 5 项）全部 PASS。无红灯被删除、skip、放宽或改写。

## 核心/终端回归

- 核心 `test_hkg_flight`：Ran 89 OK（与 G2 后一致，无新增失败）。
- 终端：`test_terminal_plain` 22 OK（原 5 → 22，原 5 项全部保留）、`test_terminal_views` 26 OK、
  `test_terminal_textual` 5 OK、`test_terminal_session` 11 OK、`test_terminal_feed` 11 OK、
  `test_terminal_state` 15 OK、`test_terminal_entrypoint` 4 OK。
- `discover -s tests`：Ran 115 / failures=3（G3b 前为 Ran 115-17=98 / failures=4，
  新增 17 项 plain 测试，R06 清零）。
- Ruff：All checks passed。

> 说明：`tests/test_terminal_plain.py::test_non_tty_failure_returns_nonzero` 原本用
> `build_session(flights=[])`（API 返回 `[]`）构造"失败"，这正是 R06 要修的行为。
> 已把它改为**真正的失败**（`api.fetch_flights.side_effect = RuntimeError` 且无缓存），
> 断言 `code == 1` 与 `Result: ERROR (api_failed)` 保持不变。该测试属于本次允许的
> plain 测试范围，不在 R01/R02/R05/R08/R09 保留清单内。

## EOF/NO_COLOR/控制字符/分页

全部有直接断言（`TestPlainBoundedExit` / `TestPlainOutputSafety` / `TestPlainPaging`）：

- **EOF / Ctrl-C / 输入耗尽 / `None`**：4 项断言均以 code 0 退出，且退出后
  `session.poller.request_refresh() == "closed"`（证明 `finally` 里的 close 真的跑了）。
  特别地 `StopIteration`（`next(iter([]))`）现在被当作 EOF，不再逃逸出 `run_plain`。
- **NO_COLOR**：置 `NO_COLOR=1` 后非 TTY 运行，输出无 `\x1b`，且 `Result: OK`、
  `Departures` 等信息行仍在（信息可辨识）。
- **控制字符**：注入 `"OK\x1b[31mRED\x07\x9bEND"` 后，输出中不含 `\x1b` / `\x07` / `\x9b`，
  且连 CSI 参数残留 `[31m` 都没有（先剥 ANSI 再 sanitize）。
- **分页 / offset**：`clamp_offset` 单元测试 7 组（含空列表、负数、超界）；
  `n` 连按 4 次停在最后一页且该页非空；`p` 不会退到负 offset；
  `detail 1` 在翻页后指向当前页首行（断言 `Flight: <第 3 行航班号>` 存在、
  `Flight: <第 1 行航班号>` 不存在）；`detail 99` 输出 `No such row (this page shows rows 1-6)`；
  200 条数据 + `page_size=10` 的非 TTY 输出 ≤ 15 行（有界）。

## 未验证/阻塞

1. **cache fallback 的退出码只有单元级推理，没有端到端夹具**：`result_for` 对
   `source == "cache"` 有记录的情况返回 0，但本轮没有构造"API 失败 + 磁盘缓存命中"的真实
   Session 夹具来验证整条链路（`CacheSystem` 写盘 → poller 回退 → plain 退出码）。
   建议后续补一个 `test_terminal_plain` 夹具。
2. **STALE 没有端到端断言**：`_status_line` 现在会输出 `freshness()` 的结果，但测试只断言了
   `MANUAL`（`no_poll=True` 必然触发）。STALE 需要打桩 `last_api_success_at` 为旧时间戳，
   目前只靠 `views.freshness` 自身的既有测试覆盖。
3. **R13 手工项未做**：未做真实 Windows Terminal / 管道（如 `| more`、重定向到文件）的
   人工验证，本报告不声称任何终端实测证据。
4. **plain 的列宽仍是 `len()` 口径**：本次按最小范围只做了净化与退出码/分页修复，
   未把 plain 的定宽列改成 display-cell 口径（那属于 views/geometry 范畴）。
   CJK 字段在 plain 里仍可能列错位，不影响 R08（R08 只测 `views.body_lines`）。

## 未触碰

`poller.py`、`session.py`、`views.py`、`state.py`、`presenter.py`、`textual_app.py`、
API、缓存、告警、Web 契约、依赖、用户数据；未 reset、clean、stash、提交或推送。

（`views.py` 只被 `plain.py` 以 `from .views import freshness, sanitize` 导入复用，
修改量为 0。）

## 是否提交/推送

**否。** 本次未执行任何 git 提交或推送。
