"""PyInstaller runtime hook for Playwright.

在 PyInstaller onedir 打包环境中，设置 PLAYWRIGHT_NODEJS_PATH
指向打包的 node.exe，确保 Playwright 能找到 Node.js 运行时。

瘦身版不内置 Chromium，因此把 PLAYWRIGHT_BROWSERS_PATH
指向用户缓存目录，避免 frozen 环境默认寻找包内 .local-browsers。

该 hook 在 main.py 之前运行（由 spec 的 runtime_hooks 配置）。
"""

import os
import sys

if getattr(sys, "frozen", False):
    _node_exe = os.path.join(sys._MEIPASS, "playwright", "driver", "node.exe")
    if os.path.isfile(_node_exe):
        os.environ.setdefault("PLAYWRIGHT_NODEJS_PATH", _node_exe)

    if "PLAYWRIGHT_BROWSERS_PATH" not in os.environ:
        _local_app_data = os.environ.get("LOCALAPPDATA")
        if _local_app_data:
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(_local_app_data, "ms-playwright")
