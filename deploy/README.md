# HKG Flight Data v3 - 部署指南

## 系统要求

- Python 3.7 或更高版本
- 无需第三方依赖（仅使用标准库）
- 可选：`windows-curses`（Windows 上需要完整 TUI 支持）

## 快速开始

### 1. 安装

```bash
# 克隆或下载项目
git clone <repository-url>
cd hkg-flight-data-v3

# 验证 Python 版本
python --version  # 需要 3.7+
```

### 2. 运行

```bash
# 启动 TUI（默认）
python -m hkg_flight

# 启动 Web 服务器
python -m hkg_flight web

# 指定端口
python -m hkg_flight web --port 9000

# CLI 查询
python -m hkg_flight query CX759
python -m hkg_flight departures
python -m hkg_flight arrivals
python -m hkg_flight alerts
```

## 部署选项

### Windows 部署

#### 作为后台服务运行

创建 `start_web.bat`：

```batch
@echo off
cd /d "O:\lyh\Projects\hkia\hkg-flight-data-v3"
start "HKG Flight Data" python -m hkg_flight web --port 8080
```

#### 使用任务计划程序

1. 打开任务计划程序
2. 创建基本任务
3. 设置触发器（例如：登录时）
4. 操作：启动程序 `python`
5. 参数：`-m hkg_flight web --port 8080`
6. 起始于：`O:\lyh\Projects\hkia\hkg-flight-data-v3`

### Linux/macOS 部署

#### 使用 systemd（Linux）

创建 `/etc/systemd/system/hkg-flight.service`：

```ini
[Unit]
Description=HKG Flight Data Web Server
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/hkg-flight-data-v3
ExecStart=/usr/bin/python3 -m hkg_flight web --port 8080
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

启用并启动服务：

```bash
sudo systemctl enable hkg-flight
sudo systemctl start hkg-flight
sudo systemctl status hkg-flight
```

#### 使用 nohup

```bash
cd /path/to/hkg-flight-data-v3
nohup python3 -m hkg_flight web --port 8080 > hkg_flight.log 2>&1 &
```

### Docker 部署

创建 `Dockerfile`：

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY hkg_flight/ ./hkg_flight/
COPY README.md .

EXPOSE 8080

CMD ["python", "-m", "hkg_flight", "web", "--port", "8080"]
```

构建并运行：

```bash
docker build -t hkg-flight .
docker run -d -p 8080:8080 --name hkg-flight hkg-flight
```

## 配置

### 缓存目录

默认缓存目录：`~/.hkg_flight_cache/`

自定义缓存目录（修改 `hkg_flight/cache.py`）：

```python
DEFAULT_CACHE_DIR = "/path/to/custom/cache"
```

### API 设置

在 `hkg_flight/api.py` 中：

```python
API_BASE = "https://www.hongkongairport.com/flightinfo-rest/rest"
```

### 轮询间隔

在 `hkg_flight/cache.py` 中：

```python
DEFAULT_MIN_API_INTERVAL = 0.6  # API 调用最小间隔（秒）
```

## 维护

### 清理告警缓存

```bash
# 查看将要清理的内容（干运行）
python cleanup_alerts.py --days 7

# 应用清理
python cleanup_alerts.py --days 7 --apply

# 清除所有告警
python cleanup_alerts.py --clear-all --apply
```

### 运行测试

```bash
python -m unittest test_hkg_flight
```

### 日志

Web 服务器日志输出到 stderr。在 Linux 上可以重定向：

```bash
python -m hkg_flight web 2>&1 | tee hkg_flight.log
```

## 故障排除

### 常见问题

1. **TUI 无法启动**
   - Windows：安装 `windows-curses`：`pip install windows-curses`
   - 或者使用 CLI 命令或 Web 模式

2. **API 连接失败**
   - 检查网络连接
   - 确认能访问 `https://www.hongkongairport.com`
   - 查看缓存数据是否可用（自动回退到缓存）

3. **端口被占用**
   - 使用 `--port` 指定其他端口
   - 检查端口占用：`netstat -an | findstr 8080`

4. **缓存过大**
   - 定期运行 `cleanup_alerts.py`
   - 手动删除 `~/.hkg_flight_cache/` 中的旧文件

## 项目结构

```
hkg-flight-data-v3/
├── hkg_flight/           # 主包
│   ├── __init__.py       # 包入口
│   ├── __main__.py       # 模块运行器
│   ├── cli.py            # 命令行接口
│   ├── cache.py          # 缓存系统
│   ├── api.py            # API 客户端
│   ├── alerts.py         # 告警管理
│   └── utils.py          # 工具函数
├── deploy/               # 部署文档
│   └── README.md         # 本文件
├── test_hkg_flight.py    # 测试套件
├── cleanup_alerts.py     # 告警清理脚本
├── README.md             # 使用说明
└── SPEC.md               # 规格说明
```

## 更多信息

- README.md：使用说明和功能介绍
- SPEC.md：详细规格和架构说明
- PROJECT-STATUS.md：项目状态和验证结果
