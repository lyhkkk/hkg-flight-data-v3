# TUI V3 执行证据

核查日期：2026-09-09。本文件仅记录本次实际执行证据，不替代详细规格或维护第二份运行状态。规格见 [V3 报告](TUI-REBUILD-REPORT-v3.html)，生命周期见 [唯一 note](.agents/notes/proposed/architecture/2026-09-09-tui-rebuild.md)。

## G0-P / G0 环境预检与停止

2026-09-09 用户同意将 Python 运行时与自动化测试前置门正式纳入计划。新增前置计划见 [V3-G0-P-PREFLIGHT-PLAN.md](V3-G0-P-PREFLIGHT-PLAN.md)。随后已在 `/mnt/o/lyh/Projects/hkia/hkg-flight-data-v3` 的 WSL2 Ubuntu 26.04.1 环境完成 G0-P 前置检查；结论为 `BLOCKED`：当前 `/usr/bin/python3` 为 Python 3.14.4，未发现可执行 Python 3.7、3.11 或 3.13；Ruff 也未发现。产品测试命令执行数为 0；未委派写入任务，未修改生产代码、测试、依赖或用户缓存，未提交推送。复核者：主 agent。

G0-P 将把环境结果分为 `READY`、`PARTIAL`、`BLOCKED`：Python/依赖命令缺失属于环境阻断，不报告为产品 FAIL；测试断言失败才进入产品失败基线。Python 3.14 不是绝对禁止使用：若可用，可运行纯 Python 的辅助测试并标为 `EXTRA/INSPECTED`；但不能替代项目声明的 Python 3.11/3.13 增强 lane 或 Python 3.7 基础兼容 lane。G0-P 为 `PARTIAL` 时，可继续有直接证据路径的自动化 G0–G3，但 G4/G5、真实平台/人工验收和 Note 生命周期迁移仍被阻断。

以下是工具直接返回结果的摘录，不是完整原始日志；本次尚未生成候选文件内容摘要，不能据此复现完整候选。

| 命令 | 实际结果 |
|---|---|
| `git log -1 --format='%H %s'` | `71f31ed96eff14b0712cea56497b495f96b1aa6a feat: add compact CLI flight output` |
| `git status --short` | 既有工作树不干净：生产模块、打包、CI、当前文档、旧测试存在修改；旧 tui.py 已删除；terminal/、tests/、规划报告及 note 等未跟踪。未 reset 或清理。 |
| `git diff --stat` | 17 个已跟踪文件，640 insertions、947 deletions；不包含未跟踪候选文件。 |
| `command -v python python3 python3.7 python3.11 python3.13 powershell.exe pwsh.exe cmd.exe gh` | 找到 `/usr/bin/python3` 和 Windows PowerShell、pwsh、cmd；其他所列命令未返回路径。 |
| `python --version` / `python -m pip show textual rich` | `python: command not found`，不是产品测试失败。 |
| `python3 --version` | Python 3.14.4。 |
| `python3 -m pip show textual rich` | `No module named pip`；不能由此推断 Windows 环境的框架版本。 |
| `powershell.exe -NoProfile -NonInteractive -Command "Get-Command py,python,wt -ErrorAction SilentlyContinue \| Select-Object Name,Source; py -0p"` | Windows launcher 列出 3.14、3.11、3.7-32、Astral 3.12.14；找到 wt.exe。未列出 3.13，不证明其他位置绝无该版本。表中反斜杠仅转义 Markdown 的管道符。 |
| `python3 -c 'import os,sys,platform; print("OS:",platform.platform()); print("executable:",sys.executable); print("stdin_tty:",sys.stdin.isatty()); print("stdout_tty:",sys.stdout.isatty()); print("DISPLAY:",bool(os.environ.get("DISPLAY"))); print("WAYLAND_DISPLAY:",bool(os.environ.get("WAYLAND_DISPLAY")))'` | Linux 6.18.33.2 microsoft-standard-WSL2，glibc 2.43；`/usr/bin/python3`；stdin/stdout TTY 均 False；DISPLAY、WAYLAND_DISPLAY 均存在。 |

停止依据：交接文件要求必要真实终端/平台证据无法取得时立即停止。本会话工具没有真实 Windows 终端的交互、IME 操作及截图/录像核验通道，尚无人工验收提供者确认。存在 wt.exe 或图形环境变量不等于 A13 验收可执行；非 TTY 也不证明产品不支持真实终端。

待用户确认如何取得真实终端人工证据，并明确是否允许在该证据待补期间继续 G0 及后续自动化修复。未申请或执行缩小支持范围；未将 A13 改为可豁免项。

## A1-A14 证据账本

| A | 关联 R | 结果 | 本次证据与缺口 |
|---|---|---|---|
| A1 | R03/R11 | NOT RUN | 未执行真实入口与阻塞首刷测试。 |
| A2 | R08-R10 | NOT RUN | 未执行 Pilot 或真实导航。 |
| A3 | R01/R02 | NOT RUN | 未执行深隔离、稳定实体与详情回归。 |
| A4 | R06 | NOT RUN | 未执行健康状态组合测试。 |
| A5 | R03 | NOT RUN | 未执行并发、限速或 no-poll 测试。 |
| A6 | R07/R08 | NOT RUN | 未执行尺寸、Unicode、安全或视觉验证。 |
| A7 | R04/R05/R12 | NOT RUN | 未执行关闭、迟到发布或 Web 生命周期测试。 |
| A8 | R11/R13 | NOT RUN | 仅 INSPECTED 解释器发现结果；未运行平台矩阵或 wheel 安装。 |
| A9 | R06/R07/R12 | NOT RUN | 未执行非 TTY 产品输出、EOF 或 NO_COLOR 验证。 |
| A10 | R04 | NOT RUN | 未执行跨日及逆序发布测试。 |
| A11 | R12/R13 | NOT RUN | 未重跑回归、lint 或文档一致性检查。 |
| A12 | R13 | NOT RUN | 未执行 1000/100/100 夹具、时延样本或 30 分钟采样。 |
| A13 | R13 | BLOCKED | 本会话无法直接取得真实 Windows 终端/IME 人工验收证据；待确认人工执行安排。 |
| A14 | R09/R10/R13 | NOT RUN | 未执行动作清单与实际 Adapter 对齐检查。 |

产品测试命令执行数：0；skipped：未运行 suite，未取得计数。没有修复前目标断言失败，也没有红转绿证据。R01-R13 基线尚未建立；历史测试声明未用于本次 PASS。G1-G5 未开始，note 未迁移。
