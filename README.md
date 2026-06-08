# DeepSeek Monitor

DeepSeek Monitor 是一个 Windows 桌面小工具，用来查看 DeepSeek API 账户余额、导入或同步 DeepSeek Usage 用量数据，并展示本月消耗、模型 tokens 和最近 7 天趋势。

## 当前功能

- 实时查询 DeepSeek API 账户余额：`GET /user/balance`
- 显示账户状态、总余额、充值余额、赠送余额
- 余额偏低/严重不足提醒
- 手动导入 DeepSeek Usage 导出的 ZIP / CSV 文件
- 后台静默同步 DeepSeek Usage 导出文件
- 首次登录使用可见浏览器窗口，后续同步使用 headless 后台模式
- 今日消耗、本月消耗、模型 tokens、模型费用、请求次数统计
- 最近 7 天消费趋势柱状图
- API Key 优先保存到 Windows Credential Manager
- 配置保存到 `%LOCALAPPDATA%\DeepSeek Monitor\config.json`
- 定时刷新、启动后自动刷新
- Windows 当前用户开机自启
- 启动后最小化到系统托盘
- 系统托盘图标和托盘菜单
- 可选隐藏 Windows 任务栏图标，仅显示托盘图标
- PyInstaller onedir 打包为 Windows EXE

## 项目结构

```text
deepseek-monitor/
  main.py
  requirements.txt
  README.md
  .gitignore
  DeepSeekMonitor.spec
  config.example.json
  scripts/
    build_exe.ps1
    pyi_rth_playwright.py
  src/
    app.py                  # PySide6 主窗口、托盘、设置窗口
    app_data.py             # %LOCALAPPDATA% 用户数据目录
    api_client.py           # DeepSeek 余额接口
    config_manager.py       # 配置和 API Key 管理
    database.py             # SQLite 本地用量数据库
    usage_downloader.py     # Playwright 静默同步/登录窗口
    usage_importer.py       # Usage ZIP/CSV 解析
    usage_recorder.py       # 真实 API 调用 token 用量记录
    workers.py              # 后台线程
    widgets.py              # 自定义 UI 组件
    styles.py               # QSS 样式
    tray.py                 # 预留文件，当前托盘逻辑在 app.py
  assets/
    icon.png
    icon.ico
```

## 用户数据位置

程序不会把用户数据写入安装目录。所有可写数据统一保存到：

```text
%LOCALAPPDATA%\DeepSeek Monitor\
```

常见文件：

```text
C:\Users\<用户名>\AppData\Local\DeepSeek Monitor\
  ├── browser_profile\     # Playwright 浏览器登录会话
  ├── auth_state.json      # 登录状态快照，不保存账号密码
  ├── exports\             # 静默同步下载的 Usage 文件
  ├── logs\app.log         # 运行日志
  ├── config.json          # 程序设置
  └── usage.db             # 本地用量数据库
```

API Key 优先保存到 Windows Credential Manager。只有系统凭据不可用时，才会 fallback 到 `config.json`。

## 开发环境运行

第一次运行：

```powershell
cd "D:\DeepSeek Monitor\deepseek-monitor"
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe main.py
```

以后运行：

```powershell
cd "D:\DeepSeek Monitor\deepseek-monitor"
.\.venv\Scripts\python.exe main.py
```

## 设置 API Key

1. 打开软件
2. 点击右上角齿轮按钮
3. 输入 DeepSeek API Key
4. 点击保存

不要把 API Key 写进代码。程序不会在日志或命令行输出完整 API Key。

命令行测试余额接口：

```powershell
$env:DEEPSEEK_API_KEY="你的 API Key"
.\.venv\Scripts\python.exe -m src.api_client
```

## Usage 数据来源

余额来自 DeepSeek API 实时查询。

用量数据来自两种方式：

- 手动导入 DeepSeek Usage 页面导出的 ZIP / CSV
- 使用 Playwright 后台静默下载 Usage 导出文件，再自动解析

手动导入：

1. 打开 DeepSeek Usage 页面：`https://platform.deepseek.com/usage`
2. 点击页面里的导出按钮，下载 ZIP 或 CSV
3. 在 DeepSeek Monitor 右上角点击向下箭头按钮
4. 选择下载的 ZIP / CSV 文件

命令行测试导入：

```powershell
.\.venv\Scripts\python.exe -m src.usage_importer "D:\路径\usage_data.zip"
```

## 自动同步 Usage

自动同步使用 Playwright：

- 正常刷新时使用 `headless=True`，不会弹出浏览器
- 第一次需要登录时，软件会提示“需要登录”
- 只有用户点击“打开登录窗口”后，才会打开可见浏览器
- 程序不保存 DeepSeek 账号密码
- 登录状态保存到 `browser_profile\` 和 `auth_state.json`

命令行测试：

```powershell
# 静默下载测试。未登录时只提示需要登录，不会弹出浏览器。
.\.venv\Scripts\python.exe -m src.usage_downloader --silent

# 打开登录窗口，让用户手动登录。
.\.venv\Scripts\python.exe -m src.usage_downloader --login

# 清除本地登录状态。
.\.venv\Scripts\python.exe -m src.usage_downloader --clear-login
```

打包版自动同步优先使用 Windows 默认浏览器对应的 Edge / Chrome。如果默认浏览器不是 Playwright 可控的 Chromium 系浏览器，会继续尝试 Microsoft Edge、Google Chrome，最后尝试 Playwright Chromium。

## 系统托盘

软件启动后会创建系统托盘图标。

托盘菜单包含：

- 当前模式
- 显示窗口
- 立即刷新
- 打开设置
- 退出程序

设置窗口中可以勾选：

```text
隐藏任务栏图标，仅显示托盘图标
```

启用后：

- 主窗口不显示在 Windows 任务栏
- 系统托盘图标仍然可用
- 关闭窗口会隐藏到托盘
- 真正退出需要使用托盘菜单“退出程序”

任务栏显示状态会记录到：

```text
%LOCALAPPDATA%\DeepSeek Monitor\logs\app.log
```

示例：

```text
Taskbar icon hidden: true
Taskbar icon hidden: false
```

## 开机自启

设置窗口中可以勾选：

```text
开机自启
```

软件使用当前用户注册表 Run 项实现开机自启，不需要管理员权限。

注册表路径：

```text
HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run
```

启动项名称：

```text
DeepSeek Monitor
```

启动命令格式：

```text
"C:\Path\To\DeepSeek Monitor.exe" --startup
```

`--startup` 表示开机自启模式。此模式下软件默认进入系统托盘，不弹出主窗口；托盘图标仍然显示，定时刷新和启动后自动刷新仍然执行。

手动检查启动项：

```powershell
reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "DeepSeek Monitor"
```

手动删除启动项：

```powershell
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "DeepSeek Monitor" /f
```

设置窗口中也可以勾选：

```text
启动后最小化到托盘
```

启用后，即使不是开机自启启动，普通启动也会先进入托盘后台运行。

## 自动刷新

支持三种刷新方式：

- 点击右上角刷新按钮
- 启动后 1.5 秒自动刷新
- 定时刷新：5 / 10 / 30 / 60 分钟

刷新时会：

1. 查询余额
2. 如果启用静默同步，则后台下载 Usage 文件
3. 解析 Usage 数据
4. 刷新今日消耗、本月消耗、模型卡片和 7 天趋势图

## 设置项

当前配置包含：

```json
{
  "api_base_url": "https://api.deepseek.com",
  "auto_start": false,
  "autostart_enabled": false,
  "start_minimized_to_tray": false,
  "refresh_interval_minutes": 10,
  "auto_refresh_on_startup": true,
  "scheduled_refresh_enabled": true,
  "silent_usage_sync_enabled": true,
  "hide_taskbar_icon": false,
  "always_on_top": false,
  "balance_warning_yellow": 5.0,
  "balance_warning_red": 1.0
}
```

说明：`auto_start` 是旧版兼容字段，新版以 `autostart_enabled` 为准。设置页会以注册表真实状态为准。

## 打包为 EXE

当前使用瘦身打包策略：不把 Playwright Chromium 浏览器本体打进程序。

推荐使用 onedir 模式，不推荐 onefile：

- PySide6 和 Playwright 依赖文件较多
- onefile 每次启动都要解压，启动慢
- onedir 更稳定

一键打包：

```powershell
cd "D:\DeepSeek Monitor\deepseek-monitor"
powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1
```

输出目录：

```text
dist\DeepSeek Monitor\
  ├── DeepSeek Monitor.exe
  └── _internal\
```

分发时要复制整个 `dist\DeepSeek Monitor` 文件夹，不要只复制单个 EXE。

手动打包：

```powershell
cd "D:\DeepSeek Monitor\deepseek-monitor"
.\.venv\Scripts\python.exe -m PyInstaller DeepSeekMonitor.spec --noconfirm
```

## 常见问题

| 提示 | 原因 | 解决方法 |
|---|---|---|
| 未找到可用浏览器 | 电脑没有 Edge / Chrome，也没有 Playwright Chromium | 安装 Microsoft Edge 或 Google Chrome |
| 需要登录 DeepSeek 后才能自动同步用量 | 登录状态缺失或过期 | 点击“打开登录窗口”重新登录 |
| 请先在设置中填写 API Key | 没有配置 API Key | 打开设置并保存 API Key |
| 自动同步失败 | 网络问题、页面结构变化或下载失败 | 使用右上角导入按钮手动导入 ZIP/CSV |
| EXE 图标没有立即变化 | Windows 图标缓存未刷新 | 重命名 EXE、换目录查看或重启资源管理器 |

## 常见 API 错误

- **401**：API Key 错误或已失效
- **402**：账户余额不足
- **429**：请求太频繁
- **500**：DeepSeek 服务器错误
- **503**：DeepSeek 服务暂时不可用
- 网络连接失败：检查网络后重试
- 请求超时：稍后重试

## 技术栈

| 层 | 技术 |
|---|---|
| UI | PySide6-Essentials 6.7.3 |
| HTTP | requests 2.32.3 |
| 浏览器自动化 | Playwright 1.49.1 |
| 凭据管理 | keyring 25.5.0 |
| 数据存储 | SQLite |
| 配置 | JSON + Windows Credential Manager |
| 打包 | PyInstaller 6.10.0 |

## 记录真实 API 调用用量

在你自己写的 DeepSeek API 调用脚本中引入 `usage_recorder`，每次调用的 token 数会自动写入 `usage.db`，打开 DeepSeek Monitor 就能看到实时统计。

### 方式 1：从 API 响应自动提取（推荐）

```python
import requests
from src.usage_recorder import record_from_response

response = requests.post(
    "https://api.deepseek.com/chat/completions",
    headers={"Authorization": "Bearer sk-xxx"},
    json={"model": "deepseek-chat", "messages": [...]},
)
data = response.json()
record_from_response(data)  # 自动提取 usage 并写入 DB
```

### 方式 2：手动记录

```python
from src.usage_recorder import record_usage

record_usage("deepseek-chat", input_tokens=100, output_tokens=50)
# 自动估算费用（按 DeepSeek 官方定价）
```

### 方式 3：批量记录（上下文管理器）

```python
from src.usage_recorder import UsageRecorder

with UsageRecorder() as recorder:
    for resp in api_responses:
        recorder.record_from_response(resp)
    # 退出上下文时自动批量写入
```

### 方式 4：流式响应

```python
from src.usage_recorder import record_from_streaming_chunks

chunks = [...]  # 收集到的所有 SSE chunk
record_from_streaming_chunks(chunks)
```

### 支持的模型定价

| 模型 | 输入（¥/1K tokens） | 输出（¥/1K tokens） |
|---|---|---|
| deepseek-chat / V4 Flash | 0.0005 | 0.0010 / 0.0020 |
| deepseek-v4-pro | 0.0020 | 0.0080 |
| deepseek-reasoner / deepseek-r1 | 0.0020 | 0.0080 |

未列出的模型使用默认定价（输入 0.001，输出 0.002）。

写入 `usage.db` 后，DeepSeek Monitor 下次刷新时会自动显示新数据。

## 后续目标
- 优化自动同步失败诊断
- 可选制作无 Playwright 的 Lite 版，进一步减小打包体积
- 将当前托盘逻辑从 `app.py` 整理到 `tray.py`
