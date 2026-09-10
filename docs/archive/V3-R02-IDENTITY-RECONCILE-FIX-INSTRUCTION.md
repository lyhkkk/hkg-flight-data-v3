# V3-R02 稳定实体 ID 与 reconcile 修复指令

**执行环境：** Windows 原生优先

**项目路径：** `O:\lyh\Projects\hkia\hkg-flight-data-v3`

## 目标

修复 R02：航班 gate/status 等可变字段变化后，实体 ID 不应变化；同时保持同日同方向重复航段可区分、选择/详情/筛选可连续。R01 快照深隔离不在本任务处理。

## 允许修改

- `hkg_flight/terminal/presenter.py`
- `hkg_flight/terminal/state.py`
- `tests/test_terminal_state.py`
- `tests/test_terminal_views.py` 或必要的 identity/reconcile 测试夹具

如果必须修改 `session.py`、`poller.py`、`textual_app.py` 或其他边界文件，立即停止并报告，不自行扩大范围。

禁止修改：`poller.py`、`session.py`、`textual_app.py`、`plain.py`、`views.py`（除非主 agent 明确批准且仅为调用契约同步）、API、缓存、告警、Web 契约、依赖、用户数据。

不得 reset、clean、stash、提交或推送；不得用清空 selection 或强制重选掩盖身份不稳定。

## 一、修复前冻结

```bat
cd /d O:\lyh\Projects\hkia\hkg-flight-data-v3
py -3.11 -m unittest tests.test_v3_g0_baseline -v
py -3.11 -m unittest tests.test_terminal_state -v
py -3.11 -m unittest tests.test_terminal_views -v
```

确认 R02 当前失败：同一航班 gate/status 等字段变化导致 `row_identity()` 结果变化。

同时阅读并记录：

- `ROW_ID_FIELDS` 当前字段；
- `row_identity()` 的完整输入；
- `state.reconcile()` 如何匹配旧记录与新记录；
- 同日同方向重复航段如何区分；
- selection/detail/filter 当前依赖的字段。

## 二、先冻结稳定身份契约

在修改前写出并遵守明确策略：

- 身份只使用稳定字段，例如业务日期、方向/type、主航班号、计划时间、起点、终点、航司代码和完整代码共享投影；
- gate、stand、aisle、hall、belt、terminal、status、status_code 等可变运营字段不得进入 ID；
- 不能只用航班号，必须能区分同日同方向重复航段；
- 不得把可变字段拼回去形成“看似唯一”的不稳定 ID；
- 若稳定字段仍碰撞，记录明确的确定性重复序号/投影策略；不得使用随机值或每次刷新重新生成的序号。

如果真实样本无法支持稳定实体策略，停止并报告，不擅自选择方案。

## 三、最小修复目标

1. gate/status/stand 等可变字段更新时，实体 ID 保持不变；
2. 记录重排时，实体 ID、selection、detail 和 filter 结果保持连续；
3. 真正删除记录时，选择有可见降级，不错误复用其他航班；
4. 同日同方向重复航段仍可稳定区分；
5. state.reconcile 不通过清空 selection 规避问题；
6. Poller/Session R03/R04/R05/R10 行为保持不变；
7. 不改变业务日期、缓存格式、告警格式、Web 契约或对外 API。

## 四、修复后验证

```bat
py -3.11 -m unittest tests.test_v3_g0_baseline -v
py -3.11 -m unittest tests.test_terminal_state -v
py -3.11 -m unittest tests.test_terminal_views -v
py -3.11 -m unittest tests.test_terminal_textual -v
py -3.11 -m unittest tests.test_terminal_entrypoint -v
py -3.11 -m unittest discover -s tests -v
py -3.11 -m unittest test_hkg_flight -v
ruff check hkg_flight tests test_hkg_flight.py cleanup_alerts.py
```

要求：

- R02 FAIL → PASS；
- R03/R04/R05/R08/R10 保持 PASS；
- R01/R06/R09 保持原状态；
- 核心回归无新增失败；
- 同日重复航段、状态变化、重排、删除降级均有直接测试。

## 固定回报

```text
V3-R02 identity/reconcile 修复报告
范围：presenter.py、state.py、相关测试/夹具
修复前：命令、R02 失败断言、ROW_ID_FIELDS
稳定身份契约：
根因：
最小修复：文件、符号、匹配策略
修复后：同一命令、计数、关键输出
R02：PASS/FAIL/BLOCKED/NOT RUN
重复航段：
selection/detail/filter 连续性：
删除降级：
R03/R04/R05/R08/R10 保持状态：
R01/R06/R09 保留状态：
核心/终端回归：
未验证/阻塞：
未触碰：
是否提交/推送：必须为否
是否建议进入 G3a：仅由主 agent 决定
```
