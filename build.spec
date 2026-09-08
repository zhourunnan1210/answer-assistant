# -*- mode: python ; coding: utf-8 -*-
"""答题助手 PyInstaller 打包配置。

修复：强制使用 Python 自带的 OpenSSL DLL（DLLs 目录）。
否则在 Git Bash 环境打包时，PyInstaller 的依赖分析会把 PATH 中
Git for Windows（mingw64/bin）的不兼容 OpenSSL 打进包里，
导致运行时 _ssl 加载失败：DLL load failed（找不到指定的程序），
进而所有 HTTPS 请求报 "SSL module is not available"。
"""
import sys
from pathlib import Path

PY_DLLS = Path(sys.base_prefix) / "DLLs"
SSL_DLLS = ("libcrypto-3-x64.dll", "libssl-3-x64.dll")

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
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
    a.binaries,
    a.datas,
    [],
    name="答题助手",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
