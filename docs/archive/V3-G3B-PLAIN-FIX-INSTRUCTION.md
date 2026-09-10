# V3-G3b plain 模式修复指令

**执行环境：** Windows 原生优先

**项目路径：** `O:\lyh\Projects\hkia\hkg-flight-data-v3`

## 目标

修复 R06 plain 非 TTY 空成功退出码问题，并验证 plain 详情 offset、控制字符、EOF、NO_COLOR 和有界分页。只修改 plain 边界，不处理 R01/R02/R08/R09。

## 允许修改

- `hkg_flight/terminal/plain.py`
- `tests/test_terminal_plain.py`
- plain 相关测试、夹具和必要仓外探针

禁止修改：`poller.py`、`session.py`、`views.py`、`state.py`、`presenter.py`、`textual_app.py`、API、缓存、告警、Web 契约、依赖、用户数据。

不得 reset、clean、stash、提交或推送；不得重写整套 TUI。

## 一、修复前冻结

```bat
cd /d O:\lyh\Projects\hkia\hkg-flight-data-v3
py -3.11 -m unittest tests.test_v3_g0_baseline -v
py -3.11 -m unittest tests.test_terminal_plain -v
```

确认 R06 当前失败：API 返回 `[]` 的成功空结果在 plain 非 TTY 路径返回码不是 0。

## 二、最小修复目标

1. API `[]` 明确表示成功的空数据，plain 非 TTY 返回码为 0；
2. `None`/失败、cache fallback、STALE、MANUAL 错误和空成功保持可区分；
3. 详情 offset、n/p 边界和有界分页正确；
4. EOF/KeyboardInterrupt 有限退出；
5. 外部控制字符不会原样污染输出；
6. `NO_COLOR` 下信息仍可辨识；
7. 不扩展 plain 成为 Textual 功能对等，不修改 Poller/Session 契约。

## 三、修复后验证

```bat
py -3.11 -m unittest tests.test_terminal_plain -v
py -3.11 -m unittest tests.test_v3_g0_baseline -v
py -3.11 -m unittest discover -s tests -v
py -3.11 -m unittest test_hkg_flight -v
ruff check hkg_flight tests test_hkg_flight.py cleanup_alerts.py
```

要求 R06 FAIL → PASS；R01/R02/R05/R08/R09 保留；R03/R04/R10 保持 PASS；核心回归无新增失败。

## 固定回报

```text
V3-G3b plain 修复报告
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
```
