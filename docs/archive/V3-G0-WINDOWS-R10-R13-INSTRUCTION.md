# V3-G0 Windows 原生环境执行指令（R10–R13）

## 项目路径

```text
O:\lyh\Projects\hkia\hkg-flight-data-v3
```

本指令只做 V3-G0 证据收敛，不进入 G1，不修改生产代码。

## 强制规则

- 使用 Windows 原生 shell；项目路径必须使用上述绝对路径。
- 优先使用 `py` Launcher，不假设 `python` 或 `python3` 存在。
- 不得修改生产代码、依赖声明、用户缓存或状态文档。
- 不得 reset、clean、stash、提交或推送。
- 允许新增/修改仅用于 G0 证据的测试、夹具或仓外临时探针；不得修复实现。
- wheel、venv、日志、解压目录放在 `%TEMP%`，不得留在源码树。
- Python 3.14 仅为 `EXTRA/INSPECTED`，不能替代 3.7/3.11/3.13 正式证据。

## 1. 环境和既有基线

在 `cmd.exe` 执行：

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
py -3.11 -c "import sys,platform,os; print(sys.executable); print(sys.version); print(platform.platform()); print(os.getcwd()); print(sys.stdin.isatty(), sys.stdout.isatty())"
git -C "O:\lyh\Projects\hkia\hkg-flight-data-v3" log -1 --format="%%H %%s"
git -C "O:\lyh\Projects\hkia\hkg-flight-data-v3" status --short
git -C "O:\lyh\Projects\hkia\hkg-flight-data-v3" diff --check
```

复跑既有失败基线，不得删除或放宽断言：

```bat
py -3.11 -m unittest "O:\lyh\Projects\hkia\hkg-flight-data-v3\tests\test_v3_g0_baseline.py" -v
py -3.13 -m unittest "O:\lyh\Projects\hkia\hkg-flight-data-v3\tests\test_v3_g0_baseline.py" -v
ruff check "O:\lyh\Projects\hkia\hkg-flight-data-v3\hkg_flight" "O:\lyh\Projects\hkia\hkg-flight-data-v3\tests" "O:\lyh\Projects\hkia\hkg-flight-data-v3\test_hkg_flight.py" "O:\lyh\Projects\hkia\hkg-flight-data-v3\cleanup_alerts.py"
```

## 2. R10：跨日、generation、逆序和 close 后发布

使用实际 Poller/Session 生产接口或真实发布 seam，执行 `tests/test_v3_g0_baseline.py` 中已有 R04/R05 基线，并补充尚缺场景：

- 23:59 请求在 00:00 返回，旧结果不得覆盖新日期数据、revision、成功时间、告警；
- 新 generation 先发布、旧 generation 后发布，旧结果被丢弃；
- Poller close 后迟到结果不得发布；
- Session close 后迟到航司 worker 结果不得发布；
- closed 状态拒绝新刷新；
- 旧日期显示明确日期/previous-date 语义。

若无法在真实 seam 接入，记录 `BLOCKED/NOT RUN` 和具体原因；不得只做静态源码推断。

## 3. R11：wheel 和包外运行

先在源码树外构建：

```bat
set P=O:\lyh\Projects\hkia\hkg-flight-data-v3
set T=%TEMP%\hkg-v3-g0
rmdir /s /q "%T%" 2>nul
mkdir "%T%"
py -3.11 -m pip --version
py -3.11 -m build --version
py -3.11 -m build --wheel --no-isolation --outdir "%T%\wheel" "%P%"
```

如果 `build` 不存在但 pip 可用：

```bat
py -3.11 -m pip wheel "%P%" --no-deps --no-build-isolation -w "%T%\wheel"
```

对实际 wheel 执行包外安装：

```bat
py -3.11 -m venv "%T%\venv311"
"%T%\venv311\Scripts\python.exe" -m pip install --no-deps %T%\wheel\*.whl
cd /d "%TEMP%"
"%T%\venv311\Scripts\python.exe" -c "import hkg_flight; print(hkg_flight.__file__)"
"%T%\venv311\Scripts\python.exe" -m hkg_flight --help
```

检查 wheel 内容：

```bat
tar -tf %T%\wheel\*.whl | findstr /i "theme.tcss hkg_flight terminal"
```

Python 3.7 venv 如可用，使用：

```bat
py -3.7-32 -m venv "%T%\venv37"
"%T%\venv37\Scripts\python.exe" -m pip --version
"%T%\venv37\Scripts\python.exe" -c "import hkg_flight; print(hkg_flight.__file__)"
```

若 Python 3.7 venv/pip 失败，记录环境 `BLOCKED`，不要修改项目配置。

检查旧路径只做负向验证：

```bat
findstr /s /n /i "CursesTUI run_simple_tui FakeCursesScreen" "%P%\hkg_flight\*.py" "%P%\tests\*.py"
if exist "%P%\hkg_flight\tui.py" (echo OLD_TUI_PRESENT) else (echo OLD_TUI_REMOVED)
```

历史文档中的旧名称不能单独判定为可达代码。

## 4. R12：离线性能和资源

使用现有离线夹具和入口；如需要探针，只能写到 `%TEMP%\hkg-v3-g0-r12.py`。记录：

- 1000/100/100 夹具是否可建立；
- 至少 100 次导航/切页/筛选/输入样本；
- 至少 100 次快照发布可见延迟样本；
- p50/p95/max；
- 活跃线程、进程内存、队列长度；
- 0/5/10/15/20/25/30 分钟采样（能执行才做）。

没有样本不得标 PASS；未执行标 `NOT RUN`；真实人工体验不能用自动化数据替代。

## 5. R13：Windows 真实终端人工证据

自动化 agent 不得自行宣称人工验收 PASS。需要真人在真实 Windows Terminal/支持的终端中记录：

- 中文 IME；
- 焦点和快捷键；
- 颜色与 NO_COLOR；
- 40 列/resize/长字符；
- Ctrl/EOF 退出；
- 终端恢复；
- 截图/录像及 OS/终端/字体/Python/Textual 信息。

没有真人记录就标 `BLOCKED/NOT RUN`。

## 6. 固定回报

```text
V3-G0 Windows R10–R13 报告
项目：O:\lyh\Projects\hkia\hkg-flight-data-v3
执行环境：Windows 原生 / shell / TTY
HEAD：
工作树：
是否修改生产代码：必须为否
R01–R09 复核：
R10：命令、入口、场景、结果、状态
R11：build、wheel、包外安装、3.7、TCSS、旧路径、状态
R12：夹具、样本、p50/p95/max、资源、日志、状态
R13：真人/终端证据、状态
PASS：
FAIL：
BLOCKED：
NOT RUN：
INSPECTED：
G0 是否收敛：是/否
是否进入 G1：必须为否
下一步：
```
