# HKG Flight Data v3 — Project Status

> 最后更新: 2026-09-09

## 项目状态: ⚠️ V3-G0-P 前置计划已纳入，V3 实施未完成

> Rev 2 的既有功能描述不等于 V3 验收通过。当前 V3 已执行一次 `V3-G0-P` Python 运行时与自动化测试前置门，但因仅发现 Python 3.14.4、未发现目标 Python 3.7/3.11/3.13，结论为 `BLOCKED`；V3 G1-G5 未完成。Python 3.14 可做辅助 lane，但不能替代正式目标版本证据。详见 [V3 执行证据报告](TUI-REBUILD-EXECUTION-REPORT-v3.md)、[G0-P 前置计划](V3-G0-P-PREFLIGHT-PLAN.md) 与 [反馈记录](FEEDBACK-LOG.md)。

## 环境信息

| 项目 | 状态 |
|------|------|
| Python 版本 | 3.11+ |
| 语法检查 | ✅ 通过 |
| CLI 功能 | ✅ 正常 |
| 数据源连接 | ✅ 正常 |

## 功能验证

| 功能 | 命令 | 状态 |
|------|------|------|
| 语法检查 | `python -m compileall -q hkg_flight cleanup_alerts.py` | ✅ 通过 |
| 帮助信息 | `python -m hkg_flight --help` | ✅ 正常 |
| 离境航班 | `python -m hkg_flight departures` | ✅ 408 条记录 |
| 到达航班 | `python -m hkg_flight arrivals` | ✅ 正常 |
| 告警查询 | `python -m hkg_flight alerts` | ✅ 正常 |
| 航司代码查询 | `python -m hkg_flight query CX` | ✅ 335 条（分页） |

## 数据源

- **API**: `https://www.hongkongairport.com/flightinfo-rest/rest`
- **缓存**: `~/.hkg_flight_cache/`
- **轮询间隔**: 30 秒
- **礼貌限速**: 0.6 秒/请求

## 最近完成的工作

### 2026-09-09 — 终端工作台重建（TUI-REBUILD Rev 2，G0→G4）

1. ✅ **决策冻结与风险验证（G0）**
   - 实测 Textual 8.2.8（requires-python >=3.9,<4.0），headless `run_test` 通过
   - 基础包保持 3.7 可解析；`py -3.7-32 -m compileall` 与 discover 通过
   - 记录身份扩展为全字段投影（真实样本存在同日同方向重复航段）
   - 缓存 mtime、API/航司失败元数据、`alerts_revision` 已落地

2. ✅ **纵向骨架（G1）**
   - `Session` 统一拥有轮询链/Web/航司加载；非阻塞首刷只触发一次
   - 原子防御性快照（revision/records/source/时间/错误元数据）
   - 真实 CLI 入口 `--ui auto|textual|plain`，统一 finally 清理

3. ✅ **航班工作流（G2）**
   - 离港/到达/告警/航司四页 + 详情 + 筛选面板 + 帮助
   - 白名单搜索（词 AND、字段 OR、航班号去空格）、稳定选择、三档布局

4. ✅ **运行场景（G3）**
   - Web 端口占用报 ERROR、no-poll 仅手动刷新、迟到请求丢弃
   - plain 降级与非 TTY 有限输出、NO_COLOR、跨午夜“上一数据日期”标记

5. ✅ **验证与删除旧路径（G4）**
   - 移除 `CursesTUI`/`run_simple_tui`/`FakeCursesScreen` 与 `hkg_flight/tui.py`
   - `.[tui]` 可选安装组、`theme.tcss` 打包、CI 基线与增强矩阵
   - 同步 README/COMMANDS/SPEC/PROJECT-STATUS

### 2026-09-08

1. ✅ **航空公司代码查询**
   - `query CX` 支持按 2 字母航司代码搜索（主航班号前缀匹配）
   - `--codeshare` 可包含搭载该航司代码的代码共享航班（如 BR258 带 CX4446）

2. ✅ **查询结果分页**
   - 默认每页 10 条（`DEFAULT_PAGE_SIZE`），交互式翻页：Enter/N 下一页、P 上一页、数字跳页、Q 退出
   - 结果超过 10 条的普通查询也自动使用分页视图

3. ✅ **测试套件扩展**
   - 新增 12 个测试（航司代码搜索 4 个 + 分页器 8 个）
   - 初始版本测试结果已归档；当前结果以本地命令和 CI 运行结果为准

### 2026-09-07

1. ✅ **添加测试套件** (test_hkg_flight.py)
   - 初始版本有 58 个测试；当前测试数量与结果以本地命令和 CI 运行结果为准
   - 覆盖：工具函数、缓存系统、告警管理、数据解析

2. ✅ **清理历史告警**
   - 清除了 56 个活跃告警
   - 清除了 100 个历史告警
   - 创建了 `cleanup_alerts.py` 脚本

3. ✅ **代码模块化重构**
   - 将 2378 行单文件拆分为包结构
   - 创建 `hkg_flight/` 包：
     - `__init__.py` - 包入口
     - `__main__.py` - 模块运行器
     - `utils.py` - 工具函数
     - `cache.py` - 缓存系统
     - `api.py` - API 客户端
     - `alerts.py` - 告警管理
     - `cli.py` - 命令行接口

4. ✅ **添加部署文档**
   - 创建 `deploy/README.md` - 部署指南
   - 创建 `deploy/config.example.md` - 配置示例
   - 包含 Windows/Linux/Docker 部署说明

## 文件清单

| 文件/目录 | 说明 |
|------|------|
| `hkg_flight/` | 主包目录 |
| `hkg_flight/terminal/` | 重建的终端工作台（session/state/presenter/views/plain/textual_app/theme.tcss） |
| `tests/` | 终端测试套件与离线夹具 |
| `test_hkg_flight.py` | 核心回归测试套件 |
| `cleanup_alerts.py` | 告警清理脚本 |
| `deploy/` | 部署文档 |
| `README.md` | 使用说明 |
| `SPEC.md` | 规格说明 |
| `PROJECT-STATUS.md` | 本文件 |

## 已知问题

- 增强终端界面需要 `.[tui]`（Python 3.9+，项目目标 3.11/3.13）；基础 CLI/Web/plain 保持 3.7+
- 40 列紧凑布局的可读性需真实终端人工确认；低于 40 列显示尺寸提示
- 真实终端输入法（Windows 中文输入、颜色、快捷键）需至少一次真人/真实终端记录
- 告警历史在保存时限制为最近 500 条；仍可使用 `cleanup_alerts.py` 做按日期清理
- 香港业务日期语义（Asia/Hong_Kong 统一）仍为独立高优先级决策，本次未变更

## 本轮改进记录 — 2026-09-08

- CLI 默认改为每航班一行的紧凑表格；`query --details/-d` 保留完整详情输出，翻页仍为每页 10 条

- 修复 V1 P1：收紧停机位识别，避免 BA15、KA21、HX22、UO23、SQ2、JL26 等短航班号被误判为停机位

- 增加告警历史上限（最近 500 条）并让告警查询返回防御性副本
- 删除 Web UI 中未使用的告警横幅，移除过时的 SSE 描述
- 将 Web API 的日期参数错误保持为 HTTP 400，并保留非今日请求失败时返回空列表的语义
- 确认 `--force` 为非破坏性的本次运行航司缓存绕过；航班请求直接访问 API，不删除缓存文件
- 增加 Web、Poller、TUI、缓存绕过、告警保留策略的回归测试（本地验证结果以 `python -m unittest test_hkg_flight` 为准）
- 记录 v5 复审改进：Windows curses 跳过、轮询停止检测、统一 TUI 状态颜色、`NO_COLOR` 输出控制
- 本轮本地验证：测试数量与结果以本地命令和 CI 为准
- v6 R1：停机位/登机门专用查询无结果时回退按航班号匹配，避免 D7/X7/E3 等歧义输入静默返回 0 条
- `state.json` 读写 API 暂作设计保留；Poller 当前使用进程内快照，跨重启状态持久化另列架构任务
- 增加 `pyproject.toml`、Ruff 规则和 GitHub Actions CI（Python 3.7/3.11/3.13）
- 记录本次操作：先测试后改进，所有行为变更均同步更新文档并完成本地验证

## 后续建议

- [x] 为 Web、Poller、TUI 和 `--force` 增加基础回归测试；测试数量与结果以本地命令和 CI 为准
- [x] 添加 `pyproject.toml`、ruff 配置和 GitHub Actions CI
- [ ] 完善 TUI 模式的跨平台支持
- [ ] 添加日志轮转配置
- [ ] 考虑添加配置文件支持（JSON/YAML）
