# HKG Flight Data v3 · 用户反馈登记

本文件按上级 AGENTS.md 仅登记用户诉求与授权范围，不维护运行状态或重复详细规格；运行状态归属 [PROJECT-STATUS.md](PROJECT-STATUS.md)，规划与决策归属下列报告及唯一 note。

## 2026-09-09 · V3 具体修复计划

- 用户原话：“非常好，v3设计的具体Plan可以动手生成”。
- 诉求：将第三方执行审查发现的问题转为 V3 具体修复/加固/验收计划，保留已有有效实现，提供单次发送的一句话开发 Prompt。
- 授权边界：本次仅生成规划文档与维护提案，不执行生产修复、不改测试/依赖/用户数据，不自动提交或推送。
- 规划交付：[TUI-REBUILD-REPORT-v3.html](TUI-REBUILD-REPORT-v3.html) / [配套 Prompt](TUI-REBUILD-PROMPT-v3.txt)。
- 唯一决策记录：[TUI architecture note](.agents/notes/proposed/architecture/2026-09-09-tui-rebuild.md)。该 note 负责生命周期，不以反馈登记代替验收。
- 产品落地与 commit：本次无产品实施、无 commit；后续授权实施并验证后在本条补充落地记录和真实引用，不预填完成声明。

## 2026-09-09 · 多代理实施交接

- 用户诉求：为新会话留下按阶段分配测试与实施任务的多代理指令。
- 交付：[TUI-REBUILD-MULTI-AGENT-HANDOFF-v3.md](TUI-REBUILD-MULTI-AGENT-HANDOFF-v3.md)，只规定委派顺序、文件边界、停止门和证据回报格式；详细技术规格仍以 V3 报告为唯一正文。
- 授权边界：本次只新增交接文档与登记，不执行产品修复、不改测试/依赖/用户数据，不自动提交或推送。

## 2026-09-09 · V3 实施授权

- 用户在审阅执行说明并暂停后明确回复：“approved”。
- 授权范围：按 V3 报告与多代理交接实施反例驱动修复；保留工作树，遵守阶段、文件边界和停止门，不自动提交或推送。
- 本次环境核查与停止证据：[V3 执行证据报告](TUI-REBUILD-EXECUTION-REPORT-v3.md)。此链接不表示阶段通过或产品完成；唯一 note 保持 proposed。

## 2026-09-09 · V3-G0-P 前置门调整

- 用户同意将 Python 运行时与自动化测试前置门纳入 V3 计划。
- 交付：[V3-G0-P 前置计划](V3-G0-P-PREFLIGHT-PLAN.md)。
- 交接文档已新增 `V3-G0-P → V3-G0 → G5` 流程、Windows Python Launcher 命令、READY/PARTIAL/BLOCKED 分类，以及自动化实施停止门与最终人工验收停止门。
- 本次仅修改计划、Prompt 与证据文档；未执行产品修复、未修改测试/依赖/用户数据、未提交或推送。

## 2026-09-09 · V3-G0-P 执行结果

- 在 `/mnt/o/lyh/Projects/hkia/hkg-flight-data-v3` 的 WSL2 Ubuntu 26.04.1 环境执行了 G0-P 前置检查。
- 结论：`BLOCKED`。`/usr/bin/python3` 实际为 Python 3.14.4；未发现可执行的 Python 3.7、3.11 或 3.13。未将 Python 3.14 替代目标版本进行验证。
- `git diff --check` 退出码为 0；既有工作树修改、删除及未跟踪文件均保留，未执行 reset、clean、stash、提交或推送。
- 当前命令通道 `stdin_tty=False`、`stdout_tty=False`，不具备真实交互终端；WSL/headless 结果不能替代 Windows 真实终端、IME、颜色、快捷键和终端恢复验收。
- Python 3.7 compileall、Python 3.11 核心 unittest、tests discover、Textual/Pilot 测试均因目标解释器缺失而 `BLOCKED/NOT RUN`；Ruff 命令不存在，按环境阻断处理；产品测试执行数为 0，无产品断言失败证据。
- G0-P 阻断期间未修改生产代码、测试、依赖或用户缓存，未启动写入 agent，V3-G0 及后续阶段未开始。解除 Python 3.11 环境阻断后必须重新执行 G0-P。

## 2026-09-09 · Python 3.14 使用边界与执行推进决策

- Python 3.14 **不是绝对不能使用**，可作为额外 `EXTRA/INSPECTED` 辅助 lane，用于运行纯 Python 测试、静态探针或发现较新解释器下的即时错误。
- 但 Python 3.14 不能替代项目正式验证目标：Python 3.7 基础兼容、Python 3.11/3.13 Textual 增强支持、目标版本的 wheel/依赖解析和真实终端验收。
- 原因是版本验证不具传递性：3.14 通过不代表 3.11、3.13 或 3.7 通过；3.14 失败也不能直接推出目标版本失败。Python 3.14 及其第三方依赖、ABI/wheel、平台标记和 Textual 兼容性还需要目标版本的独立证据。
- 当前项目 `pyproject.toml` 的增强支持目标是 Python 3.11/3.13，基础支持目标是 Python 3.7+；因此不能仅凭系统默认 `/usr/bin/python3` 为 3.14 就将正式目标改为 3.14。
- 执行推进：允许先用实际 `/usr/bin/python3`（3.14.4）执行纯 Python 辅助检查，并将结果标为 `EXTRA/INSPECTED`；同时继续寻找/提供 Python 3.7、3.11、3.13 解释器。只有目标 Python 3.11 测试入口可启动，G0-P 才可从 `BLOCKED` 变为 `READY` 或 `PARTIAL`；若 3.14 辅助检查通过，不能单独解除目标版本阻断。
- 在目标解释器缺失期间，不启动生产写入 agent，不进入 G1；可以执行不修改生产代码的 3.14 辅助检查、源码/文档核查和环境探针。

## 2026-09-09 · V3-G0-P 当前 WSL 复核结果

- 项目绝对路径：`/mnt/o/lyh/Projects/hkia/hkg-flight-data-v3`。
- 本次复核未修改生产代码、测试、依赖或用户缓存，未启动写入 agent；未执行 reset、clean、stash、提交或推送。
- HEAD：`71f31ed96eff14b0712cea56497b495f96b1aa6a feat: add compact CLI flight output`。
- 工作树已有修改和未跟踪文件均保留；`git diff --check` 退出码为 0。
- 环境为 WSL2 Ubuntu 26.04.1，内核 `6.18.33.2-microsoft-standard-WSL2`，不是 Windows 原生环境。
- 当前 shell 为 `/usr/bin/bash`；`stdin_tty=False`、`stdout_tty=False`。DISPLAY 和 WAYLAND_DISPLAY 存在，但当前命令通道不具备真实交互终端。
- 实际解释器：`/usr/bin/python3.7` 为 Python 3.7.17；`/usr/bin/python3.11` 为 Python 3.11.16；`/usr/bin/python3.13` 为 Python 3.13.15；`/usr/bin/python3` 解析到 `/usr/bin/python3.14`，为 Python 3.14.4。未使用 3.14 替代目标版本验证。
- Python 3.7 `compileall` 退出码 0；未发现语法编译错误。
- Python 3.11 核心 unittest 退出码 0：`Ran 89 tests`，`OK`，跳过 0。
- Python 3.11 `tests` discover 退出码 0：`Ran 58 tests`，`OK (skipped=5)`；实际通过 53 项，5 项因 `requires textual` 跳过。
- Textual import：`/usr/bin/python3.11 -c 'import textual; ...'` 退出码 1，`ModuleNotFoundError`；Textual/Pilot 增强 lane 为 `BLOCKED/NOT RUN`。
- Rich import：退出码 0，输出 `rich= imported`，未取得版本号。
- Ruff：`command -v ruff` 退出码 1；`ruff --version` 退出码 127，按环境 `BLOCKED/NOT RUN` 处理。
- 本次已执行测试无产品断言失败；依赖缺失和命令缺失不报告为产品 FAIL。
- WSL/headless 结果不能替代 Windows 真实终端、Windows IME、颜色、快捷键和终端恢复验收；wheel、Python 3.13 产品测试、30 分钟性能采样也尚未执行。
- G0-P 当前结论：`PARTIAL`。允许继续具备直接证据路径的自动化 G0–G3；Textual 相关 Adapter 验证、G4/G5 及对应验收项保持 `BLOCKED/NOT RUN`，不得进入最终完成声明。

## 2026-09-09 · V3-G0-P Textual 增量复核

- 用户明确授权安装 Textual；未修改项目代码、测试、依赖声明、文档或用户缓存。
- 为 `/usr/bin/python3.11` 和 `/usr/bin/python3.13` 安装 Textual `8.2.8`，均为用户级安装；当前两版本均可 `import textual`。
- 执行 `/usr/bin/python3.11 -m unittest discover -s /mnt/o/lyh/Projects/hkia/hkg-flight-data-v3/tests -t /mnt/o/lyh/Projects/hkia/hkg-flight-data-v3 -p 'test_terminal_*.py' -v`：退出码 0，`Ran 58 tests`，`OK`，无跳过。
- 执行 `/usr/bin/python3.13 -m unittest discover -s /mnt/o/lyh/Projects/hkia/hkg-flight-data-v3/tests -t /mnt/o/lyh/Projects/hkia/hkg-flight-data-v3 -p 'test_terminal_*.py' -v`：退出码 0，`Ran 58 tests`，`OK`，无跳过。
- `tests.test_terminal_textual.TestTextualInteraction` 的 5 个实际 Textual 用例在 Python 3.11 和 3.13 下均执行并通过；此前因 Textual 缺失的 5 项 skipped 已不再跳过。
- 本增量 lane 无产品断言失败。Python 3.11/3.13 Textual 自动化阻断已解除；真实 Windows 终端、IME、颜色、快捷键和终端恢复仍未验证。

## 2026-09-09 · V3-G0 只读基线复核

- 本阶段仅执行只读基线检查，未修改项目代码、测试、依赖声明、文档或用户缓存；未执行 reset、clean、stash、提交或推送；未启动写入 agent，未进入 G1。
- Ruff：`ruff check /mnt/o/lyh/Projects/hkia/hkg-flight-data-v3/hkg_flight /mnt/o/lyh/Projects/hkia/hkg-flight-data-v3/tests /mnt/o/lyh/Projects/hkia/hkg-flight-data-v3/test_hkg_flight.py /mnt/o/lyh/Projects/hkia/hkg-flight-data-v3/cleanup_alerts.py`，退出码 0，`All checks passed!`。
- Python 3.11 核心：`/usr/bin/python3.11 -m unittest /mnt/o/lyh/Projects/hkia/hkg-flight-data-v3/test_hkg_flight.py -v`，退出码 0，Ran 89，OK。
- Python 3.11 discover：`/usr/bin/python3.11 -m unittest discover -s /mnt/o/lyh/Projects/hkia/hkg-flight-data-v3/tests -t /mnt/o/lyh/Projects/hkia/hkg-flight-data-v3 -v`，退出码 0，Ran 58，OK，无跳过。
- Python 3.13 核心：`/usr/bin/python3.13 -m unittest /mnt/o/lyh/Projects/hkia/hkg-flight-data-v3/test_hkg_flight.py -v`，退出码 0，Ran 89，OK。
- Python 3.13 discover：`/usr/bin/python3.13 -m unittest discover -s /mnt/o/lyh/Projects/hkia/hkg-flight-data-v3/tests -t /mnt/o/lyh/Projects/hkia/hkg-flight-data-v3 -v`，退出码 0，Ran 58，OK，无跳过。
- 现有绿色 suite 不等于 V3 全部验收通过。G0 静态核查显示 R01–R05、R07–R10、R12–R13 的全部指定反例尚未由现有测试完整建立；尤其是嵌套快照隔离、稳定实体/重复航段、跨日/关闭后迟到发布、阻塞 worker 关闭、恶意控制码、真实尺寸可见选择、完整 Adapter 动作链和性能采样仍缺直接证据。
- G0 结果：现有自动化基线可启动且通过；V3 反例基线尚未完整建立。因此不将 G0 报告为 V3 核心完成，也不进入 G1。

## 2026-09-09 · V3-G0 反例基线补齐进度

- 当前准确状态：自动化环境基本就绪；正式目标版本基础测试通过；Textual 自动化测试通过；G0 反例基线未完成；生产修复未开始；Windows 真实终端仍阻断；项目完成不成立。
- 新增只读前置测试文件：`tests/test_v3_g0_baseline.py`。该文件只建立反例断言，不包含生产修复。
- Python 3.11 与 3.13 执行该文件：均 `Ran 9 tests`，`FAILED (failures=8)`，退出码 1；失败不是环境错误，而是当前候选实现的直接产品断言失败。
- Ruff 对新增基线文件：退出码 0，`All checks passed!`。
- 已建立并复现的失败基线：
  - R01：Session 航司嵌套快照可被调用方修改。
  - R02：状态/gate 变化会改变实体 ID。
  - R03：重复 pending refresh 返回 `accepted`，未合并为 `already_running`。
  - R04：关闭后迟到的 Poller 结果仍发布到快照。
  - R05：Session 关闭后航司 worker 仍可发布结果。
  - R06：API `[]` 成功在 plain 非 TTY 路径返回退出码 1，而非 0。
  - R08：40 列 CJK 输出按 `len()` 截断，display-cell 宽度溢出。
  - R09：真实 Textual 航司页 `/` 搜索动作不可达。
- R07 外部 markup 基线当前通过，保留为防回归保护；这不抵扣其他 R 项。
- R10 跨日/代次迟到发布、R11 完整旧路径/打包隔离、R12 规模/性能采样、R13 Windows 真实终端/IME/颜色/恢复仍未完成或不可在当前 WSL 通道直接验证。
- G0 状态：`IN PROGRESS`，不是完成声明。必须继续补齐 R10–R13 的直接证据或明确 `BLOCKED/NOT RUN` 记录；完成后由主 agent 冻结 Poller 契约，才可进入 V3-G1a。

## 2026-09-09 · Python 3.7 wheel venv 环境补证

- 按 R11 建议继续在仓外 `/tmp` 临时环境补证；未修改生产代码、测试、依赖声明、用户缓存或状态文档，未执行 reset、clean、stash、提交或推送，未进入 G1a。
- `/tmp/opencode/g0-r11-venv37/bin/python /tmp/opencode/get-pip.py`：`BLOCKED`。通用 get-pip.py 要求 Python >=3.10。
- `curl -fsSL https://bootstrap.pypa.io/pip/3.7/get-pip.py -o /tmp/opencode/get-pip-37.py`：退出码 0。
- `/tmp/opencode/g0-r11-venv37/bin/python /tmp/opencode/get-pip-37.py`：`BLOCKED`，退出码 1；错误为 `ModuleNotFoundError: No module named 'distutils.cmd'`。
- 因 Python 3.7 运行时缺少 `distutils`，临时 venv 仍无法安装 pip 或 wheel；该环境阻断不能报告为产品 FAIL。
- `git diff --check` 退出码 0。
- 当前 G0 状态仍为未收敛：Python 3.7 wheel venv、R10 跨日/generation seam、R12 30 分钟采样和 R13 Windows 真实终端证据仍未完成；未进入 G1。

## 2026-09-10 · V3-G0 Windows 原生 R10–R13 证据收敛

- 用户原话：“请在 Windows 原生环境执行以下绝对路径指令文档：`O:\lyh\Projects\hkia\hkg-flight-data-v3\V3-G0-WINDOWS-R10-R13-INSTRUCTION.md`”，并要求“严格按文档中的『V3-G0 Windows R10–R13 报告』格式返回……本次无论结果如何，必须明确『是否进入 G1：否』”。
- 诉求：在 Windows 原生环境完成 V3-G0 的 R10–R13 证据收敛，只做证据、不做修复。
- 授权边界：使用 Windows 原生 shell 与项目绝对路径；不修改生产代码、依赖声明、用户缓存或状态文档；不 reset、clean、stash、提交或推送；不启动写入 agent；不进入 G1。（本条登记本身是用户随后单独要求的写入，详见文末“本条写入说明”。）
- 完整报告外链：`R:\Temp\V3-G0-Windows-R10-R13-REPORT.md`；R13 人工取证清单：`R:\Temp\V3-G0-R13-HUMAN-EVIDENCE-CHECKLIST.md`；R12 原始数据：`R:\Temp\hkg-v3-g0-r12.txt` / `.json`。

### 执行环境

- OS：Windows 10 10.0.19045.5854，原生（非 WSL）。
- 环境偏差（需记录）：`cmd.exe` 被命令通道安全策略拦截（PowerShell 工具调用 cmd 亦被拒）；PowerShell 工具可执行但不回显 stdout。因此改用 Windows 原生 Git Bash（PortableGit 1.2.0）执行等价命令，`where` 改用 `which`/`Get-Command`，路径一律用项目绝对路径。
- TTY：命令通道 `stdin_tty=True`、`stdout_tty=False`、`TERM=dumb`，**非真实交互终端**。
- `%TEMP%` 实际为 `R:\Temp`（不是 `C:\Users\...\Temp`）；wheel、venv、探针、日志全部落在 `%TEMP%`。
- 解释器：`py -0p` 可见 3.14（默认）/ 3.11 / 3.7-32 / Astral-3.12.14。`py -3.7-32` = 3.7.7，`py -3.11` = 3.11.9，`py -3.14` = 3.14.7；**`py -3.13` 退出码 103（本机无 3.13 运行时）**。3.13 证据改用托管解释器 `C:\Users\avery\.workbuddy-ai\binaries\python\versions\3.13.12\python.exe`（实际 3.13.14），按既有 Python 3.14 使用边界决策记为 `EXTRA/INSPECTED`，不替代正式 3.13 证据。

### HEAD 与工作树

- HEAD：`71f31ed96eff14b0712cea56497b495f96b1aa6a feat: add compact CLI flight output`，分支 `master`。
- `git status --short` 执行前后逐行一致（17 个 `M`、1 个 `D hkg_flight/tui.py`、20 个 `??` 含 `hkg_flight/terminal/`、`tests/`）；`git diff --check` 退出码 0（仅 CRLF 警告）。
- 是否修改生产代码：**否**。源码树内仅新增 G0 证据测试 `tests\test_v3_g0_r10_scenarios.py`（`tests/` 本身即未跟踪目录）。
- 未执行 reset、clean、stash、commit、push；本次只运行 `log` / `status` / `branch` / `diff --check`。

### R01–R09 复核（既有红基线，断言未删未放宽）

- `py -3.11 -m unittest ...\tests\test_v3_g0_baseline.py -v`：`Ran 11`，`FAILED (failures=8)`，退出码 **1**。
- 托管 3.13.14 同命令：`Ran 11`，`FAILED (failures=7, skipped=1)`，退出码 **1**（R09 因无 textual 跳过）。
- `ruff check`（ruff 0.16.6）四个目标路径：`All checks passed!`，退出码 **0**。
- FAIL：R01、R02、R03、R04、R05、R06、R08、R09；通过：R07（外部 markup 字面化）、R10 两子项（closed 拒绝刷新、previous-date 语义）。

### R10：跨日、generation、逆序、close 后发布 —— 状态 **FAIL**

- 入口与 seam：新增 `tests\test_v3_g0_r10_scenarios.py`，**走真实发布 seam**：并发调用生产接口 `Poller.refresh_today()`，仅替换网络面 `api` 与两个文档化测试缝（实例属性 `Poller._now`、模块级 `today_str` 的线程局部打桩）。非静态源码推断。
- 执行：`py -3.11 -m unittest ...\tests\test_v3_g0_r10_scenarios.py -v` → `Ran 6`，`failures=2`，退出码 **1**；托管 3.13.14 同结果。与基线合并 `discover -p "test_v3_g0_*.py"` → `Ran 17`，`failures=10`，退出码 **1**。
- 失败实证：
  - 跨日：23:59 启动、00:00 后返回的刷新，把 `records_date` 从 `2026-09-10` 回写成 `2026-09-09`（`'2026-09-09' != '2026-09-10'`）。
  - 逆序：晚到的旧结果被重新发布，记录的 `gate` 由 `2` 退回 `1`。
  - 告警：晚到结果重跑告警检测，`AlertManager` revision 由 `1` 变为 `2`（`2 != 1`）。
  - 另由既有基线覆盖：Poller close 后迟到结果仍发布（R04 FAIL）、Session close 后航司 worker 仍发布（R05 FAIL，`loaded` 变 True）。
- 通过子项：closed 状态拒绝新刷新——`Poller.request_refresh()` 与 `Session.request_refresh()` 均返回 `"closed"`；旧日期显示——header 含 `2026-09-08` 与 `previous` 标记，同日不加标记。
- 根因（只读观察）：`Poller._do_refresh` 仅按 `revision + 1` 无条件发布，没有 generation / 启动序号 / 日期单调性守卫。

### R11：wheel 与包外运行 —— 状态 **PASS**

- `py -3.11 -m pip --version` → pip 26.2.1，退出码 0。`py -3.11 -m build --version` → 退出码 **1**（树内执行被项目 `build/` 目录遮蔽为 `No module named build.__main__`；树外为 `No module named build`），按文档走 `pip wheel` 兜底。
- `pip wheel --no-deps --no-build-isolation` → 退出码 **1**，`error: invalid command 'bdist_wheel'`（3.11 环境未装 wheel 包）。改为带隔离 `py -3.11 -m pip wheel "%P%" --no-deps -w R:\Temp\hkg-v3-g0\wheel` → 退出码 **0**，`hkg_flight_data-3.0.0-py3-none-any.whl`，46643 B。
- 包外 venv：`py -3.11 -m venv R:\Temp\hkg-v3-g0\venv311` 退出码 0（pip 24.0）；`pip install --no-deps <wheel>` 退出码 0；在 `%TEMP%` 下 `python -c "import hkg_flight"` 退出码 0，落点 `R:\Temp\hkg-v3-g0\venv311\Lib\site-packages\hkg_flight\__init__.py`；`python -m hkg_flight --help` 与控制台脚本 `hkg-flight.exe --help` 均退出码 0。
- wheel 内容：22 条目，**含 `hkg_flight/terminal/theme.tcss`**；安装后 tcss 落盘 662 B。
- Python 3.7：`py -3.7-32 -m venv R:\Temp\hkg-v3-g0\venv37` 退出码 0（pip 19.2.3）；安装 / `import hkg_flight` / `-m hkg_flight --help` 均退出码 0；`compileall` 返回 `True`。此前 WSL 侧 3.7 venv 因缺 `distutils` 阻断，Windows 原生侧已解除。
- 旧路径负向验证：`CursesTUI|run_simple_tui|FakeCursesScreen` 在 `hkg_flight\*.py` 与 `tests\*.py` 中 **0 命中**；`hkg_flight/tui.py` → `OLD_TUI_REMOVED`。仅历史文档/报告与记忆文件提及，按文档规定不作为可达代码证据。

### R12：离线性能与资源 —— 状态 **PASS（样本齐备）**

- 探针 `R:\Temp\hkg-v3-g0-r12.py`（仓外），真实 Session + 真实 Poller 后台线程 + 离线夹具 API；输出 `R:\Temp\hkg-v3-g0-r12.json` / `.txt` / `-stdout.log`。
- 1000/100/100 夹具**可建立**：flights 1002（`make_flights` 在 count≥30 时注入 1 条同日同向重复段）、alerts 100、airlines 100，构建 5.9 ms；渲染 80x24 `1.92 ms`、40x16 `1.76 ms`、200x50 `1.82 ms`。
- 样本量达标并做了有效性计数：交互 120 次（**90 次产生真实状态变更**，30 次为列表边界/同页等合法 no-op），发布 100 次。
  - 交互延迟（切页/移动/输入/筛选，`Session.handle`）：p50 **1.63 ms** / p95 **1.79 ms** / max **2.05 ms**。
  - 交互后渲染（`views.body_lines` 80x24）：p50 **1.71** / p95 **1.87** / max **1.95 ms**。
  - 快照发布（`Poller.refresh_today`，1000 条）：p50 **29.35** / p95 **34.94** / max **37.18 ms**。
  - 发布→可见（`rows_for`）：p50 **1.83** / p95 **2.00** / max **2.07 ms**。
- 0/5/10/15/20/25/30 分钟采样**全部执行**（后台 poller 30 s 间隔，30 分钟 60 次刷新，无异常）：RSS `31.8 → 32.7 MB`，线程 `5 → 2`，`records` 恒 1000，`revision` 101 → 160，`gc_objects` 23181 → 23707。队列长度用 `len(Poller._records)` 代理 = 1000（Poller 无显式队列对象）。
- 限制：本环境 stdout 非 TTY，“可见延迟”为 `rows_for` + `body_lines` 计算耗时，**不含真实终端绘制/刷新延迟**，不能替代 R13 真人体验。

### R13：Windows 真实终端人工证据 —— 状态 **BLOCKED / NOT RUN**

- 自动化 agent 不得自宣此项 PASS；本次无真人记录，故全部人工子项记 `NOT RUN`。
- 已采集供真人补录的环境事实：Windows 10 10.0.19045.5854；终端为 WorkBuddy 内置 Git Bash（PortableGit 1.2.0），**非 Windows Terminal**，`WT_SESSION` 未设置、stdout 非 TTY；Python 3.11.9；textual 8.2.8；字体未采集。
- 静态只读观察（`INSPECTED`，不构成人工证据）：`plain.py:273` 处理 `NO_COLOR`；`plain.py:184` 捕获 `EOFError/KeyboardInterrupt`；40 列宽度约束由 test_r08 覆盖且当前 FAIL。
- 待真人补录：中文 IME、焦点与快捷键、颜色与 NO_COLOR、40 列/resize/长字符、Ctrl/EOF 退出、终端恢复，以及截图或录像。清单见 `R:\Temp\V3-G0-R13-HUMAN-EVIDENCE-CHECKLIST.md`。

### 汇总

- **PASS**：R11 全部子项（构建、包外安装 3.11/3.7、import、`-m hkg_flight --help`、控制台脚本、wheel 含 `theme.tcss`、3.7 compileall、旧路径负向验证、`tui.py` 已删除）；R10 的 closed 拒绝刷新与 previous-date 语义；R07。
- **FAIL**：R10 跨日覆盖 / 逆序发布 / 旧结果重跑告警；R01、R02、R03、R04、R05、R06、R08、R09（既有红基线，未放宽未删除）。
- **BLOCKED**：R13（无真人记录）；`py -3.13`（退出码 103，正式 3.13 证据无法产出）。
- **NOT RUN**：`py -3.11 -m build`（模块缺失，已按文档兜底）；`pip wheel --no-build-isolation`（缺 wheel 包）；R13 全部人工子项。
- **INSPECTED**：3.13 用托管 3.13.14（EXTRA）；wheel **非可复现**——同源码连续 3 次构建 sha256 分别为 `350051a4…` / `9c09fc4a…` / `2934db75…`（均 46643 B），仓库内既有 `dist\*.whl` 为 `af002f94…`（46517 B）；wheel 安装环境无 textual（`textual_app` 导入 `ModuleNotFoundError`，符合可选 extra 声明）；R12 `gc_objects` 30 分钟 +526（约 +8.8/次刷新），趋势需更长/更严实验确认，未判定为泄漏。

### 结论与下一步

- **G0 是否收敛：否。**
- **是否进入 G1：否。**
- 下一步：① 修复 R10 根因——为 `Poller` 增加发布单调性守卫（generation/启动序号 + 日期不回退 + closed 后不发布），使 `test_v3_g0_r10_scenarios.py` 与基线 R04/R05 转绿；② 全绿后复跑 R11/R12，并补正式 Python 3.13 环境证据（需先安装 `py -3.13` 或指定解释器）；③ 由真人在真实 Windows Terminal 完成 R13 全部子项并留截图/录像后，方可判定 G0 收敛。
- 遗留（工具安全删除被拦截，需手动确认后清理）：`R:\r\temp\hkg-v3-g0\wheel\hkg_flight_data-3.0.0-py3-none-any.whl`（MSYS 路径解析失误错放的**有效**第 2 次构建产物，sha `9c09fc4a…`，非垃圾）；`R:\Temp\hkg-v3-g0-r12-*` 共 5 个 R12 探针缓存空目录。

### 本条写入说明

- 用户随后单独要求“你的报告写入 FEEDBACK-LOG.md”，故本条为**显式授权下的写入**，是本次唯一被修改的仓库内文件（且该文件当前为未跟踪状态，不进入 diff）。
- 本条只登记诉求、授权边界、执行结论与外链，不替代 `PROJECT-STATUS.md` 的运行状态，也不替代 `R:\Temp\V3-G0-Windows-R10-R13-REPORT.md` 的完整证据正文。
- 除本条外，本次仍未修改生产代码、测试断言以外的文件、依赖声明、用户缓存或状态文档；仍未提交或推送。
