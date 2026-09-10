# TUI V3 多代理实施交接

状态：供下一次已获实施授权的会话使用；不是产品完成声明。详细规格唯一归属 [TUI-REBUILD-REPORT-v3.html](TUI-REBUILD-REPORT-v3.html)，生命周期唯一归属 [architecture note](.agents/notes/proposed/architecture/2026-09-09-tui-rebuild.md)。

## 新会话启动指令

```text
请先完整阅读 AGENTS.md、TUI-REBUILD-REPORT-v3.html、TUI-REBUILD-MULTI-AGENT-HANDOFF-v3.md 与唯一 proposed architecture note，然后按 V3-G0-P→G0→G5 实施现有 TUI 候选的反例驱动修复：先完成 Python 运行时与测试前置门，明确 READY/PARTIAL/BLOCKED；主 agent 负责阶段契约、跨模块合并和 A1→A14 证据账本；仅按本文的文件边界委派，最多两项写入任务并行，Poller→Session→Adapter 必须串行；每项先用生产接口或实际 Adapter 固定修复前失败，再做最小根因修复并用同一证据转绿，保留工作树和既有有效实现，不重生成整套应用、不改变业务或持久化契约、不自动提交推送；自动化可验证部分可在 G0-P 为 PARTIAL 时继续，但最终平台/人工证据未完成不得进入完成声明；任一停止门、支持边界或范围变更立即停止并报告，未执行、跳过和人工验收缺口如实记录。
```

## 主 agent 的不可委派职责

- G0 开始前记录候选工作树摘要、解释器/依赖版本和已知反例的真实基线；不得 reset 或清理他人改动。
- 在每一门冻结接口与测试预期，合并跨模块改动；只在对应证据真实闭合后推进下一门。
- 维护 A1–A14 证据账本，区分 `PASS`、`FAIL`、`BLOCKED`、`NOT RUN`、`INSPECTED`；不以测试总数、CI 配置或 agent 结论代替直接证据。
- 处理冲突、支持范围/预算变更和 Agent Note 生命周期；`proposed` 只能在 V3-G5 与必要人工验收完成后迁为 `implemented`。

## 委派顺序与边界

| 门 | 任务 | 建议模型 / 思考 | 允许改动 | 交付条件 |
|---|---|---|---|---|
| V3-G0-P | Python 运行时与自动化测试前置门：发现解释器、依赖、工作树和测试入口；执行基础编译、核心回归与终端测试前置检查；区分环境阻断和产品失败 | `gpt-5.6-terra` / high | 只读检查、仓外探针、必要测试夹具；不得修改生产代码、依赖声明或用户缓存；不得 reset/clean/stash | 输出 READY/PARTIAL/BLOCKED；记录 `py -0p`、Python 3.7/3.11/3.13、Textual/Ruff、compileall、unittest 与 TTY 事实；环境错误不得报告为产品 FAIL |
| V3-G0 | 将 R01–R13 转为可重复的修复前失败基线；只读核查平台/依赖事实 | `gpt-5.6-terra` / high | 对应测试、夹具或仓外探针；不改生产代码 | G0-P 为 READY 或有明确 PARTIAL 边界；每个反例的命令、失败断言、实际入口和未覆盖面 |
| V3-G1a | 修复 Poller：深隔离、单刷新所有权、日期/代次发布、健康语义 | `gpt-5.5` / high | `poller.py`、feed 测试及必要夹具 | 同一并发/跨日/嵌套修改反例由红转绿；API `[]` 与 `None` 语义明确 |
| V3-G1b | 修复 Session：航空 worker 所有权、关闭门、Web 生命周期、迟到发布 | `gpt-5.6-terra` / high | `terminal/session.py`、session 测试 | 阻塞 worker/端口失败/重复 close 的生产装配测试转绿 |
| V3-G2 | 修复文本字面安全、显示单元宽度、紧凑布局容量和选择可见性 | `gpt-5.6-terra` / high | `terminal/views.py`、最小共享工具、views 测试 | 控制码/markup/CJK/组合字符和 40×16 高宽反例转绿 |
| V3-G3a | 修复 Textual 实际焦点、按键映射、筛选、搜索、选择保持、非阻塞退出 | `gpt-5.5` / high | `terminal/textual_app.py`、必要 state/presenter 小改、Pilot 测试 | `run_test`/Pilot 覆盖真实 Widget、输入上下文、刷新和关闭；不能仅测 reducer |
| V3-G3b | 修复 plain：非 TTY 空成功、详情偏移、控制字符和有界分页 | `gpt-5.4-mini` / medium | `terminal/plain.py`、plain 测试 | 同一非 TTY/详情/安全反例转绿；不扩展为增强功能对等 |
| V3-G4 | wheel、运行时分层、平台、性能与真实终端验证 | `gpt-5.6-luna` / medium | 打包/CI/平台探针/性能记录/证据文件；不得改业务逻辑 | 实际执行矩阵、wheel 包外安装、性能采样、真实终端/IME 记录；缺失环境标记 BLOCKED，不得填 PASS |
| V3-G5 | 文档、A1–A14 证据账本和 lifecycle 收敛 | `gpt-5.6-luna` / medium | 当前文档/证据文件/Agent Note；不得改业务逻辑 | 文档与按键同步、完整证据回读、核心阻断为零；仅在必要人工验收完成后建议迁移 note |

## V3-G0-P 执行协议

### 目标解释器与命令

Windows 优先使用 Python Launcher，不直接假设 `python` 或 `python3` 存在：

```bat
cd /d O:\lyh\Projects\hkia\hkg-flight-data-v3
where py
where python
where python3
py -0p
py -3.7-32 --version
py -3.11 --version
py -3.13 --version
py -3.14 --version
```

记录解释器身份，不把命令不存在误报为产品失败：

```bat
py -3.11 -c "import sys,platform,os; print('executable=',sys.executable); print('version=',sys.version); print('platform=',platform.platform()); print('cwd=',os.getcwd()); print('stdin_tty=',sys.stdin.isatty()); print('stdout_tty=',sys.stdout.isatty())"
py -3.11 -c "import textual; print('textual=', textual.__version__)"
py -3.11 -c "import rich; print('rich=', getattr(rich, '__version__', 'imported'))"
```

基础与增强测试分层执行：

```bat
py -3.7-32 -m compileall -q hkg_flight cleanup_alerts.py
py -3.11 -m unittest test_hkg_flight -v
py -3.11 -m unittest discover -s tests -v
ruff check hkg_flight tests test_hkg_flight.py cleanup_alerts.py
```

若 Textual 可用，再单独执行真实增强测试；若解释器、依赖或命令不存在，记录为相应 lane 的 `BLOCKED`/`NOT RUN`，不能改报为产品 `FAIL`。测试断言失败才是产品 `FAIL`。Python 3.14 若存在，可作为额外 `EXTRA/INSPECTED` 辅助 lane 运行纯 Python 测试，但不得替代 3.11/3.13 增强目标或 3.7 基础兼容性证据。

### G0-P 结论

- `READY`：至少一个目标 Python 3.11 可执行，基础测试可启动，环境与产品失败已区分。
- `PARTIAL`：部分自动化 lane 可执行；允许继续可验证的 G0–G3，但缺失 lane 对应验收保持 `BLOCKED`/`NOT RUN`，不得进入最终完成声明。
- `BLOCKED`：无目标 Python、基础测试无法启动、无法重复执行或工作树无法安全保留；停止所有写入任务。

G0-P 必须输出：工作树/HEAD、解释器、依赖、TTY、每条命令的退出码和测试计数，以及 `PASS/FAIL/BLOCKED/NOT RUN` 分类。推荐固定回报格式：

```text
G0-P 前置环境报告：
工作目录：
HEAD：
工作树摘要：
解释器：py -3.7-32 / py -3.11 / py -3.13
依赖：textual / rich / ruff
基础检查：compileall / 核心 unittest / tests discover / Textual tests / Ruff
每项状态：PASS / FAIL / BLOCKED / NOT RUN
环境阻断：
产品失败：
下一步：
```

## 串行与并行规则

1. G0-P 必须先完成；若为 `BLOCKED`，不得启动任何写入 agent；若为 `PARTIAL`，只允许已具备直接证据路径的自动化 G0–G3，G4/G5 仍被环境门阻断。不要把“新测试”与修复混在同一无基线提交中。
2. G1a 完成并由主 agent 冻结 Poller 快照、刷新与关闭契约后，才开始 G1b；Session 完成后才开始任何 Adapter 改动。
3. G2 与 G3b 可在 G1b 后并行，前提是文件不重叠；G3a 必须在 G1b 后执行，且与 G2 协调共享文本/几何契约。
4. 同时最多两名写入 agent；每个任务只改表中列出的文件。需要跨边界时，停止并交给主 agent 拆分或合并。
5. 快速模型只承担机械测试补齐、打包/文档/CI 对照；并发、跨午夜、资源关闭和真实 Textual 行为不用低思考任务草率处理。

## 每个 agent 的固定回报格式

```text
范围：
修复前：<命令、失败断言、环境>
最小修复：<文件与根因>
修复后：<同一命令及结果>
未验证 / 阻塞：
未触碰：
```

不得报告“完成”而没有修复前失败与修复后同一路径的结果。真实 Windows 终端/IME、40 列可读性、NO_COLOR 与 30 分钟性能采样必须由主 agent 汇总实际记录；若不能执行，保持 `BLOCKED` 或 `NOT RUN`，不能由纯代码代理补写为通过。

## 停止门

### 自动化实施停止门

立即停止并报告，而非自行扩大实现，当出现以下任一情况：

- G0-P 为 `BLOCKED`，或没有可执行的目标 Python 3.11 与基础测试入口；
- 无法区分解释器/依赖环境错误与产品断言失败；
- 无法建立 R01–R06 的修复前失败或明确已被其他改动修复的直接证据；
- 工作树存在无法归属的冲突，或需要 reset/clean/stash 才能继续；
- 要改变 Python 支持层、40×16 支持边界、刷新返回值、缓存/告警格式、HKIA 业务日期、Web HTTP 契约或已宣传按键；
- 找不到稳定实体策略且局部兼容修复不足；
- 需要重写整套 TUI、恢复 curses/simple、引入通用事件总线、DI 或新运行时依赖；
- 核心 R/A 项仍失败。

### 最终验收与发布停止门

以下情况允许继续具备直接证据的自动化 G0–G3，但禁止 G4/G5 完成声明、禁止把对应项标为 PASS，也禁止迁移 Agent Note：

- 没有真实 Windows 终端或中文 IME 验收；
- 没有 40 列人工可读性、真实颜色、快捷键或终端恢复记录；
- 没有 30 分钟性能采样；
- Python 3.7/3.13 或 wheel 包外安装 lane 尚未执行；
- 真实平台/终端权限尚未取得。

上述项目必须保持 `BLOCKED` 或 `NOT RUN`，不能用 headless、CI 配置、历史测试总数或 agent 结论替代直接证据。

完成 V3-G5 前，本文件和 V3 报告均只描述拟议流程；不修改 Agent Note 为 `implemented`，不创建“implemented locally”等替代状态。

完成 V3-G5 前，本文件和 V3 报告均只描述拟议流程；不修改 Agent Note 为 `implemented`，不创建“implemented locally”等替代状态。
