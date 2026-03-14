"""
Key code mapping between Linux evdev and macOS virtual key codes.

Linux uses evdev key codes (KEY_A = 30, etc.) from <linux/input-event-codes.h>.
macOS uses virtual key codes from <Carbon/HIToolbox/Events.h>.

This module provides bidirectional mapping plus mouse button translation.
"""

# Linux evdev key code -> macOS virtual key code
# Source: linux/input-event-codes.h -> Carbon/HIToolbox/Events.h
LINUX_TO_MACOS = {
    # Row 1: Escape + Number row
    1:   0x35,   # KEY_ESC -> kVK_Escape
    2:   0x12,   # KEY_1 -> kVK_ANSI_1
    3:   0x13,   # KEY_2 -> kVK_ANSI_2
    4:   0x14,   # KEY_3 -> kVK_ANSI_3
    5:   0x15,   # KEY_4 -> kVK_ANSI_4
    6:   0x17,   # KEY_5 -> kVK_ANSI_5
    7:   0x16,   # KEY_6 -> kVK_ANSI_6
    8:   0x1A,   # KEY_7 -> kVK_ANSI_7
    9:   0x1C,   # KEY_8 -> kVK_ANSI_8
    10:  0x19,   # KEY_9 -> kVK_ANSI_9
    11:  0x1D,   # KEY_0 -> kVK_ANSI_0
    12:  0x1B,   # KEY_MINUS -> kVK_ANSI_Minus
    13:  0x18,   # KEY_EQUAL -> kVK_ANSI_Equal
    14:  0x33,   # KEY_BACKSPACE -> kVK_Delete (backspace)

    # Row 2: Tab + QWERTY
    15:  0x30,   # KEY_TAB -> kVK_Tab
    16:  0x0C,   # KEY_Q -> kVK_ANSI_Q
    17:  0x0D,   # KEY_W -> kVK_ANSI_W
    18:  0x0E,   # KEY_E -> kVK_ANSI_E
    19:  0x0F,   # KEY_R -> kVK_ANSI_R
    20:  0x11,   # KEY_T -> kVK_ANSI_T
    21:  0x10,   # KEY_Y -> kVK_ANSI_Y
    22:  0x20,   # KEY_U -> kVK_ANSI_U
    23:  0x22,   # KEY_I -> kVK_ANSI_I
    24:  0x1F,   # KEY_O -> kVK_ANSI_O
    25:  0x23,   # KEY_P -> kVK_ANSI_P
    26:  0x21,   # KEY_LEFTBRACE -> kVK_ANSI_LeftBracket
    27:  0x1E,   # KEY_RIGHTBRACE -> kVK_ANSI_RightBracket
    28:  0x24,   # KEY_ENTER -> kVK_Return

    # Row 3: Caps + ASDF + modifiers
    29:  0x3B,   # KEY_LEFTCTRL -> kVK_Control
    30:  0x00,   # KEY_A -> kVK_ANSI_A
    31:  0x01,   # KEY_S -> kVK_ANSI_S
    32:  0x02,   # KEY_D -> kVK_ANSI_D
    33:  0x03,   # KEY_F -> kVK_ANSI_F
    34:  0x05,   # KEY_G -> kVK_ANSI_G
    35:  0x04,   # KEY_H -> kVK_ANSI_H
    36:  0x26,   # KEY_J -> kVK_ANSI_J
    37:  0x28,   # KEY_K -> kVK_ANSI_K
    38:  0x25,   # KEY_L -> kVK_ANSI_L
    39:  0x29,   # KEY_SEMICOLON -> kVK_ANSI_Semicolon
    40:  0x27,   # KEY_APOSTROPHE -> kVK_ANSI_Quote
    41:  0x32,   # KEY_GRAVE -> kVK_ANSI_Grave

    # Row 4: Shift + ZXCV
    42:  0x38,   # KEY_LEFTSHIFT -> kVK_Shift
    43:  0x2A,   # KEY_BACKSLASH -> kVK_ANSI_Backslash
    44:  0x06,   # KEY_Z -> kVK_ANSI_Z
    45:  0x07,   # KEY_X -> kVK_ANSI_X
    46:  0x08,   # KEY_C -> kVK_ANSI_C
    47:  0x09,   # KEY_V -> kVK_ANSI_V
    48:  0x0B,   # KEY_B -> kVK_ANSI_B
    49:  0x2D,   # KEY_N -> kVK_ANSI_N
    50:  0x2E,   # KEY_M -> kVK_ANSI_M
    51:  0x2B,   # KEY_COMMA -> kVK_ANSI_Comma
    52:  0x2F,   # KEY_DOT -> kVK_ANSI_Period
    53:  0x2C,   # KEY_SLASH -> kVK_ANSI_Slash
    54:  0x3C,   # KEY_RIGHTSHIFT -> kVK_RightShift

    # Bottom row
    55:  0x43,   # KEY_KPASTERISK -> kVK_ANSI_KeypadMultiply
    56:  0x3A,   # KEY_LEFTALT -> kVK_Option
    57:  0x31,   # KEY_SPACE -> kVK_Space
    58:  0x39,   # KEY_CAPSLOCK -> kVK_CapsLock

    # Function keys
    59:  0x7A,   # KEY_F1 -> kVK_F1
    60:  0x78,   # KEY_F2 -> kVK_F2
    61:  0x63,   # KEY_F3 -> kVK_F3
    62:  0x76,   # KEY_F4 -> kVK_F4
    63:  0x60,   # KEY_F5 -> kVK_F5
    64:  0x61,   # KEY_F6 -> kVK_F6
    65:  0x62,   # KEY_F7 -> kVK_F7
    66:  0x64,   # KEY_F8 -> kVK_F8
    67:  0x65,   # KEY_F9 -> kVK_F9
    68:  0x6D,   # KEY_F10 -> kVK_F10
    87:  0x67,   # KEY_F11 -> kVK_F11
    88:  0x6F,   # KEY_F12 -> kVK_F12

    # Numlock / scroll lock
    69:  0x47,   # KEY_NUMLOCK -> kVK_ANSI_KeypadClear

    # Numpad
    71:  0x59,   # KEY_KP7 -> kVK_ANSI_Keypad7
    72:  0x5B,   # KEY_KP8 -> kVK_ANSI_Keypad8
    73:  0x5C,   # KEY_KP9 -> kVK_ANSI_Keypad9
    74:  0x4E,   # KEY_KPMINUS -> kVK_ANSI_KeypadMinus
    75:  0x56,   # KEY_KP4 -> kVK_ANSI_Keypad4
    76:  0x57,   # KEY_KP5 -> kVK_ANSI_Keypad5
    77:  0x58,   # KEY_KP6 -> kVK_ANSI_Keypad6
    78:  0x45,   # KEY_KPPLUS -> kVK_ANSI_KeypadPlus
    79:  0x53,   # KEY_KP1 -> kVK_ANSI_Keypad1
    80:  0x54,   # KEY_KP2 -> kVK_ANSI_Keypad2
    81:  0x55,   # KEY_KP3 -> kVK_ANSI_Keypad3
    82:  0x52,   # KEY_KP0 -> kVK_ANSI_Keypad0
    83:  0x41,   # KEY_KPDOT -> kVK_ANSI_KeypadDecimal
    96:  0x4C,   # KEY_KPENTER -> kVK_ANSI_KeypadEnter
    98:  0x4B,   # KEY_KPSLASH -> kVK_ANSI_KeypadDivide

    # Right modifiers
    97:  0x3E,   # KEY_RIGHTCTRL -> kVK_RightControl
    100: 0x3D,   # KEY_RIGHTALT -> kVK_RightOption

    # Navigation cluster
    102: 0x73,   # KEY_HOME -> kVK_Home
    103: 0x7E,   # KEY_UP -> kVK_UpArrow
    104: 0x74,   # KEY_PAGEUP -> kVK_PageUp
    105: 0x7B,   # KEY_LEFT -> kVK_LeftArrow
    106: 0x7C,   # KEY_RIGHT -> kVK_RightArrow
    107: 0x77,   # KEY_END -> kVK_End
    108: 0x7D,   # KEY_DOWN -> kVK_DownArrow
    109: 0x79,   # KEY_PAGEDOWN -> kVK_PageDown
    110: 0x72,   # KEY_INSERT -> kVK_Help
    111: 0x75,   # KEY_DELETE -> kVK_ForwardDelete

    # Super / Meta -> Command
    125: 0x37,   # KEY_LEFTMETA -> kVK_Command
    126: 0x36,   # KEY_RIGHTMETA -> kVK_RightCommand

    # Additional function keys
    183: 0x69,   # KEY_F13 -> kVK_F13
    184: 0x6B,   # KEY_F14 -> kVK_F14
    185: 0x71,   # KEY_F15 -> kVK_F15
    186: 0x6A,   # KEY_F16 -> kVK_F16
    187: 0x40,   # KEY_F17 -> kVK_F17
    188: 0x4F,   # KEY_F18 -> kVK_F18
    189: 0x50,   # KEY_F19 -> kVK_F19
}

# Reverse mapping: macOS virtual key code -> Linux evdev key code
MACOS_TO_LINUX = {v: k for k, v in LINUX_TO_MACOS.items()}


# Linux evdev mouse button codes
# BTN_LEFT = 0x110 (272), BTN_RIGHT = 0x111 (273), BTN_MIDDLE = 0x112 (274)
# macOS button: 0=left, 1=right, 2=middle

LINUX_BTN_TO_MACOS = {
    272: 0,   # BTN_LEFT -> left
    273: 1,   # BTN_RIGHT -> right
    274: 2,   # BTN_MIDDLE -> middle
    275: 3,   # BTN_SIDE -> button 4
    276: 4,   # BTN_EXTRA -> button 5
}

MACOS_BTN_TO_LINUX = {v: k for k, v in LINUX_BTN_TO_MACOS.items()}


# Linux evdev modifier key codes for hotkey detection
KEY_LEFTCTRL = 29
KEY_RIGHTCTRL = 97
KEY_LEFTALT = 56
KEY_RIGHTALT = 100
KEY_LEFTSHIFT = 42
KEY_RIGHTSHIFT = 54
KEY_LEFTMETA = 125
KEY_RIGHTMETA = 126
KEY_SCROLLLOCK = 70

# Common keys for hotkey combos
KEY_S = 31
KEY_T = 20
KEY_R = 19
KEY_1 = 2
KEY_2 = 3
KEY_3 = 4
KEY_4 = 5
KEY_5 = 6
KEY_C = 46

# Modifier sets for easy checking
CTRL_KEYS = {KEY_LEFTCTRL, KEY_RIGHTCTRL}
ALT_KEYS = {KEY_LEFTALT, KEY_RIGHTALT}
SHIFT_KEYS = {KEY_LEFTSHIFT, KEY_RIGHTSHIFT}
META_KEYS = {KEY_LEFTMETA, KEY_RIGHTMETA}

# macOS modifier flags for CGEvent
MACOS_MOD_SHIFT = 0x020000       # kCGEventFlagMaskShift
MACOS_MOD_CONTROL = 0x040000     # kCGEventFlagMaskControl
MACOS_MOD_OPTION = 0x080000      # kCGEventFlagMaskAlternate
MACOS_MOD_COMMAND = 0x100000     # kCGEventFlagMaskCommand
MACOS_MOD_CAPSLOCK = 0x010000    # kCGEventFlagMaskAlphaShift

# Mapping from Linux modifier keycodes to macOS modifier flags
LINUX_MOD_TO_MACOS_FLAG = {
    KEY_LEFTSHIFT:  MACOS_MOD_SHIFT,
    KEY_RIGHTSHIFT: MACOS_MOD_SHIFT,
    KEY_LEFTCTRL:   MACOS_MOD_CONTROL,
    KEY_RIGHTCTRL:  MACOS_MOD_CONTROL,
    KEY_LEFTALT:    MACOS_MOD_OPTION,
    KEY_RIGHTALT:   MACOS_MOD_OPTION,
    KEY_LEFTMETA:   MACOS_MOD_COMMAND,
    KEY_RIGHTMETA:  MACOS_MOD_COMMAND,
}


def linux_keycode_to_macos(keycode: int) -> int:
    """Convert a Linux evdev key code to a macOS virtual key code.
    Returns -1 if no mapping exists."""
    return LINUX_TO_MACOS.get(keycode, -1)


def macos_keycode_to_linux(keycode: int) -> int:
    """Convert a macOS virtual key code to a Linux evdev key code.
    Returns -1 if no mapping exists."""
    return MACOS_TO_LINUX.get(keycode, -1)


def linux_button_to_macos(button: int) -> int:
    """Convert a Linux evdev button code to a macOS button number.
    Returns -1 if no mapping exists."""
    return LINUX_BTN_TO_MACOS.get(button, -1)


def macos_button_to_linux(button: int) -> int:
    """Convert a macOS button number to a Linux evdev button code.
    Returns -1 if no mapping exists."""
    return MACOS_BTN_TO_LINUX.get(button, -1)
