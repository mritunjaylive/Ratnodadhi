"""
detect_windows.py – registry-based reader detection for Windows.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from booklib.readers.models import Reader

# Executables that are launchers, not readers
_SKIP_EXES = frozenset({
    "rundll32.exe", "explorer.exe", "cmd.exe", "powershell.exe",
    "msiexec.exe", "wscript.exe", "cscript.exe",
})


def _winreg():
    try:
        import winreg
        return winreg
    except ImportError:
        return None


def _read_value(key, name: str) -> str | None:
    wr = _winreg()
    if not wr:
        return None
    try:
        return wr.QueryValueEx(key, name)[0]
    except (OSError, wr.error):
        return None


def _open_key(root, path: str):
    wr = _winreg()
    if not wr:
        return None
    try:
        return wr.OpenKey(root, path)
    except (OSError, wr.error):
        return None


def _exe_from_command(cmd: str) -> str | None:
    """Extract the executable path from a shell command string."""
    cmd = cmd.strip()
    if cmd.startswith('"'):
        m = re.match(r'"([^"]+\.exe)"', cmd, re.IGNORECASE)
    else:
        m = re.match(r'([^\s"]+\.exe)', cmd, re.IGNORECASE)
    return m.group(1) if m else None


def _resolve_progid(progid: str) -> str | None:
    wr = _winreg()
    if not wr:
        return None
    for root in (wr.HKEY_CURRENT_USER, wr.HKEY_LOCAL_MACHINE):
        key = _open_key(root, rf"SOFTWARE\Classes\{progid}\shell\open\command")
        if key:
            cmd = _read_value(key, "")
            key.Close()
            if cmd:
                return _exe_from_command(cmd)
    return None


def _resolve_appname(app_exe: str) -> str | None:
    """Resolve an app exe name through HKCR\\Applications\\<exe>."""
    wr = _winreg()
    if not wr:
        return None
    key = _open_key(wr.HKEY_CLASSES_ROOT, rf"Applications\{app_exe}\shell\open\command")
    if key:
        cmd = _read_value(key, "")
        key.Close()
        if cmd:
            return _exe_from_command(cmd)
    return None


def _friendly_name(exe_path: str) -> str:
    """Try to get a human-friendly name from version resources."""
    name = Path(exe_path).stem
    try:
        import ctypes
        import ctypes.wintypes as wt
        vsize = ctypes.windll.version.GetFileVersionInfoSizeW(exe_path, None)
        if vsize:
            buf = ctypes.create_string_buffer(vsize)
            if ctypes.windll.version.GetFileVersionInfoW(exe_path, 0, vsize, buf):
                sub = ctypes.create_unicode_buffer(r"\StringFileInfo\040904B0\FileDescription")
                p = ctypes.c_wchar_p()
                size = ctypes.c_uint()
                if ctypes.windll.version.VerQueryValueW(buf, sub, ctypes.byref(p), ctypes.byref(size)):
                    desc = p.value
                    if desc:
                        name = desc
    except Exception:
        pass
    return name


def detect_for_extension(ext: str, formats: frozenset[str]) -> list[Reader]:
    """Detect registered readers for a file extension (e.g. 'pdf')."""
    if sys.platform != "win32":
        return []
    wr = _winreg()
    if not wr:
        return []

    dot_ext = f".{ext.lower()}"
    exe_paths: dict[str, str] = {}  # normalized_exe → display_name

    for root in (wr.HKEY_CURRENT_USER, wr.HKEY_LOCAL_MACHINE):
        # OpenWithProgids
        key = _open_key(root, rf"SOFTWARE\Classes\{dot_ext}\OpenWithProgids")
        if key:
            idx = 0
            while True:
                try:
                    progid = wr.EnumValue(key, idx)[0]
                    idx += 1
                    exe = _resolve_progid(progid)
                    if exe and Path(exe).exists():
                        norm = exe.lower()
                        if norm not in exe_paths and Path(exe).name.lower() not in _SKIP_EXES:
                            exe_paths[norm] = _friendly_name(exe)
                except OSError:
                    break
            key.Close()

        # OpenWithList
        key = _open_key(root, rf"SOFTWARE\Classes\{dot_ext}\OpenWithList")
        if key:
            idx = 0
            while True:
                try:
                    app_exe = wr.EnumKey(key, idx)
                    idx += 1
                    exe = _resolve_appname(app_exe)
                    if exe and Path(exe).exists():
                        norm = exe.lower()
                        if norm not in exe_paths and app_exe.lower() not in _SKIP_EXES:
                            exe_paths[norm] = _friendly_name(exe)
                except OSError:
                    break
            key.Close()

    readers: list[Reader] = []
    for norm_exe, name in exe_paths.items():
        readers.append(Reader(
            key=f"detected:{norm_exe}",
            name=name,
            exe=norm_exe,
            formats=formats,
        ))
    return readers


def detect_all(extensions: list[str]) -> list[Reader]:
    """Detect readers for all given extensions."""
    all_readers: dict[str, Reader] = {}
    for ext in extensions:
        for r in detect_for_extension(ext, frozenset({ext})):
            if r.key not in all_readers:
                all_readers[r.key] = r
    return list(all_readers.values())
