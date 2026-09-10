# V3-G0-P 增量执行指令

**执行环境：** WSL

**项目绝对路径：** `/mnt/o/lyh/Projects/hkia/hkg-flight-data-v3`

## 目标

补齐 G0-P 的 Ruff、Python 3.7/3.13/3.14 检查，并重新确认当前环境；只读执行，不修改代码。

## 强制规则

- 所有项目路径使用 `/mnt/o/lyh/Projects/hkia/hkg-flight-data-v3`，不得依赖当前目录。
- 不得修改生产代码、测试、依赖、用户缓存或文档。
- 不得执行 `reset`、`clean`、`stash`、提交或推送。
- 不得启动写入 agent，不进入 G1。
- Python 3.14 仅标记 `EXTRA/INSPECTED`，不得替代 3.7/3.11/3.13 正式证据。
- 环境缺失标记 `BLOCKED/NOT RUN`；测试断言失败才标记产品 `FAIL`。

## 执行命令

```bash
P=/mnt/o/lyh/Projects/hkia/hkg-flight-data-v3

command -v ruff
readlink -f "$(command -v ruff)"
ruff --version

/usr/bin/python3.7 --version
/usr/bin/python3.11 --version
/usr/bin/python3.13 --version
/usr/bin/python3.14 --version

git -C "$P" log -1 --format='%H %s'
git -C "$P" status --short
git -C "$P" diff --stat
git -C "$P" diff --check

ruff check "$P/hkg_flight" "$P/tests" "$P/test_hkg_flight.py" "$P/cleanup_alerts.py"

/usr/bin/python3.7 -m compileall -q "$P/hkg_flight" "$P/cleanup_alerts.py"
/usr/bin/python3.7 -c 'import hkg_flight; print("python37_import=OK", hkg_flight.__file__)'
(cd "$P" && /usr/bin/python3.7 -m hkg_flight --help)

/usr/bin/python3.11 -m unittest "$P/test_hkg_flight.py" -v
/usr/bin/python3.11 -m unittest discover -s "$P/tests" -t "$P" -v

/usr/bin/python3.13 -m unittest "$P/test_hkg_flight.py" -v
/usr/bin/python3.13 -m unittest discover -s "$P/tests" -t "$P" -v

/usr/bin/python3.14 -m compileall -q "$P/hkg_flight" "$P/cleanup_alerts.py"
/usr/bin/python3.14 -m unittest "$P/test_hkg_flight.py" -v
/usr/bin/python3.14 -m unittest discover -s "$P/tests" -t "$P" -v

/usr/bin/python3.11 -c 'import textual; print("textual311=OK", getattr(textual,"__version__","unknown"))'
/usr/bin/python3.13 -c 'import textual; print("textual313=OK", getattr(textual,"__version__","unknown"))'
/usr/bin/python3.11 -c 'import rich; print("rich311=OK", getattr(rich,"__version__","unknown"))'
/usr/bin/python3.13 -c 'import rich; print("rich313=OK", getattr(rich,"__version__","unknown"))'
```

## Textual 测试条件

只有对应解释器的 `import textual` 成功，才运行该版本：

```bash
P=/mnt/o/lyh/Projects/hkia/hkg-flight-data-v3
/usr/bin/python3.11 -m unittest discover -s "$P/tests" -t "$P" -p 'test_terminal_*.py' -v
/usr/bin/python3.13 -m unittest discover -s "$P/tests" -t "$P" -p 'test_terminal_*.py' -v
```

若 Textual 不可导入，记录为 `BLOCKED/NOT RUN`，不要把跳过当作通过。

## 回报格式

```text
G0-P 增量报告
项目：/mnt/o/lyh/Projects/hkia/hkg-flight-data-v3
HEAD：
工作树：
git diff --check：
Ruff：路径、版本、结果、规则错误
Python 3.7：compileall/import/help
Python 3.11：核心测试、discover、Textual
Python 3.13：核心测试、discover、Textual
Python 3.14：compileall、核心测试、discover（EXTRA/INSPECTED）
Rich：3.11/3.13
PASS：
FAIL：
BLOCKED：
NOT RUN：
SKIPPED：
产品断言失败：
环境阻断：
是否修改文件：必须为否
G0-P 结论：READY / PARTIAL / BLOCKED
下一步：
```

G0-P 只有在 Python 3.11 基础测试能够启动且环境/产品失败已区分时，才可至少判定为 `PARTIAL`；不得因 Python 3.14 辅助测试通过而解除正式目标版本阻断。
