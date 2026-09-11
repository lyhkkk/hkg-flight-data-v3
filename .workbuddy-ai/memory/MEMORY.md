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
- 增强 UI 测试在未安装 Textual 时自动 skip。

## 文档约定

- `SPEC.md` 描述**实际系统**，不是实现约束。不要往里写"必须如何实现"的条款。
- 第三方 agent 的历史产物已归档在 `docs/archive/`，不要再往根目录堆积。

## 验证命令

```bash
python -m compileall -q hkg_flight tests cleanup_alerts.py test_hkg_flight.py
python -m ruff check .
python -m unittest discover -s . -p "test*.py"
```
