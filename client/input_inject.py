"""
macOS input injection using Quartz (CoreGraphics).

Injects mouse moves, clicks, scrolls, and keyboard events into macOS
using CGEvent APIs. Requires Accessibility permissions.
"""

import logging
import subprocess
from typing import Optional

log = logging.getLogger(__name__)

try:
    import Quartz
    from Quartz import (
        CGEventCreateMouseEvent,
        CGEventCreateKeyboardEvent,
        CGEventCreateScrollWheelEvent2,
        CGEventPost,
        CGEventSetIntegerValueField,
        CGEventSetFlags,
        CGEventGetFlags,
        CGDisplayBounds,
        CGMainDisplayID,
        CGWarpMouseCursorPosition,
        CGAssociateMouseAndMouseCursorPosition,
        CGEventSourceCreate,
        kCGEventSourceStateHIDSystemState,
        kCGEventMouseMoved,
        kCGEventLeftMouseDown,
        kCGEventLeftMouseUp,
        kCGEventRightMouseDown,
        kCGEventRightMouseUp,
        kCGEventOtherMouseDown,
        kCGEventOtherMouseUp,
        kCGEventLeftMouseDragged,
        kCGEventRightMouseDragged,
        kCGEventOtherMouseDragged,
        kCGHIDEventTap,
        kCGMouseEventDeltaX,
        kCGMouseEventDeltaY,
        kCGMouseEventClickState,
        kCGMouseEventButtonNumber,
        kCGScrollEventUnitPixel,
        kCGEventKeyDown,
        kCGEventKeyUp,
        kCGEventFlagsChanged,
        kCGEventFlagMaskShift,
        kCGEventFlagMaskControl,
        kCGEventFlagMaskAlternate,
        kCGEventFlagMaskCommand,
    )
    QUARTZ_AVAILABLE = True
except ImportError:
    QUARTZ_AVAILABLE = False
    log.warning("Quartz framework not available")

# Import key mapping
from shared.keymap import (
    LINUX_TO_MACOS, LINUX_BTN_TO_MACOS,
    LINUX_MOD_TO_MACOS_FLAG,
    KEY_LEFTSHIFT, KEY_RIGHTSHIFT,
    KEY_LEFTCTRL, KEY_RIGHTCTRL,
    KEY_LEFTALT, KEY_RIGHTALT,
    KEY_LEFTMETA, KEY_RIGHTMETA,
)

# Modifier keycodes (Linux evdev)
MODIFIER_KEYCODES = {
    KEY_LEFTSHIFT, KEY_RIGHTSHIFT,
    KEY_LEFTCTRL, KEY_RIGHTCTRL,
    KEY_LEFTALT, KEY_RIGHTALT,
    KEY_LEFTMETA, KEY_RIGHTMETA,
}


class InputInjector:
    """Injects input events into macOS using Quartz/CoreGraphics.

    Handles:
    - Relative mouse movement (with position tracking)
    - Absolute mouse positioning
    - Mouse button clicks
    - Scroll wheel events
    - Keyboard events with modifier tracking
    """

    def __init__(self):
        if not QUARTZ_AVAILABLE:
            raise RuntimeError(
                "Quartz framework not available. "
                "Install pyobjc-framework-Quartz: pip3 install pyobjc-framework-Quartz"
            )

        # Create event source for HID-level injection
        self._source = CGEventSourceCreate(kCGEventSourceStateHIDSystemState)

        # Current cursor position (absolute)
        self._cursor_x: float = 0.0
        self._cursor_y: float = 0.0

        # Current modifier flags
        self._modifier_flags: int = 0

        # Mouse button state
        self._buttons_pressed: set = set()  # Set of pressed button numbers

        # Screen bounds
        self._update_screen_bounds()

        # Initialize cursor position
        self._init_cursor_position()

    def _update_screen_bounds(self):
        """Get the total screen bounds across all displays."""
        main_display = CGMainDisplayID()
        bounds = CGDisplayBounds(main_display)
        self._min_x = bounds.origin.x
        self._min_y = bounds.origin.y
        self._max_x = bounds.origin.x + bounds.size.width
        self._max_y = bounds.origin.y + bounds.size.height

        # For multi-monitor, we need to extend bounds
        try:
            from Quartz import CGGetActiveDisplayList
            max_displays = 16
            (err, display_ids, count) = CGGetActiveDisplayList(max_displays, None, None)
            if err == 0 and display_ids:
                for did in display_ids:
                    b = CGDisplayBounds(did)
                    self._min_x = min(self._min_x, b.origin.x)
                    self._min_y = min(self._min_y, b.origin.y)
                    self._max_x = max(self._max_x, b.origin.x + b.size.width)
                    self._max_y = max(self._max_y, b.origin.y + b.size.height)
        except Exception as e:
            log.debug(f"Multi-display detection: {e}")

        log.info(f"Screen bounds: ({self._min_x},{self._min_y}) to "
                 f"({self._max_x},{self._max_y})")

    def _init_cursor_position(self):
        """Get the current cursor position."""
        try:
            from Quartz import CGEventCreate, CGEventGetLocation
            event = CGEventCreate(None)
            if event:
                loc = CGEventGetLocation(event)
                self._cursor_x = loc.x
                self._cursor_y = loc.y
        except Exception:
            self._cursor_x = self._max_x / 2
            self._cursor_y = self._max_y / 2

    def move_mouse_relative(self, dx: int, dy: int):
        """Move the mouse cursor by a relative amount."""
        new_x = self._cursor_x + dx
        new_y = self._cursor_y + dy

        # Clamp to screen bounds
        new_x = max(self._min_x, min(new_x, self._max_x - 1))
        new_y = max(self._min_y, min(new_y, self._max_y - 1))

        self._cursor_x = new_x
        self._cursor_y = new_y

        # Determine event type based on button state
        if 0 in self._buttons_pressed:
            event_type = kCGEventLeftMouseDragged
        elif 1 in self._buttons_pressed:
            event_type = kCGEventRightMouseDragged
        elif self._buttons_pressed:
            event_type = kCGEventOtherMouseDragged
        else:
            event_type = kCGEventMouseMoved

        point = Quartz.CGPointMake(new_x, new_y)
        event = CGEventCreateMouseEvent(self._source, event_type, point, 0)
        if event:
            # Set delta values for proper relative movement
            CGEventSetIntegerValueField(event, kCGMouseEventDeltaX, dx)
            CGEventSetIntegerValueField(event, kCGMouseEventDeltaY, dy)
            CGEventPost(kCGHIDEventTap, event)

    def move_mouse_absolute(self, x: int, y: int):
        """Move the mouse cursor to an absolute position."""
        self._cursor_x = float(x)
        self._cursor_y = float(y)

        point = Quartz.CGPointMake(x, y)
        event = CGEventCreateMouseEvent(
            self._source, kCGEventMouseMoved, point, 0
        )
        if event:
            CGEventPost(kCGHIDEventTap, event)

    def warp_cursor(self, x: int, y: int):
        """Instantly warp the cursor to a position (no event generated)."""
        self._cursor_x = float(x)
        self._cursor_y = float(y)
        point = Quartz.CGPointMake(x, y)
        CGWarpMouseCursorPosition(point)
        # Re-associate mouse and cursor after warp
        CGAssociateMouseAndMouseCursorPosition(True)

    def mouse_button(self, linux_button: int, state: int):
        """Handle a mouse button event.

        Args:
            linux_button: Linux evdev button code (BTN_LEFT=272, etc.)
            state: 0=release, 1=press
        """
        mac_button = LINUX_BTN_TO_MACOS.get(linux_button, -1)
        if mac_button < 0:
            log.debug(f"Unknown button: {linux_button}")
            return

        point = Quartz.CGPointMake(self._cursor_x, self._cursor_y)

        if mac_button == 0:  # Left button
            event_type = kCGEventLeftMouseDown if state else kCGEventLeftMouseUp
        elif mac_button == 1:  # Right button
            event_type = kCGEventRightMouseDown if state else kCGEventRightMouseUp
        else:  # Other buttons
            event_type = kCGEventOtherMouseDown if state else kCGEventOtherMouseUp

        event = CGEventCreateMouseEvent(
            self._source, event_type, point, mac_button
        )
        if event:
            if mac_button > 1:
                CGEventSetIntegerValueField(
                    event, kCGMouseEventButtonNumber, mac_button
                )
            CGEventPost(kCGHIDEventTap, event)

        # Track button state
        if state:
            self._buttons_pressed.add(mac_button)
        else:
            self._buttons_pressed.discard(mac_button)

    def scroll(self, dx: int, dy: int):
        """Handle a scroll wheel event.

        Args:
            dx: Horizontal scroll amount
            dy: Vertical scroll amount (positive = up)
        """
        # CGEventCreateScrollWheelEvent2 takes (source, units, wheelCount, v, h)
        event = CGEventCreateScrollWheelEvent2(
            self._source,
            kCGScrollEventUnitPixel,
            2,  # number of axes
            dy * 3,  # vertical (scale up for reasonable speed)
            dx * 3,  # horizontal
        )
        if event:
            CGEventPost(kCGHIDEventTap, event)

    def key_event(self, linux_keycode: int, state: int):
        """Handle a keyboard event.

        Args:
            linux_keycode: Linux evdev key code
            state: 0=release, 1=press, 2=repeat
        """
        # Handle modifier keys specially
        if linux_keycode in MODIFIER_KEYCODES:
            self._handle_modifier(linux_keycode, state)
            return

        # Map to macOS keycode
        mac_keycode = LINUX_TO_MACOS.get(linux_keycode, -1)
        if mac_keycode < 0:
            log.debug(f"Unmapped key: {linux_keycode}")
            return

        key_down = state in (1, 2)  # Press or repeat
        event = CGEventCreateKeyboardEvent(
            self._source, mac_keycode, key_down
        )
        if event:
            # Apply current modifier flags
            CGEventSetFlags(event, self._modifier_flags)
            CGEventPost(kCGHIDEventTap, event)

    def _handle_modifier(self, linux_keycode: int, state: int):
        """Handle modifier key press/release."""
        mac_flag = LINUX_MOD_TO_MACOS_FLAG.get(linux_keycode, 0)
        if not mac_flag:
            return

        mac_keycode = LINUX_TO_MACOS.get(linux_keycode, -1)
        if mac_keycode < 0:
            return

        if state == 1:  # Press
            self._modifier_flags |= mac_flag
        elif state == 0:  # Release
            self._modifier_flags &= ~mac_flag

        # Create a flags-changed event
        event = CGEventCreateKeyboardEvent(
            self._source, mac_keycode, state == 1
        )
        if event:
            CGEventSetFlags(event, self._modifier_flags)
            CGEventPost(kCGHIDEventTap, event)

    def reset_modifiers(self):
        """Release all modifier keys."""
        for linux_kc in MODIFIER_KEYCODES:
            mac_kc = LINUX_TO_MACOS.get(linux_kc, -1)
            if mac_kc >= 0:
                event = CGEventCreateKeyboardEvent(self._source, mac_kc, False)
                if event:
                    CGEventPost(kCGHIDEventTap, event)
        self._modifier_flags = 0
        self._buttons_pressed.clear()

    def release_all(self):
        """Release all keys and buttons."""
        self.reset_modifiers()

    @property
    def cursor_position(self):
        """Get current cursor position as (x, y)."""
        return (int(self._cursor_x), int(self._cursor_y))


def check_accessibility_permissions() -> bool:
    """Check if the app has accessibility permissions on macOS."""
    try:
        from Quartz import (
            CGEventCreateKeyboardEvent,
            CGEventSourceCreate,
            kCGEventSourceStateHIDSystemState,
        )
        # Try creating a test event
        source = CGEventSourceCreate(kCGEventSourceStateHIDSystemState)
        event = CGEventCreateKeyboardEvent(source, 0, False)
        return event is not None
    except Exception:
        return False


def request_accessibility_permissions():
    """Prompt user to grant accessibility permissions."""
    print("\n  ⚠  Accessibility permissions required!")
    print()
    print("  macOS requires Accessibility access to inject input events.")
    print("  Please grant permission:")
    print()
    print("  1. Open System Settings → Privacy & Security → Accessibility")
    print("  2. Click the + button")
    print("  3. Add Terminal (or iTerm2, or whatever terminal you're using)")
    print("  4. Enable the toggle")
    print("  5. Restart this application")
    print()

    # Try to open the settings pane
    try:
        subprocess.run([
            'open', 'x-apple.systempreferences:'
            'com.apple.preference.security?Privacy_Accessibility'
        ], check=False)
    except Exception:
        pass
