"""
macOS screen information manager.

Detects all connected displays, their resolutions, positions,
and scale factors using CoreGraphics/AppKit.
"""

import logging
import subprocess
import json
from typing import List

log = logging.getLogger(__name__)


def get_macos_screens() -> List[dict]:
    """Get screen information for all connected macOS displays.

    Returns a list of screen dictionaries with keys:
        width, height, x, y, scale, name
    """
    screens = []

    # Method 1: Try using Quartz/AppKit
    try:
        screens = _get_screens_quartz()
        if screens:
            return screens
    except Exception as e:
        log.debug(f"Quartz screen detection failed: {e}")

    # Method 2: Try using system_profiler
    try:
        screens = _get_screens_system_profiler()
        if screens:
            return screens
    except Exception as e:
        log.debug(f"system_profiler detection failed: {e}")

    # Method 3: Fallback using screenresolution command or defaults
    log.warning("Could not detect screens, using defaults")
    return [{
        'width': 1920,
        'height': 1080,
        'x': 0,
        'y': 0,
        'scale': 2.0,
        'name': 'Default Display',
    }]


def _get_screens_quartz() -> List[dict]:
    """Get screen info using Quartz (CoreGraphics)."""
    from Quartz import (
        CGGetActiveDisplayList,
        CGDisplayBounds,
        CGDisplayScreenSize,
    )
    try:
        from AppKit import NSScreen
    except ImportError:
        NSScreen = None

    max_displays = 16
    (err, display_ids, count) = CGGetActiveDisplayList(max_displays, None, None)
    if err != 0:
        return []

    screens = []
    ns_screens = NSScreen.screens() if NSScreen else []

    for i, did in enumerate(display_ids):
        bounds = CGDisplayBounds(did)

        # Determine scale factor
        scale = 1.0
        if ns_screens:
            for ns in ns_screens:
                frame = ns.frame()
                if (abs(frame.origin.x - bounds.origin.x) < 1 and
                        abs(frame.origin.y - bounds.origin.y) < 1):
                    scale = ns.backingScaleFactor()
                    break

        # Get display name
        name = f"Display {i + 1}"
        if ns_screens and i < len(ns_screens):
            try:
                name = ns_screens[i].localizedName()
            except Exception:
                pass

        screens.append({
            'width': int(bounds.size.width),
            'height': int(bounds.size.height),
            'x': int(bounds.origin.x),
            'y': int(bounds.origin.y),
            'scale': float(scale),
            'name': name,
        })

    return screens


def _get_screens_system_profiler() -> List[dict]:
    """Get screen info using system_profiler command."""
    result = subprocess.run(
        ['system_profiler', 'SPDisplaysDataType', '-json'],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        return []

    data = json.loads(result.stdout)
    screens = []
    x_offset = 0

    for gpu in data.get('SPDisplaysDataType', []):
        for display in gpu.get('spdisplays_ndrvs', []):
            resolution = display.get('_spdisplays_resolution', '')
            # Parse "3456 x 2234" or "1920 x 1080 @ 60Hz"
            if ' x ' in resolution:
                parts = resolution.split(' x ')
                try:
                    w = int(parts[0].strip())
                    h_part = parts[1].split('@')[0].split('(')[0].strip()
                    h = int(h_part)

                    # Check for Retina
                    scale = 1.0
                    if 'Retina' in display.get('spdisplays_display_type', ''):
                        scale = 2.0
                        # Retina resolutions are reported at native pixels
                        # but the logical resolution is half
                        w = w // 2
                        h = h // 2

                    name = display.get('_name', f'Display {len(screens) + 1}')

                    screens.append({
                        'width': w,
                        'height': h,
                        'x': x_offset,
                        'y': 0,
                        'scale': scale,
                        'name': name,
                    })
                    x_offset += w
                except (ValueError, IndexError):
                    continue

    return screens


def get_clipboard_content() -> str:
    """Get the current clipboard content on macOS."""
    try:
        result = subprocess.run(
            ['pbpaste'],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout if result.returncode == 0 else ''
    except Exception:
        return ''


def set_clipboard_content(content: str):
    """Set the clipboard content on macOS."""
    try:
        proc = subprocess.Popen(
            ['pbcopy'],
            stdin=subprocess.PIPE,
        )
        proc.communicate(input=content.encode('utf-8'), timeout=5)
    except Exception as e:
        log.error(f"Failed to set clipboard: {e}")
