# V3-G1b Session 生命周期修复指令

**执行环境：** Windows 原生优先

**项目路径：** `O:\lyh\Projects\hkia\hkg-flight-data-v3`

**WSL 路径：** `/mnt/o/lyh/Projects/hkia/hkg-flight-data-v3`

## 目标

在 G1a Poller 已完成 R03/R04/R10 收敛后，修复 Session 生命周期和资源所有权问题，重点处理 R05。只修改 Session 边界，不混入 Poller、Views、Textual Adapter 或 plain 修复。

## 允许修改范围

只允许修改：

- `hkg_flight/terminal/session.py`
- `tests/test_terminal_session.py`
- 必要的 Session 测试夹具或仅用于验证的 Session 测试文件

如必须修改其他文件才能保持公共契约，先停止并报告，不自行扩大边界。

禁止修改：

- `hkg_flight/poller.py`
- `views.py`、`state.py`、`presenter.py`
- `textual_app.py`、`plain.py`
- `api.py`、`cache.py`、`alerts.py`
- Web HTTP 契约、依赖声明、Python 支持范围、用户数据和用户缓存

不得 reset、clean、stash、提交或推送；不得重写整套 TUI；不得引入新事件总线、DI 或新运行时依赖。

## 一、修复前冻结

先在不修改生产代码前执行：

```bat
cd /d O:\lyh\Projects\hkia\hkg-flight-data-v3
py -3.11 -m unittest tests.test_v3_g0_baseline -v
py -3.11 -m unittest tests.test_terminal_session -v
py -3.11 -m unittest discover -s tests -p "test_v3_g0_*.py" -v
```

确认并记录 R05 原始失败：

```text
Session close 后航空公司 worker 仍可发布结果；
_airlines_loaded 变为 True 或 _airlines 被写入；
期望 close 后无后写。
```

如果 `py -3.11` 不可用，使用已确认的绝对 Python 3.11 路径并记录；不得用 Python 3.14 替代正式目标证据。

## 二、Session 修复不变量

最小修复必须满足：

1. `Session.close()` 建立关闭门，关闭后所有 owned worker 的迟到结果丢弃；
2. 航空公司 worker 必须由 Session 持有并可观察其句柄、完成状态和异常；
3. close 期间阻塞的航班、航司和 Web worker 按现有资源模型释放；不得以 daemon 线程代替清理；
4. 重复 `close()` 幂等，不产生后写，不覆盖既有失败；
5. close 顺序先阻止新发布，再停止/等待 Session 所有资源，最后通知 UI/调用方状态；
6. 航司加载成功、失败、空结果和重试都必须经过 close/generation 门；
7. Web 启动失败、busy-port、启动中 close 和立即 restart 状态真实可观察；不得假报 ON；
8. Poller 的 R03/R04/R10 修复保持不变，不在本阶段重复修改 Poller；
9. 不改变 Web HTTP 契约、缓存/告警格式或现有公共 Session 调用契约。

## 三、修复后同一路径验证

使用同一解释器和同一测试路径：

```bat
py -3.11 -m unittest tests.test_v3_g0_baseline -v
py -3.11 -m unittest tests.test_terminal_session -v
py -3.11 -m unittest discover -s tests -p "test_v3_g0_*.py" -v
py -3.11 -m unittest test_hkg_flight -v
py -3.11 -m unittest discover -s tests -v
ruff check hkg_flight tests test_hkg_flight.py cleanup_alerts.py
```

要求：

- R05 同一路径由 FAIL 转为 PASS；
- R03/R04/R10 必须保持 PASS；
- R01/R02/R06/R08/R09 必须保留原红基线，不得删除、skip、放宽或改写；
- 核心 89 tests 不得回归；
- 终端测试新增失败必须说明根因；
- 重复 close、阻塞 worker、迟到发布、Web busy-port/close/restart 需有直接测试输出。

如果 Textual 或真实 Windows 终端缺失，只记录环境 BLOCKED/NOT RUN，不伪造人工验收。

## 四、停止条件

立即停止并报告，不自行扩大实现：

- 需要修改 `poller.py` 才能修 Session；
- 需要修改 Views/State/Presenter/Adapter 才能完成 R05；
- 需要改变刷新返回值、Web HTTP 契约、缓存/告警格式或业务日期；
- 需要删除或放宽 R01/R02/R06/R08/R09 红基线；
- 需要恢复旧 curses/simple 路径；
- 需要引入新运行时依赖、事件总线或 DI；
- 无法保证 close 后无后写；
- 需要真实 Windows Terminal/IME 才能完成代码级 Session 证明（此项应拆为 BLOCKED 人工证据，不得伪造）。

## 五、固定回报格式

```text
V3-G1b Session 修复报告
范围：session.py、Session 测试/夹具
执行环境：Windows 原生 / shell / Python 绝对路径
修复前：命令、退出码、测试计数、R05 失败断言
根因：
最小修复：文件、符号、资源所有权与关闭门
修复后：同一命令、退出码、测试计数、关键输出
R05：PASS/FAIL/BLOCKED/NOT RUN
R03/R04/R10 保持状态：
核心回归：
终端回归：
R01/R02/R06/R08/R09 保留红基线：
Web 生命周期：
未验证/阻塞：
未触碰：
是否建议进入 G2/G3：仅由主 agent 决定
是否提交/推送：必须为否
```
