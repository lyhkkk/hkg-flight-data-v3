# HKG Flight Data v3 — Project Status

> 最后更新: 2026-09-08

## 项目状态: ✅ 运行正常

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
| `test_hkg_flight.py` | 测试套件 |
| `cleanup_alerts.py` | 告警清理脚本 |
| `deploy/` | 部署文档 |
| `README.md` | 使用说明 |
| `SPEC.md` | 规格说明 |
| `PROJECT-STATUS.md` | 本文件 |

## 已知问题

- TUI 模式需要 `windows-curses`（Windows）或 `curses`（Linux/macOS）
- 告警历史在保存时限制为最近 500 条；仍可使用 `cleanup_alerts.py` 做按日期清理
- TUI 在不同终端上的 curses 支持仍取决于平台（Windows 可选 `windows-curses`）

## 本轮改进记录 — 2026-09-08

- 修复 V1 P1：收紧停机位识别，避免 BA15、KA21、HX22、UO23、SQ2、JL26 等短航班号被误判为停机位

- 增加告警历史上限（最近 500 条）并让告警查询返回防御性副本
- 删除 Web UI 中未使用的告警横幅，移除过时的 SSE 描述
- 将 Web API 的日期参数错误保持为 HTTP 400，并保留非今日请求失败时返回空列表的语义
- 确认 `--force` 为非破坏性的本次运行航司缓存绕过；航班请求直接访问 API，不删除缓存文件
- 增加 Web、Poller、TUI、缓存绕过、告警保留策略的回归测试（本地验证结果以 `python -m unittest test_hkg_flight` 为准）
- 记录 v5 复审改进：Windows curses 跳过、轮询停止检测、统一 TUI 状态颜色、`NO_COLOR` 输出控制
- 本轮本地验证：88 个测试通过；测试数量与结果仍以本地命令和 CI 为准
- 增加 `pyproject.toml`、Ruff 规则和 GitHub Actions CI（Python 3.7/3.11/3.13）
- 记录本次操作：先测试后改进，所有行为变更均同步更新文档并完成本地验证

## 后续建议

- [x] 为 Web、Poller、TUI 和 `--force` 增加基础回归测试；测试数量与结果以本地命令和 CI 为准
- [x] 添加 `pyproject.toml`、ruff 配置和 GitHub Actions CI
- [ ] 完善 TUI 模式的跨平台支持
- [ ] 添加日志轮转配置
- [ ] 考虑添加配置文件支持（JSON/YAML）
