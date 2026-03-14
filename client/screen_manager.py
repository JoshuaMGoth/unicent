"""
Client-side screen information & clipboard — cross-platform.

Detects all connected displays, their resolutions, positions,
and scale factors.
- macOS:   Quartz/AppKit
- Linux:   xrandr, /sys/class/drm
- Windows: ctypes user32

Also provides clipboard read/write.
"""

import logging
import platform
import subprocess
import json
from typing import List

log = logging.getLogger(__name__)

_SYSTEM = platform.system()


def get_macos_screens() -> List[dict]:
    """Get screen info — dispatches to platform-specific implementation."""
    return get_client_screens()


def get_client_screens() -> List[dict]:
    """Get screen info for the client machine (any OS)."""
    if _SYSTEM == 'Darwin':
        return _get_screens_macos()
    elif _SYSTEM == 'Linux':
        return _get_screens_linux()
    elif _SYSTEM == 'Windows':
        return _get_screens_windows()
    return [{'width': 1920, 'height': 1080, 'x': 0, 'y': 0, 'scale': 1.0, 'name': 'default'}]


def _get_screens_macos() -> List[dict]:
    screens = []
    try:
        from Quartz import CGGetActiveDisplayList, CGDisplayBounds
        try:
            from AppKit import NSScreen
        except ImportError:
            NSScreen = None
        (err, display_ids, count) = CGGetActiveDisplayList(16, None, None)
        if err == 0 and display_ids:
            ns_screens = NSScreen.screens() if NSScreen else []
            for i, did in enumerate(display_ids):
                bounds = CGDisplayBounds(did)
                scale = 1.0
                if ns_screens:
                    for ns in ns_screens:
                        frame = ns.frame()
                        if (abs(frame.origin.x - bounds.origin.x) < 1 and
                                abs(frame.origin.y - bounds.origin.y) < 1):
                            scale = ns.backingScaleFactor()
                            break
                name = f"Display {i + 1}"
                if ns_screens and i < len(ns_screens):
                    try:
                        name = ns_screens[i].localizedName()
                    except Exception:
                        pass
                screens.append({
                    'width': int(bounds.size.width), 'height': int(bounds.size.height),
                    'x': int(bounds.origin.x), 'y': int(bounds.origin.y),
                    'scale': float(scale), 'name': name,
                })
        if screens:
            return screens
    except ImportError:
        pass
    # Fallback: system_profiler
    try:
        result = subprocess.run(['system_profiler', 'SPDisplaysDataType', '-json'],
                                capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            x_offset = 0
            for gpu in data.get('SPDisplaysDataType', []):
                for display in gpu.get('spdisplays_ndrvs', []):
                    resolution = display.get('_spdisplays_resolution', '')
                    if ' x ' in resolution:
                        parts = resolution.split(' x ')
                        try:
                            w = int(parts[0].strip())
                            h_part = parts[1].split('@')[0].split('(')[0].strip()
                            h = int(h_part)
                            scale = 2.0 if 'Retina' in display.get('spdisplays_display_type', '') else 1.0
                            if scale == 2.0:
                                w //= 2
                                h //= 2
                            screens.append({
                                'width': w, 'height': h, 'x': x_offset, 'y': 0,
                                'scale': scale,
                                'name': display.get('_name', f'Display {len(screens)+1}'),
                            })
                            x_offset += w
                        except (ValueError, IndexError):
                            continue
            if screens:
                return screens
    except Exception:
        pass
    return [{'width': 1920, 'height': 1080, 'x': 0, 'y': 0, 'scale': 2.0, 'name': 'Default'}]


def _get_screens_linux() -> List[dict]:
    screens = []
    try:
        import re
        result = subprocess.run(['xrandr', '--query'],
                                capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                match = re.match(r'.+\s+connected\s+(?:primary\s+)?(\d+)x(\d+)\+(\d+)\+(\d+)', line)
                if match:
                    screens.append({
                        'width': int(match.group(1)), 'height': int(match.group(2)),
                        'x': int(match.group(3)), 'y': int(match.group(4)),
                        'scale': 1.0, 'name': line.split()[0],
                    })
            if screens:
                return screens
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    try:
        import glob
        for mode_path in glob.glob('/sys/class/drm/card*-*/modes'):
            with open(mode_path) as f:
                first_mode = f.readline().strip()
                if 'x' in first_mode:
                    w, h = first_mode.split('x')
                    connector = mode_path.split('/')[-2]
                    status_path = mode_path.replace('/modes', '/status')
                    try:
                        with open(status_path) as sf:
                            if sf.read().strip() != 'connected':
                                continue
                    except FileNotFoundError:
                        pass
                    screens.append({
                        'width': int(w), 'height': int(h),
                        'x': len(screens) * int(w), 'y': 0,
                        'scale': 1.0, 'name': connector,
                    })
        if screens:
            return screens
    except Exception:
        pass
    return [{'width': 1920, 'height': 1080, 'x': 0, 'y': 0, 'scale': 1.0, 'name': 'default'}]


def _get_screens_windows() -> List[dict]:
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        monitors = []

        def enum_proc(hMonitor, hdcMonitor, lprcMonitor, dwData):
            class MONITORINFOEX(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD),
                    ("szDevice", ctypes.c_wchar * 32),
                ]
            mi = MONITORINFOEX()
            mi.cbSize = ctypes.sizeof(MONITORINFOEX)
            user32.GetMonitorInfoW(hMonitor, ctypes.byref(mi))
            monitors.append({
                'width': mi.rcMonitor.right - mi.rcMonitor.left,
                'height': mi.rcMonitor.bottom - mi.rcMonitor.top,
                'x': mi.rcMonitor.left, 'y': mi.rcMonitor.top,
                'scale': 1.0, 'name': mi.szDevice,
            })
            return 1

        MONITORENUMPROC = ctypes.WINFUNCTYPE(
            ctypes.c_int, wintypes.HMONITOR, wintypes.HDC,
            ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
        user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(enum_proc), 0)
        if monitors:
            return monitors
    except Exception:
        pass
    return [{'width': 1920, 'height': 1080, 'x': 0, 'y': 0, 'scale': 1.0, 'name': 'default'}]


# ────────────────────────────────────────────────────────────
# Clipboard
# ────────────────────────────────────────────────────────────

def get_clipboard_content() -> str:
    """Get clipboard text content."""
    if _SYSTEM == 'Darwin':
        try:
            result = subprocess.run(['pbpaste'], capture_output=True, text=True, timeout=5)
            return result.stdout if result.returncode == 0 else ''
        except Exception:
            return ''
    elif _SYSTEM == 'Linux':
        for cmd in [['xclip', '-selection', 'clipboard', '-o'],
                    ['xsel', '--clipboard', '--output']]:
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    return result.stdout
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue
        return ''
    elif _SYSTEM == 'Windows':
        try:
            import ctypes
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            CF_UNICODETEXT = 13
            if user32.OpenClipboard(0):
                try:
                    handle = user32.GetClipboardData(CF_UNICODETEXT)
                    if handle:
                        data = kernel32.GlobalLock(handle)
                        if data:
                            text = ctypes.c_wchar_p(data).value
                            kernel32.GlobalUnlock(handle)
                            return text or ''
                finally:
                    user32.CloseClipboard()
        except Exception:
            pass
        return ''
    return ''


def set_clipboard_content(content: str):
    """Set clipboard text content."""
    if _SYSTEM == 'Darwin':
        try:
            p = subprocess.Popen(['pbcopy'], stdin=subprocess.PIPE)
            p.communicate(content.encode('utf-8'), timeout=5)
        except Exception:
            pass
    elif _SYSTEM == 'Linux':
        for cmd in [['xclip', '-selection', 'clipboard'],
                    ['xsel', '--clipboard', '--input']]:
            try:
                p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
                p.communicate(content.encode('utf-8'), timeout=5)
                return
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue
    elif _SYSTEM == 'Windows':
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            CF_UNICODETEXT = 13
            GMEM_MOVEABLE = 0x0002
            data = content.encode('utf-16-le') + b'\x00\x00'
            if user32.OpenClipboard(0):
                try:
                    user32.EmptyClipboard()
                    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
                    if handle:
                        ptr = kernel32.GlobalLock(handle)
                        ctypes.memmove(ptr, data, len(data))
                        kernel32.GlobalUnlock(handle)
                        user32.SetClipboardData(CF_UNICODETEXT, handle)
                finally:
                    user32.CloseClipboard()
        except Exception:
            pass
