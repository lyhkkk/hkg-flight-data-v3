# HKG Flight Data v3 - 配置示例

# 复制此文件并根据需要进行修改
# 注意：当前版本通过修改源代码中的常量进行配置

## cache.py 配置

```python
# 默认缓存目录（~/.hkg_flight_cache/）
DEFAULT_CACHE_DIR = "~/.hkg_flight_cache"

# API 调用最小间隔（秒）- 用于礼貌限速
DEFAULT_MIN_API_INTERVAL = 0.6

# 默认 Web 服务器端口
DEFAULT_WEB_PORT = 8080
```

## api.py 配置

```python
# HKIA API 基础 URL
API_BASE = "https://www.hongkongairport.com/flightinfo-rest/rest"

# 请求超时时间（秒）
REQUEST_TIMEOUT = 15

# User-Agent 头
USER_AGENT = "HKGFlightData/3.0"
```

## 环境变量（可选）

可以通过环境变量覆盖某些设置：

```bash
# 设置缓存目录
export HKG_CACHE_DIR="/path/to/cache"

# 设置 Web 端口
export HKG_WEB_PORT=9000

# 设置 API 间隔
export HKG_API_INTERVAL=1.0
```

## 系统服务配置

### Windows 任务计划程序

创建 XML 任务定义：

```xml
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
    </LogonTrigger>
  </Triggers>
  <Actions>
    <Exec>
      <Command>python</Command>
      <Arguments>-m hkg_flight web --port 8080</Arguments>
      <WorkingDirectory>O:\lyh\Projects\hkia\hkg-flight-data-v3</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
```

### Linux systemd

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
Environment=HKG_CACHE_DIR=/var/cache/hkg-flight

[Install]
WantedBy=multi-user.target
```

## 性能调优

### 减少 API 调用

增大 `DEFAULT_MIN_API_INTERVAL` 可以减少 API 调用频率：

```python
DEFAULT_MIN_API_INTERVAL = 1.0  # 增加到 1 秒
```

### 增加缓存时间

修改 `cache.py` 中的缓存过期时间：

```python
# 今日数据缓存过期（分钟）
TODAY_CACHE_EXPIRY = 5

# 历史数据缓存过期（小时）
HISTORY_CACHE_EXPIRY = 24
```

## 日志配置

默认日志输出到 stderr。可以通过修改 `utils.py` 中的 `log()` 函数自定义：

```python
import logging

def log(msg):
    """自定义日志函数"""
    logging.info(msg)
```

## 告警配置

### 清理旧告警

告警由程序自动维护：上限 500 条、仅保留当前数据日期、航班起飞 / 降落 / 取消
后自动移除。**不再需要定时清理任务**。

如需人工检查或清空：

```bash
# 查看将要清理的内容（干运行）
python cleanup_alerts.py --days 7

# 应用清理
python cleanup_alerts.py --days 7 --apply

# 清空全部告警
python cleanup_alerts.py --clear-all --apply
```

## 安全注意事项

1. **API 访问**：遵守 HKIA 的使用条款，不要过度频繁调用 API
2. **Web 服务器**：默认绑定到所有接口，生产环境建议绑定到 localhost
3. **缓存目录**：确保缓存目录有适当的读写权限
