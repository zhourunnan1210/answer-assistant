# -*- mode: python ; coding: utf-8 -*-
"""答题助手 PyInstaller 打包配置（onedir 目录版，供 Inno Setup 制作安装包）。

为什么 onedir 而不是 onefile：
- 本地语音识别模型（models/sense-voice，约 228MB）不嵌入 exe，随安装包附带；
- onefile 每次启动需自解压数百 MB，启动慢；onedir 启动快、便于安装包分发。

SSL 修复：强制使用 Python 自带的 OpenSSL DLL（DLLs 目录）。
否则在 Git Bash 环境打包时，PyInstaller 的依赖分析会把 PATH 中
Git for Windows（mingw64/bin）的不兼容 OpenSSL 打进包里，
导致运行时 _ssl 加载失败：DLL load failed（找不到指定的程序），
进而所有 HTTPS 请求报 "SSL module is not available"。
"""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

PY_DLLS = Path(sys.base_prefix) / "DLLs"
SSL_DLLS = ("libcrypto-3-x64.dll", "libssl-3-x64.dll")

# sherpa_onnx 原生库（onnxruntime.dll / sherpa-onnx-c-api.dll / _sherpa_onnx.pyd）
# 位于包内 lib/ 目录，collect_all 会作为 binaries 一并收集
datas, binaries, hiddenimports = collect_all("sherpa_onnx")

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

# 移除可能来自 PATH（Git/mingw64 等）的错误 OpenSSL DLL，替换为 Python 自带版本
a.binaries = [b for b in a.binaries if b[0] not in SSL_DLLS]
for dll in SSL_DLLS:
    src = PY_DLLS / dll
    assert src.exists(), f"找不到 Python 自带的 {src}"
    a.binaries.append((dll, str(src), "BINARY"))

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="答题助手",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="答题助手",
)
