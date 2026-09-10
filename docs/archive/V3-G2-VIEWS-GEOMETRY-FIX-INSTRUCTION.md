# V3-G2 Views / Geometry 修复指令

**执行环境：** Windows 原生优先

**项目路径：** `O:\lyh\Projects\hkia\hkg-flight-data-v3`

## 目标

处理 R08 display-cell 宽度、文本安全与紧凑布局；调查 R02 稳定实体 ID，但不得擅自跨越本阶段文件边界。R01 暂不处理。

## 允许修改

- `hkg_flight/terminal/views.py`
- 必要的最小共享显示工具
- `tests/test_terminal_views.py`
- Views/geometry 相关测试和夹具

如果 R02 根因实际位于 `state.py`、`presenter.py`、`session.py` 或 `textual_app.py`，只记录根因和建议，不修改这些文件；将 R02 保留为 FAIL，交由主 agent 另行拆分。不得修改 R01。

禁止修改：`poller.py`、`session.py`、`state.py`、`presenter.py`、`textual_app.py`、`plain.py`、API、缓存、告警、Web 契约、依赖、用户数据。

不得 reset、clean、stash、提交或推送；不得重写整套 TUI。

## 一、修复前冻结

```bat
cd /d O:\lyh\Projects\hkia\hkg-flight-data-v3
py -3.11 -m unittest tests.test_v3_g0_baseline -v
py -3.11 -m unittest tests.test_terminal_views -v
py -3.11 -m unittest tests.test_terminal_textual -v
```

确认并记录：

- R08 当前 display-cell 宽度失败；
- R02 当前稳定实体 ID 失败；
- R07 markup/控制字符保护仍通过。

## 二、最小修复目标

1. 使用 display-cell 宽度而非 `len()` 计算 CJK/组合字符/控制字符显示宽度；
2. 截断不得输出未闭合 markup、原始 ESC/C0/C1 控制码或破坏支持范围内的组合字符；
3. 40×16 和 resize 场景下 body 行数有界；
4. 两行 compact 数据时选择项可见；
5. 详情区域可滚动，不能通过无条件截断所有详情制造假通过；
6. 空态、计数、长字段和 previous-date 文本保持现有业务含义；
7. 如果调查发现 R02 必须修改生产状态/实体生成逻辑，停止修改并报告，不要在 views.py 中掩盖问题。

## 三、修复后验证

```bat
py -3.11 -m unittest tests.test_terminal_views -v
py -3.11 -m unittest tests.test_v3_g0_baseline -v
py -3.11 -m unittest discover -s tests -v
py -3.11 -m unittest test_hkg_flight -v
ruff check hkg_flight tests test_hkg_flight.py cleanup_alerts.py
```

要求：

- R08 同一路径 FAIL → PASS；
- R07 保持 PASS；
- R01、R02、R05、R06、R09 不得删除、skip、放宽或改写；
- R03/R04/R10 保持 PASS；
- 核心回归无新增失败；
- 40×16、CJK、组合字符、控制字符和选择可见性有直接断言。

## 固定回报

```text
V3-G2 Views/Geometry 修复报告
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
```
