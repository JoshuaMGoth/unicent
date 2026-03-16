"""
Binary protocol for UniCent communication.

Designed for minimal latency with compact binary encoding for input events
and JSON encoding for control messages.

Wire format:
    Header: [type: 1 byte][payload_length: 4 bytes BE] = 5 bytes
    Payload: variable length

Input events use fixed-size binary payloads for speed.
Control messages use JSON payloads for flexibility.
"""

import struct
import json
import time
from enum import IntEnum
from typing import Tuple, Any, List, Optional


class MsgType(IntEnum):
    """Message type identifiers."""
    # Input events (high frequency, binary encoded) - 0x01-0x0F
    MOUSE_MOVE = 0x01
    MOUSE_BUTTON = 0x02
    MOUSE_SCROLL = 0x03
    KEY_EVENT = 0x04
    MOUSE_MOVE_ABS = 0x05

    # Control messages (low frequency, JSON encoded) - 0x10+
    CLIPBOARD_DATA = 0x10
    SCREEN_INFO = 0x11
    SWITCH_ACTIVE = 0x12
    HEARTBEAT = 0x13
    HANDSHAKE = 0x14
    HANDSHAKE_ACK = 0x15
    EDGE_HIT = 0x16
    CURSOR_WARP = 0x17
    DISCONNECT = 0x18
    PING = 0x19
    PONG = 0x1A
    WAKE_SCREEN = 0x1B


# Header format: type(uint8) + payload_length(uint32 BE)
HEADER_FORMAT = '!BI'
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)  # 5 bytes

# Binary payload formats for input events
MOUSE_MOVE_FORMAT = '!hh'          # dx(int16), dy(int16) = 4 bytes
MOUSE_MOVE_ABS_FORMAT = '!HH'     # x(uint16), y(uint16) = 4 bytes
MOUSE_BUTTON_FORMAT = '!HB'       # button(uint16), state(uint8) = 3 bytes
MOUSE_SCROLL_FORMAT = '!hh'       # dx(int16), dy(int16) = 4 bytes
KEY_EVENT_FORMAT = '!HB'          # keycode(uint16), state(uint8) = 3 bytes

# Protocol version
PROTOCOL_VERSION = 1
MAGIC = 'UNICENT'


def encode_header(msg_type: int, payload_length: int) -> bytes:
    """Encode a message header."""
    return struct.pack(HEADER_FORMAT, msg_type, payload_length)


def decode_header(data: bytes) -> Tuple[int, int]:
    """Decode a message header. Returns (msg_type, payload_length)."""
    return struct.unpack(HEADER_FORMAT, data)


# --- Encoder functions ---

def encode_mouse_move(dx: int, dy: int) -> bytes:
    """Encode a relative mouse move event. Total: 9 bytes."""
    payload = struct.pack(MOUSE_MOVE_FORMAT, dx, dy)
    return encode_header(MsgType.MOUSE_MOVE, len(payload)) + payload


def encode_mouse_move_abs(x: int, y: int) -> bytes:
    """Encode an absolute mouse position. Total: 9 bytes."""
    payload = struct.pack(MOUSE_MOVE_ABS_FORMAT, x, y)
    return encode_header(MsgType.MOUSE_MOVE_ABS, len(payload)) + payload


def encode_mouse_button(button: int, state: int) -> bytes:
    """Encode a mouse button event. Total: 7 bytes."""
    payload = struct.pack(MOUSE_BUTTON_FORMAT, button, state)
    return encode_header(MsgType.MOUSE_BUTTON, len(payload)) + payload


def encode_mouse_scroll(dx: int, dy: int) -> bytes:
    """Encode a mouse scroll event. Total: 9 bytes."""
    payload = struct.pack(MOUSE_SCROLL_FORMAT, dx, dy)
    return encode_header(MsgType.MOUSE_SCROLL, len(payload)) + payload


def encode_key_event(keycode: int, state: int) -> bytes:
    """Encode a keyboard event. Total: 8 bytes."""
    payload = struct.pack(KEY_EVENT_FORMAT, keycode, state)
    return encode_header(MsgType.KEY_EVENT, len(payload)) + payload


def encode_json_message(msg_type: int, data: dict) -> bytes:
    """Encode a JSON control message."""
    payload = json.dumps(data, separators=(',', ':')).encode('utf-8')
    return encode_header(msg_type, len(payload)) + payload


def encode_handshake(hostname: str, screens: list, clipboard: str = '') -> bytes:
    """Encode a handshake message."""
    return encode_json_message(MsgType.HANDSHAKE, {
        'version': PROTOCOL_VERSION,
        'magic': MAGIC,
        'hostname': hostname,
        'screens': screens,
        'clipboard': clipboard,
        'timestamp': time.time(),
    })


def encode_handshake_ack(hostname: str, screens: list, layout: list) -> bytes:
    """Encode a handshake acknowledgment."""
    return encode_json_message(MsgType.HANDSHAKE_ACK, {
        'version': PROTOCOL_VERSION,
        'magic': MAGIC,
        'hostname': hostname,
        'screens': screens,
        'layout': layout,
        'accepted': True,
    })


def encode_screen_info(screens: list) -> bytes:
    """Encode screen information."""
    return encode_json_message(MsgType.SCREEN_INFO, {'screens': screens})


def encode_switch_active(target: str, cursor_x: int = 0, cursor_y: int = 0) -> bytes:
    """Encode a switch-active-target command."""
    return encode_json_message(MsgType.SWITCH_ACTIVE, {
        'target': target,
        'cursor_x': cursor_x,
        'cursor_y': cursor_y,
    })


def encode_clipboard(content: str) -> bytes:
    """Encode clipboard data."""
    return encode_json_message(MsgType.CLIPBOARD_DATA, {
        'content': content,
        'timestamp': time.time(),
    })


def encode_heartbeat() -> bytes:
    """Encode a heartbeat message."""
    return encode_json_message(MsgType.HEARTBEAT, {
        'timestamp': time.time(),
    })


def encode_cursor_warp(x: int, y: int) -> bytes:
    """Encode a cursor warp command."""
    return encode_json_message(MsgType.CURSOR_WARP, {'x': x, 'y': y})


def encode_edge_hit(edge: str, position: int) -> bytes:
    """Encode an edge-hit notification. edge is 'left','right','top','bottom'."""
    return encode_json_message(MsgType.EDGE_HIT, {
        'edge': edge,
        'position': position,
    })


def encode_ping() -> bytes:
    """Encode a ping message."""
    return encode_json_message(MsgType.PING, {'t': time.time()})


def encode_pong(ping_time: float) -> bytes:
    """Encode a pong message."""
    return encode_json_message(MsgType.PONG, {'t': ping_time, 'r': time.time()})


def encode_disconnect(reason: str = 'disconnected') -> bytes:
    """Encode a disconnect command sent by the host to tell a client to stop."""
    return encode_json_message(MsgType.DISCONNECT, {'reason': reason})


def encode_wake_screen() -> bytes:
    """Encode a wake-screen command to wake a sleeping/locked display."""
    return encode_json_message(MsgType.WAKE_SCREEN, {
        'timestamp': time.time(),
    })


# --- Decoder ---

def decode_payload(msg_type: int, payload: bytes) -> Any:
    """Decode a message payload based on its type."""
    if msg_type == MsgType.MOUSE_MOVE:
        dx, dy = struct.unpack(MOUSE_MOVE_FORMAT, payload)
        return {'type': 'mouse_move', 'dx': dx, 'dy': dy}

    elif msg_type == MsgType.MOUSE_MOVE_ABS:
        x, y = struct.unpack(MOUSE_MOVE_ABS_FORMAT, payload)
        return {'type': 'mouse_move_abs', 'x': x, 'y': y}

    elif msg_type == MsgType.MOUSE_BUTTON:
        button, state = struct.unpack(MOUSE_BUTTON_FORMAT, payload)
        return {'type': 'mouse_button', 'button': button, 'state': state}

    elif msg_type == MsgType.MOUSE_SCROLL:
        dx, dy = struct.unpack(MOUSE_SCROLL_FORMAT, payload)
        return {'type': 'mouse_scroll', 'dx': dx, 'dy': dy}

    elif msg_type == MsgType.KEY_EVENT:
        keycode, state = struct.unpack(KEY_EVENT_FORMAT, payload)
        return {'type': 'key_event', 'keycode': keycode, 'state': state}

    else:
        # JSON control message
        data = json.loads(payload.decode('utf-8'))
        data['type'] = MsgType(msg_type).name.lower()
        return data


class MessageReader:
    """Incrementally reads messages from a byte stream.

    Feed data with feed(), then call read_messages() to get
    all complete messages available. Maintains internal buffer
    for partial messages across reads.
    """

    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data: bytes):
        """Add data to the internal buffer."""
        self.buffer.extend(data)

    def read_messages(self) -> List[Tuple[int, Any]]:
        """Yield all complete (msg_type, decoded_payload) pairs from buffer."""
        messages = []
        while len(self.buffer) >= HEADER_SIZE:
            msg_type, payload_length = decode_header(
                bytes(self.buffer[:HEADER_SIZE])
            )
            total_length = HEADER_SIZE + payload_length
            if len(self.buffer) < total_length:
                break
            payload = bytes(self.buffer[HEADER_SIZE:total_length])
            del self.buffer[:total_length]
            try:
                decoded = decode_payload(msg_type, payload)
                messages.append((msg_type, decoded))
            except Exception as e:
                # Skip malformed messages
                print(f"[protocol] Failed to decode message type {msg_type}: {e}")
        return messages

    def reset(self):
        """Clear the internal buffer."""
        self.buffer.clear()
