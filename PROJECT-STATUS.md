# HKG Flight Data v3 — Project Status

> 最后更新: 2026-09-11

## 项目状态: ✅ 已通过第一性原理重构，测试与 lint 全绿

## 环境信息

| 项目 | 状态 |
|------|------|
| Python | 3.9+（基础包），3.11 / 3.13 为 CI 目标 |
| 依赖 | 基础包仅标准库；`.[tui]` 可选引入 Textual |
| 测试 | 222 用例通过（5 skipped：未安装 Textual 时的增强 UI 测试） |
| Lint | `ruff check .` 全部通过 |
| 数据源连接 | ✅ 实测（今日 417 departures / 415 arrivals） |

## 本轮重构 — 2026-09-11

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
python -m unittest discover -s . -p "test*.py"                                  # 222 tests, OK (skipped=5)
```

真实 API 冒烟（2026-09-11）：`departures` 417 条、`arrivals` 415 条、
`query CX261` / `query G63` / `query BA15` 三种模式行为正确，Web API 与 plain 非 TTY 输出正常。

## 已知问题

- 增强 UI 需要 `.[tui]`；未安装时相关测试自动跳过，本地无法验证 Textual 交互
- 40 列紧凑布局的可读性仍需真实终端人工确认
- 香港业务日期语义（Asia/Hong_Kong 统一）仍为独立待决项
- 告警历史保存时限制最近 500 条，可用 `cleanup_alerts.py` 按日期清理

## 后续建议

- [ ] 在装有 Textual 的环境跑一次增强 UI 测试与真机交互
- [ ] 如需跨重启的变更检测，重新设计 state 持久化（当前仅进程内快照）
- [ ] 考虑给 Web 仪表盘增加告警视图
