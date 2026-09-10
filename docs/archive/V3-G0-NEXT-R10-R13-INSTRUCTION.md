# V3-G0 下一步执行指令：收敛 R10–R13

**执行环境：** WSL

**项目绝对路径：** `/mnt/o/lyh/Projects/hkia/hkg-flight-data-v3`

## 当前背景

R01–R09 已建立修复前基线；R07 为当前防回归通过。R10–R13 尚未收敛。Python 3.7 venv/pip 补证因 `distutils.cmd` 缺失而 BLOCKED；这只阻断该 venv 路径，不得报告为产品 FAIL，也不得修改生产代码或项目依赖来绕过。

## 强制规则

- 先阅读 `TUI-REBUILD-REPORT-v3.html`、`TUI-REBUILD-MULTI-AGENT-HANDOFF-v3.md`、`V3-G0-CONTINUE-R10-R13-INSTRUCTION.md` 和本文件。
- 仍处于 G0；本次不得进入 G1，不得修改生产代码。
- 可以新增或修改仅用于 G0 失败证据的测试/夹具/仓外探针，但不得修复实现。
- 不得修改依赖声明、业务契约、持久化格式、用户缓存、状态文档。
- 不得 reset、clean、stash、提交或推送。
- 所有临时 wheel、venv、解压目录、日志放在 `/tmp`，不得在源码树留下构建产物。
- 每项报告实际入口、完整命令、退出码、断言/输出、状态和未覆盖面。

## 1. 复核已有基线

```bash
P=/mnt/o/lyh/Projects/hkia/hkg-flight-data-v3

git -C "$P" status --short
git -C "$P" diff --check
/usr/bin/python3.11 -m unittest "$P/tests/test_v3_g0_baseline.py" -v
/usr/bin/python3.13 -m unittest "$P/tests/test_v3_g0_baseline.py" -v
```

确认 R01–R09 的失败名称仍保持，不得删除、放宽或改写失败断言。

## 2. R10：完成直接行为基线

在现有 Poller/Session 生产接口或实际发布 seam 上，补充只用于基线的测试，覆盖：

- 23:59 请求在 00:00 返回，旧结果不得覆盖新日期记录、revision、成功时间、告警；
- 新 generation 先发布、旧 generation 后发布，旧结果被丢弃；
- Poller `close()` 后迟到结果不得发布；
- Session `close()` 后迟到航司 worker 结果不得发布；
- closed 状态拒绝新刷新；
- 旧日期显示有明确日期/previous-date 语义。

若实现失败，保留真实失败测试并报告 FAIL；若测试无法接入实际 seam，报告 BLOCKED/NOT RUN 和具体原因。不得只做静态源码判断。

## 3. R11：改用“wheel 解压包外运行”补充 Python 3.7 证据

不要继续反复运行通用 get-pip.py；Python 3.7 venv 已因 `distutils.cmd` 阻断。先只读检查构建能力：

```bash
P=/mnt/o/lyh/Projects/hkia/hkg-flight-data-v3
rm -rf /tmp/hkg-v3-g0-wheel /tmp/hkg-v3-g0-unpack37 /tmp/hkg-v3-g0-unpack311 /tmp/hkg-v3-g0-unpack313
mkdir -p /tmp/hkg-v3-g0-wheel
/usr/bin/python3.11 -m pip --version
/usr/bin/python3.11 -m build --version || true
```

如果 `python3.11 -m build` 可用，执行：

```bash
/usr/bin/python3.11 -m build --wheel --no-isolation --outdir /tmp/hkg-v3-g0-wheel "$P"
```

否则如果 pip 可用，执行：

```bash
/usr/bin/python3.11 -m pip wheel "$P" --no-deps --no-build-isolation -w /tmp/hkg-v3-g0-wheel
```

如果两者都不可用，R11 wheel build 标记 BLOCKED，不修改项目配置。

对实际生成的 wheel：

```bash
WHEEL=$(find /tmp/hkg-v3-g0-wheel -maxdepth 1 -name '*.whl' -print -quit)
unzip -q "$WHEEL" -d /tmp/hkg-v3-g0-unpack37
find /tmp/hkg-v3-g0-unpack37 -maxdepth 4 -type f | sort
```

用 Python 3.7 从源码树外的解压包执行基础 import/help：

```bash
PYTHONPATH=/tmp/hkg-v3-g0-unpack37 /usr/bin/python3.7 -c 'import hkg_flight; print("import=OK", hkg_flight.__file__)'
PYTHONPATH=/tmp/hkg-v3-g0-unpack37 /usr/bin/python3.7 -m hkg_flight --help
```

如导入失败，记录真实 traceback 为 Python 3.7 包外运行 FAIL；如 Python 3.7 运行时缺少依赖/模块，区分环境 BLOCKED 与产品 FAIL，不修改依赖。

对 3.11/3.13 解压包分别确认：

- 包目录来源不指向源码树；
- `hkg_flight/terminal/theme.tcss` 存在；
- Python 3.11/3.13 可 import；
- 不把 wheel 构建成功等同于完整 A8 通过。

## 4. R12：仅做可复现的离线测量

优先使用现有生产 presenter/views/state/terminal 测试入口和离线夹具；如果没有现成性能脚本，可创建 `/tmp/hkg-v3-g0-r12.py`，不得写入项目目录。记录：

- 1000/100/100 规模夹具是否可建立；
- 至少 100 次导航/筛选/输入反馈样本（入口可达时）；
- 至少 100 次快照发布到可见的样本（seam 可达时）；
- p50/p95/max；
- 活跃线程、进程内存、队列长度；
- 退出恢复和资源最终退出时间。

可以执行 0/5/10/15/20/25/30 分钟采样，但必须有原始日志路径。没有样本不得标 PASS；WSL 非 TTY 无法测量的真实终端人工体验标记 BLOCKED/NOT RUN，不用 headless 冒充 A13。

## 5. R13：明确记录平台阻断

当前 WSL2 非 Windows 原生环境，且当前命令通道 `stdin_tty=False`、`stdout_tty=False`。以下必须明确标记 BLOCKED/NOT RUN：

- Windows Terminal 真实操作；
- 中文 IME；
- 真实颜色和 NO_COLOR；
- 快捷键和焦点人工行为；
- 40 列人工可读性、resize、长字符；
- Ctrl/EOF 退出后的终端恢复；
- 截图/录像证据。

不要用 WSL、headless、Pilot 或静态检查填充 R13 PASS。

## 6. G0 收敛判断

本次只报告，不进入 G1。R10–R13 使用：

- `PASS`：直接命令/行为证据通过；
- `FAIL`：直接命令/断言失败；
- `BLOCKED`：明确环境或平台缺口；
- `NOT RUN`：未执行并说明原因；
- `INSPECTED`：只有静态检查，不能替代行为证据。

G0 收敛报告必须分别说明：

1. R01–R09 是否保持原失败基线；
2. R10 的每个场景结果；
3. R11 wheel 构建、包外解压运行、Python 3.7 venv 阻断的区别；
4. R12 样本和原始日志路径；
5. R13 人工平台阻断；
6. 哪些项允许进入 G1，哪些项必须继续保留阻断；
7. 是否建议 G0 收敛；
8. 本次不得启动 G1。

## 固定回报格式

```text
V3-G0 R10–R13 收敛报告
项目：/mnt/o/lyh/Projects/hkia/hkg-flight-data-v3
HEAD：
是否修改生产代码：必须为否
R01–R09 复核：
R10：逐场景命令、入口、结果、状态
R11：build 工具、wheel 路径、包外解压、3.7 import/help、TCSS、状态
R12：夹具规模、样本数量、p50/p95/max、资源数据、原始日志、状态
R13：平台/人工证据与状态
Python 3.7 venv distutils 阻断：
PASS：
FAIL：
BLOCKED：
NOT RUN：
INSPECTED：
G0 是否收敛：是/否
是否进入 G1：必须为否
下一步建议：
```
