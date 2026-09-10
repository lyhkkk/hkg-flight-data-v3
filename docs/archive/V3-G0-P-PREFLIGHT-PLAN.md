# V3-G0-P Python 运行时与自动化测试前置计划

**适用项目：** HKG Flight Data v3 终端工作台

**状态：** 已纳入 V3 实施交接；不是产品完成声明。

**日期：** 2026-09-09

## 1. 目的

V3-G0-P 是正式 V3-G0 基线前的强制前置门，负责确认：

- Windows Python 解释器是否可发现、可调用；
- 基础 Python 3.7 lane、目标增强 Python 3.11 lane、候选 Python 3.13 lane，以及可选 Python 3.14 辅助 lane 的实际状态；
- Textual、Rich、Ruff 等依赖的真实状态；
- 核心回归测试和终端测试是否能够启动；
- 环境错误、测试未执行、产品断言失败之间的区别；
- 当前工作树、HEAD 和 TTY 事实是否可复现。

本阶段不修复生产代码，不修改依赖声明，不清理或重置工作树，不安装未知依赖，不触碰用户缓存。

## 2. 结果分类

### READY

至少一个目标 Python 3.11 可执行，核心测试可以启动，工作树可安全保留，且环境错误与产品断言失败已经分开记录。可以进入 V3-G0。Python 3.14 可以作为临时兼容性/探索性辅助 lane，但不能替代项目声明的 3.11/3.13 增强支持证据，也不能替代 3.7 基础兼容性证据。

### PARTIAL

部分自动化 lane 可执行，例如 Python 3.11 核心测试可运行，但 Python 3.7、3.13、Textual、Ruff、wheel 或真实终端 lane 缺失。允许继续有直接证据路径的自动化 G0–G3；缺失项保持 `BLOCKED` 或 `NOT RUN`，不得进入最终完成声明。

### BLOCKED

没有可执行的目标 Python 3.11、基础测试无法启动、无法重复执行，或工作树无法安全保留。停止所有写入 agent，不开始 G0-G3 修复。

## 3. Windows 预检命令

在仓库根目录执行，优先使用 Python Launcher，不假设 `python` 或 `python3` 存在：

```bat
cd /d O:\lyh\Projects\hkia\hkg-flight-data-v3
where py
where python
where python3
py -0p
py -3.7-32 --version
py -3.11 --version
py -3.13 --version
```

记录每条命令的：

- 完整命令；
- 退出码；
- 标准输出和错误输出；
- 实际解释器路径；
- `PASS`、`BLOCKED` 或 `NOT FOUND`。

命令不存在是环境状态，不是产品测试 FAIL。

## 4. 解释器与 TTY 事实

```bat
py -3.11 -c "import sys,platform,os; print('executable=',sys.executable); print('version=',sys.version); print('platform=',platform.platform()); print('cwd=',os.getcwd()); print('stdin_tty=',sys.stdin.isatty()); print('stdout_tty=',sys.stdout.isatty())"
```

对于实际存在的 3.7 和 3.13 解释器，执行同等身份检查。记录当前是否为真实交互终端；非 TTY 只能说明当前命令通道，不得推断产品不支持真实终端。

## 5. Python 3.14 的使用边界

Python 3.14 不是“绝对不能使用”，但在当前项目计划中只能作为**额外辅助 lane**：

- 可以用来检查纯 Python 代码是否能在更新解释器上启动；
- 可以运行与版本无关的单元测试，帮助发现候选实现的即时错误；
- 可以用于静态检查、文档工具或一次性探针，前提是依赖能够安装并实际运行。

Python 3.14 不能替代以下证据：

- 项目声明的 Python 3.11/3.13 Textual 增强支持；
- Python 3.7 基础包语法/导入兼容性；
- 目标版本上的 Textual 8.x、Pilot、Session 和入口行为；
- 目标版本上的 wheel 安装和依赖解析；
- 真实 Windows 终端、IME、颜色、快捷键和终端恢复验收。

原因不是 Python 3.14 一定不兼容，而是版本验证具有非传递性：3.14 通过，不证明 3.11/3.13/3.7 通过；3.14 失败，也不能直接证明目标版本失败。Python 3.14 还是较新的版本，第三方依赖、构建 wheel、ABI、平台标记和 Textual 兼容性可能尚未覆盖；项目当前 `pyproject.toml` 的增强支持目标明确为 Python 3.11/3.13，验收矩阵也按这些版本定义。

因此本次策略为：

```text
3.14：可运行辅助测试，结果标记为 EXTRA / INSPECTED
3.11：增强目标版本，必须实际验证
3.13：增强目标版本，必须实际验证
3.7：基础兼容目标，必须实际验证或明确 BLOCKED
```

如果用户希望把 Python 3.14 纳入正式支持范围，必须另行调整 `pyproject.toml`、CI、文档、依赖兼容性和 A8 验收矩阵；不能仅凭一次 3.14 测试运行自动扩大支持范围。

## 6. 依赖检查

```bat
py -3.11 -c "import textual; print('textual=', getattr(textual, '__version__', 'unknown'))"
py -3.11 -c "import rich; print('rich=', getattr(rich, '__version__', 'imported'))"
where ruff
ruff --version
```

依赖分类：

| 情况 | 状态 |
|---|---|
| 依赖可 import，版本满足项目约束 | PASS / READY |
| 依赖缺失 | 对应增强 lane BLOCKED；不是产品 FAIL |
| 版本不满足约束 | 对应 lane BLOCKED，并记录实际版本 |
| import 后测试断言失败 | 产品测试 FAIL |
| 命令未执行 | NOT RUN |

## 6. 基础 lane

### Python 3.7 语法/导入兼容

```bat
py -3.7-32 -m compileall -q hkg_flight cleanup_alerts.py
```

3.7 不存在时，A8 基础 3.7 lane 标为 `BLOCKED`，不得使用 3.11 结果替代。

### 核心回归

```bat
py -3.11 -m unittest test_hkg_flight -v
```

### 终端测试发现

```bat
py -3.11 -m unittest discover -s tests -v
```

### 静态检查

```bat
ruff check hkg_flight tests test_hkg_flight.py cleanup_alerts.py
```

测试断言失败标记为产品 `FAIL`，并进入 V3-G0 反例归档；解释器、依赖或命令缺失标记为环境 `BLOCKED`/`NOT RUN`。

## 7. Textual 增强 lane

只有 Textual 可 import 且版本满足项目约束时，才执行增强测试。至少单独记录：

```bat
py -3.11 -m unittest tests.test_terminal_textual -v
py -3.11 -m unittest tests.test_terminal_entrypoint -v
py -3.11 -m unittest tests.test_terminal_session -v
```

测试不得只运行 reducer 或静态函数；真实 Widget、Pilot、Session 装配和关闭路径按 V3-G0/G3 继续建立证据。

## 8. 工作树与证据

G0-P 必须记录：

```bat
git log -1 --format="%H %s"
git status --short
git diff --stat
```

不得执行：

```text
reset --hard
clean -fd
stash
删除或覆盖他人修改
自动提交或推送
```

如果需要安装环境，应由用户明确授权，并在独立环境中执行；前置计划本身不自动安装。

## 9. 固定回报模板

```text
G0-P 前置环境报告：

工作目录：
HEAD：
工作树摘要：

解释器：
- py -3.7-32：PASS / BLOCKED / NOT FOUND / NOT RUN
- py -3.11：PASS / BLOCKED / NOT FOUND / NOT RUN
- py -3.13：PASS / BLOCKED / NOT FOUND / NOT RUN

依赖：
- textual：
- rich：
- ruff：

基础检查：
- compileall：
- 核心 unittest：
- tests discover：
- Textual tests：
- Ruff：

每条命令：命令、退出码、测试计数、关键输出
环境阻断：
产品失败：
NOT RUN：
结论：READY / PARTIAL / BLOCKED
下一步：
```

## 10. 与后续阶段的关系

- `READY`：进入 V3-G0，建立 R01–R13 修复前基线。
- `PARTIAL`：只进入具备直接证据路径的自动化 G0–G3；G4/G5、A8/A13 及相关项保持阻断或未运行。
- `BLOCKED`：不委派写入 agent，先解决 Python/测试执行环境。
- 无论哪种结果，都不能以历史测试总数、CI 配置、目录存在或 agent 结论代替直接测试证据。
- 真实 Windows 终端、IME、40 列人工可读性、终端恢复和性能采样是最终验收门；缺失时不得迁移唯一 Agent Note 为 `implemented`。
