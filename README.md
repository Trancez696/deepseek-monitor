# DeepSeek Monitor

DeepSeek Monitor 是一个 Windows 桌面小工具，用来查看 DeepSeek API 账户余额和本地用量趋势。

- 余额查询（DeepSeek API `/user/balance`）
- 用量自动静默同步（Playwright headless 下载 Usage 导出）
- 用量手动导入（DeepSeek 网页导出的 ZIP / CSV）
- 今天/本月消耗统计 + 7 天趋势图表
- API Key 保存到 Windows Credential Manager
- 定时自动刷新 + 余额预警

## 项目结构

```text
deepseek-monitor/
  main.py                   # 程序入口
  requirements.txt
  README.md
  .gitignore
  DeepSeekMonitor.spec      # PyInstaller 打包配置
  config.example.json       # 配置模板
  scripts/
    build_exe.ps1           # 一键打包脚本
    pyi_rth_playwright.py   # PyInstaller 运行时 hook（Playwright Chromium 路径）
  src/
    app.py                  # PySide6 主窗口
    app_data.py             # 用户数据目录管理 (%LOCALAPPDATA%)
    api_client.py           # DeepSeek API 余额查询
    config_manager.py       # 配置读写 (keyring + config.json)
    database.py             # SQLite 本地用量数据库
    usage_downloader.py     # Playwright 自动同步/登录
    usage_importer.py       # CSV / ZIP 用量文件导入
    workers.py              # QThread 后台任务
    widgets.py              # 自定义 UI 组件
    styles.py               # QSS 样式
    tray.py                 # 系统托盘（预留）
  assets/
    icon.png
    icon.ico
```

## 用户数据保存位置

所有用户数据统一保存到：

```text
%LOCALAPPDATA%\DeepSeek Monitor\
```

例如：

```text
C:\Users\<用户名>\AppData\Local\DeepSeek Monitor\
  ├── browser_profile\     # Playwright 浏览器登录会话
  ├── exports\             # 静默同步下载的 Usage 导出文件
  ├── logs\                # 运行日志（预留）
  ├── config.json          # 程序设置
  └── usage.db             # 本地用量数据库
```

不在程序安装目录写入任何用户数据。

---

## 开发环境

### 第一次运行

```powershell
cd "D:\DeepSeek Monitor\deepseek-monitor"
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe main.py
```

### 以后每次运行

```powershell
cd "D:\DeepSeek Monitor\deepseek-monitor"
.\.venv\Scripts\python.exe main.py
```

### 设置 API Key

1. 点击右上角 ⚙ 按钮
2. 输入 DeepSeek API Key
3. 点击保存

API Key 优先保存到 Windows Credential Manager（`keyring`），如果系统凭据不可用则 fallback 到 config.json。

### 测试余额接口

```powershell
$env:DEEPSEEK_API_KEY="你的 API Key"
python -m src.api_client
```

### 命令行测试 Usage 导入

```powershell
.\.venv\Scripts\python.exe -m src.usage_importer "下载的导出文件.zip"
```

---

## 打包为 EXE

### 前置说明

当前使用瘦身打包策略：不把 Playwright Chromium 浏览器本体打进程序。
自动同步会优先使用 Windows 默认浏览器对应的 Edge / Chrome；如果默认浏览器不是 Playwright 可控的 Chromium 系浏览器，则自动尝试 Microsoft Edge 和 Google Chrome。

**运行时路径解析机制：**

打包后的 EXE 通过两层保障确保 Playwright 能启动：

1. **PyInstaller 运行时 hook**（`scripts/pyi_rth_playwright.py`）：在 `main.py` 之前运行，设置 Playwright `node.exe` 路径。
2. **模块级兜底**（`src/usage_downloader.py`）：优先识别系统默认浏览器；如果默认浏览器不是 Edge / Chrome，再尝试系统 Edge、Chrome，最后尝试 Playwright Chromium。

这样可以避免把 100MB+ 的 Chromium 放进安装包里。

推荐使用 **onedir** 模式（不推荐 onefile），原因：

1. PySide6 和 Playwright 运行时文件较多
2. onefile 每次启动都要解压，非常慢
3. onedir 更稳定，PySide6 兼容性更好

### 使用一键打包脚本

```powershell
cd "D:\DeepSeek Monitor\deepseek-monitor"
powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1
```

脚本会自动完成所有步骤，并验证打包产物没有内置 Chromium 浏览器本体。
输出在：

```text
dist\DeepSeek Monitor\DeepSeek Monitor.exe
```

### 手动打包步骤

如果要手动执行每一步：

```powershell
cd "D:\DeepSeek Monitor\deepseek-monitor"

# 1. 安装依赖
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. 清理旧产物
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue

# 3. 打包
.\.venv\Scripts\python.exe -m PyInstaller DeepSeekMonitor.spec --noconfirm
```

### 安装包输出结构

```text
dist\DeepSeek Monitor\
  ├── DeepSeek Monitor.exe     # 主程序
  └── _internal\               # Python 运行时 + 所有依赖
      ├── playwright\
      │   └── driver\          # node.exe，不内置 Chromium 浏览器本体
      ├── PySide6\
      ├── python312.dll
      └── ...
```

用户拿到 `DeepSeek Monitor` 文件夹后直接运行即可，无需安装 Python。自动同步优先使用电脑上的默认 Edge / Chrome；如果默认浏览器不是 Chromium 系浏览器，则会尝试系统 Edge、Chrome。手动导入 ZIP/CSV 不依赖浏览器。

---

## 运行已打包的 EXE

1. 打开 `dist\DeepSeek Monitor\DeepSeek Monitor.exe`
2. 点击 ⚙ 设置，填写 DeepSeek API Key
3. **首次使用自动同步**：点击"打开登录窗口"→ 在弹出浏览器中登录 DeepSeek → 关闭窗口 → 点击刷新
4. 之后每次点击刷新都会自动静默同步用量

### 常见问题

| 提示 | 原因 | 解决方法 |
|---|---|---|
| "未找到可用浏览器" | 电脑没有 Microsoft Edge / Google Chrome，也没有 Playwright Chromium | 安装 Microsoft Edge 或 Google Chrome 后重试 |
| "需要登录 DeepSeek 后才能自动同步用量" | 登录状态过期 | 点击"打开登录窗口"重新登录 |
| "请先在设置中填写 API Key" | 未配置 Key | 点击 ⚙ 设置，输入 API Key |
| 自动同步失败 | 页面结构变化或网络问题 | 使用右侧"导入"按钮手动导入 ZIP/CSV |

手动导入 ZIP/CSV 始终可用，不依赖 Playwright。

---

## 自动刷新

三种触发方式：

- 手动点击右上角 ↻ 按钮
- 启动后 1.5 秒自动刷新（可在设置中关闭）
- 定时自动刷新（5/10/30/60 分钟，可在设置中关闭）

---

## 常见 API 错误提示

- **401**：API Key 错误或已失效
- **402**：账户余额不足
- **429**：请求太频繁
- **500**：DeepSeek 服务器错误
- **503**：DeepSeek 服务暂时不可用
- 网络连接失败：检查网络后重试
- 请求超时：稍后重试

---

## 技术栈

| 层 | 技术 |
|---|---|
| UI | PySide6-Essentials 6.7 |
| HTTP | requests |
| 浏览器自动化 | Playwright，优先使用系统默认 Edge / Chrome |
| 凭据管理 | keyring (Windows Credential Manager) |
| 数据存储 | SQLite |
| 配置 | JSON + keyring |
| 打包 | PyInstaller (onedir) |

---

## 后续预留

- 最小化到系统托盘
- 开机自启
- 接入真实 DeepSeek 调用脚本，自动记录 token 用量
