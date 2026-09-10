# V3-G1a Poller 修复指令：R03/R04/R10

**执行环境：** Windows 原生优先；也可在已验证的 WSL Python 3.11 环境复现。

**项目路径：** `O:\lyh\Projects\hkia\hkg-flight-data-v3`

**WSL 路径：** `/mnt/o/lyh/Projects/hkia/hkg-flight-data-v3`

## 当前前提

V3-G0 已取得 R10 的直接红灯证据，但 G0 报告仍为未收敛；本阶段开始 V3-G1a Poller 最小根因修复。R10 当前已复现：跨日旧结果覆盖新日、逆序结果回退 gate、迟到结果重复告警；R04 close 后 Poller 结果仍发布。R05 属于 Session worker 问题，不在本阶段修改。

## 允许修改范围

只允许修改：

- `hkg_flight/poller.py`
- Poller/feed 相关测试、夹具和必要的 G0/G1 证据测试

不得修改：

- `terminal/session.py`
- Textual/plain/views/state/presenter
- API、缓存、告警持久化格式、Web HTTP 契约
- Python 支持范围、依赖声明、用户缓存和状态文档

不得 reset、clean、stash、提交或推送；不得重写整套 TUI；不得把 R05 的 Session worker 问题混入本阶段。

## 1. 修复前冻结

先执行相同红灯命令并保存原始输出；不得先改生产代码：

```bat
cd /d O:\lyh\Projects\hkia\hkg-flight-data-v3
py -3.11 -m unittest tests.test_v3_g0_baseline -v
py -3.11 -m unittest tests.test_v3_g0_r10_scenarios -v
py -3.11 -m unittest discover -s tests -p "test_v3_g0_*.py" -v
```

如果 Windows `py -3.11` 不可用，使用已确认的绝对解释器并记录路径。Python 3.13 本机缺失，不得把托管 3.13.14 宣称为正式 3.13 证据。

必须保留并确认这些修复前失败：

- R03：重复 pending refresh 未合并为 `already_running`；
- R04：Poller close 后迟到结果仍发布；
- R10：跨日旧结果覆盖新日期；
- R10：逆序旧结果回退 gate；
- R10：迟到结果重复运行告警检测。

## 2. 最小根因修复目标

在不改变既有公开返回契约的前提下，统一所有刷新入口的 Poller 协调器，并建立发布门：

1. 所有 `start`、`start_background`、`request_refresh`、`refresh_today` 和定时路径不得绕过同一刷新所有权；
2. pending/refreshing 已占用刷新槽时返回既有约定的 `already_running`，不得新增调用方未声明的返回值；
3. 每次刷新记录明确 generation/启动序号和请求日期；
4. 旧 generation、旧日期或逆序结果不得覆盖当前记录、`records_date`、revision、成功时间或告警状态；
5. `close()` 后所有迟到结果丢弃，不得发布或推进当前元数据；
6. 异常、空成功、缓存回退和关闭路径都必须在 finally 中复位内部刷新状态；
7. API `[]` 与 `None` 的既有语义保持不变，不把空成功变为错误；
8. 不用粗大锁包住网络请求，不用清空 selection 或改变业务日期语义规避问题。

如果需要修改超出 `poller.py` 或 feed 测试的文件，先停止并报告，不自行扩大边界。

## 3. 修复后同一路径验证

使用同一命令验证红转绿：

```bat
py -3.11 -m unittest tests.test_v3_g0_r10_scenarios -v
py -3.11 -m unittest tests.test_v3_g0_baseline -v
py -3.11 -m unittest discover -s tests -p "test_v3_g0_*.py" -v
py -3.11 -m unittest test_hkg_flight -v
py -3.11 -m unittest discover -s tests -v
ruff check hkg_flight tests test_hkg_flight.py cleanup_alerts.py
```

要求：

- R03/R04/R10 的同一失败断言转绿；
- R01/R02/R05/R06/R08/R09 的既有失败不得被删除、skip、放宽或改写；
- 全量核心和终端 suite 不得回归；
- 若测试失败，区分 Poller 根因、Session 未修复的 R05 和环境失败；
- 不得因 R13 真实 Windows 人工证据缺失而伪造通过，但 R13 不阻止本阶段自动化 Poller 修复。

## 4. 停止条件

立即停止并报告：

- 需要修改 Session 或 Adapter 才能完成 Poller 修复；
- 需要改变刷新返回值、业务日期、缓存/告警格式或 Web 契约；
- 无法保持 R01–R02、R05–R09 原有红基线；
- 需要重写整套 TUI、引入新事件总线或新运行时依赖；
- 需要使用托管 3.13 结果冒充正式 3.13 证据。

## 固定回报格式

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
