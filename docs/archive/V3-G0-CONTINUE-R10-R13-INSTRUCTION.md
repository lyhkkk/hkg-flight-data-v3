# V3-G0 反例基线续执行指令（R10–R13）

**执行环境：** WSL

**项目绝对路径：** `/mnt/o/lyh/Projects/hkia/hkg-flight-data-v3`

## 目标

继续完成 V3-G0 只读反例基线，补齐 R10–R13 的直接证据或明确 `BLOCKED/NOT RUN` 原因。当前不得进入 G1，不得修改生产代码。

## 强制规则

- 所有项目路径使用 `/mnt/o/lyh/Projects/hkia/hkg-flight-data-v3`。
- 不得修改生产代码；允许新增或修改仅用于 G0 证据的测试、夹具或仓外探针，但不得借此修复实现。
- 不得修改依赖声明、业务契约、持久化格式、用户缓存或文档状态。
- 不得 reset、clean、stash、提交或推送。
- 不得启动 Poller、Session、Adapter 的生产写入 agent。
- 每项必须记录：实际入口、完整命令、修复前失败/结果、环境、未覆盖面。
- R10–R13 不能通过静态源码阅读、历史测试总数或 agent 推断替代直接证据。

## 一、先复核当前基线

```bash
P=/mnt/o/lyh/Projects/hkia/hkg-flight-data-v3

git -C "$P" status --short
git -C "$P" diff --check
git -C "$P" log -1 --format='%H %s'

/usr/bin/python3.11 -m unittest "$P/tests/test_v3_g0_baseline.py" -v
/usr/bin/python3.13 -m unittest "$P/tests/test_v3_g0_baseline.py" -v
ruff check "$P/hkg_flight" "$P/tests" "$P/test_hkg_flight.py" "$P/cleanup_alerts.py"
```

确认既有 R01–R09 失败数量与名称；不得修改这些失败断言来制造通过。

## 二、R10：跨日、generation、逆序和关闭后发布

使用现有 Poller/Session 的生产接口或实际发布 seam，建立可控时钟、阻塞请求和逆序发布测试，至少覆盖：

1. 23:59 请求在 00:00 后返回，旧日结果不得覆盖新日记录、revision、成功时间或告警；
2. 新 generation 先发布，旧 generation 后发布，旧结果必须被丢弃；
3. `close()` 后迟到 Poller 结果不得发布；
4. `close()` 后迟到航空 worker 结果不得发布；
5. closed 状态下新刷新请求被拒绝；
6. 跨日旧数据必须有明确日期/previous-date 表达，不能静默伪装成今日数据。

若当前实现失败，保留失败测试作为基线；若某项已通过，记录实际断言和命令，不报告为“整个 R10 通过”。

## 三、R11：入口、旧路径和打包隔离

只做验证，不修改生产代码：

1. 检查 `main([])`/`main([tui])` 是否经过真实 Session/Adapter 装配；不能 mock 掉整条链；
2. 在临时目录构建 wheel，不在源码目录生成持久产物；
3. 在源码树外创建临时 venv 或临时安装目标，验证安装包来源不是源码目录；
4. 基础 lane 用 Python 3.7 检查 compileall/import/CLI/Web/plain 可用性；
5. 增强 lane 用 Python 3.11/3.13 检查 Textual 可导入及 TCSS 是否存在于 wheel；
6. 检查旧 `CursesTUI`、`run_simple_tui`、`FakeCursesScreen` 和 `hkg_flight/tui.py` 不再有可达注册路径；历史文档引用不得误判为可达代码。

所有构建产物、venv、缓存放在 `/tmp` 或其他仓外临时目录；执行结束后可清理临时目录，但不得触碰项目工作树。若 wheel 构建需要缺失工具，记录 `BLOCKED`，不要修改 pyproject 或安装配置。

## 四、R12：性能与资源基线

在不修改生产代码的前提下，使用现有离线夹具/测试入口记录：

- 1000/100/100 规模夹具是否能建立；
- 至少 100 次导航、切页、筛选、输入反馈样本（若入口可达）；
- 至少 100 次快照发布可见延迟样本（若 seam 可达）；
- 线程数、进程内存、通知/命令队列长度；
- 退出恢复时间和资源最终退出时间；
- 若能执行，记录 0/5/10/15/20/25/30 分钟采样。

不能在当前 WSL 非 TTY 环境测量的终端人工性能，标记 `BLOCKED/NOT RUN`，不得以 headless 结果替代 A13。性能超预算如实标记 FAIL；没有样本不得标 PASS。

## 五、R13：平台和人工证据

记录当前明确缺口：

- WSL2 而非 Windows 原生；
- `stdin_tty=False`、`stdout_tty=False`；
- 无真实 Windows Terminal/IME 操作；
- 无截图/录像；
- 未验证中文输入法、颜色、快捷键、40 列人工可读性、终端恢复。

这些项目必须标记为 `BLOCKED` 或 `NOT RUN`。不要伪造 Windows 证据，不要把 WSL/仿真/headless 结果写成 A13 PASS。

## 六、G0 结束判定

返回 R10–R13 账本，并明确：

- `FAIL`：有直接命令和失败断言；
- `PASS`：有直接命令和通过输出；
- `BLOCKED`：环境/平台无法提供证据；
- `NOT RUN`：尚未执行并说明原因；
- `INSPECTED`：仅静态检查，不能替代行为证据。

只有 R10–R13 均已取得直接证据，或每项均有明确 `BLOCKED/NOT RUN` 记录且主 agent 明确批准，才可建议 G0 收敛。无论结果如何，本次不得启动 G1。

## 回报格式

```text
V3-G0 R10–R13 续执行报告
项目：/mnt/o/lyh/Projects/hkia/hkg-flight-data-v3
HEAD：
工作树/是否修改生产代码：
R01–R09 复核：
R10：命令、入口、结果、失败断言、状态
R11：命令、wheel/入口结果、缺口、状态
R12：样本、测量、原始数据位置、状态
R13：平台/人工证据、状态
PASS：
FAIL：
BLOCKED：
NOT RUN：
INSPECTED：
未验证：
G0 是否收敛：是/否
是否进入 G1：必须为否
下一步建议：
```
