"""
Client network connection.

Manages the TLS-encrypted TCP connection to the host server.
Handles auto-discovery, handshake, and message processing
with minimal latency.
"""

import asyncio
import ssl
import os
import socket
import logging
import time
import threading
from typing import Optional, Callable

from shared.protocol import (
    MsgType, MessageReader, HEADER_SIZE,
    encode_handshake, encode_heartbeat, encode_clipboard,
    encode_screen_info, encode_edge_hit, encode_pong,
    decode_header, decode_payload,
)

log = logging.getLogger(__name__)

DEFAULT_PORT = 27183
RECONNECT_DELAY = 3.0
HEARTBEAT_INTERVAL = 5.0


class HostConnection:
    """Manages connection to the host server.

    Features:
    - Auto-discovery via UDP broadcast
    - Direct connection by IP/hostname
    - TLS encryption
    - Automatic reconnection
    - Message callback dispatching
    """

    def __init__(self, host_addr: Optional[str] = None,
                 host_port: int = DEFAULT_PORT,
                 cert_file: Optional[str] = None,
                 ca_file: Optional[str] = None,
                 hostname: str = ''):
        self.host_addr = host_addr
        self.host_port = host_port
        self.cert_file = cert_file
        self.ca_file = ca_file
        self.hostname = hostname or socket.gethostname()

        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._msg_reader = MessageReader()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._connected = False
        self._write_lock: Optional[asyncio.Lock] = None

        # Client state
        self._screens: list = []
        self._clipboard: str = ''

        # Callbacks
        self.on_connected: Optional[Callable] = None
        self.on_disconnected: Optional[Callable] = None
        self.on_mouse_move: Optional[Callable] = None      # (dx, dy)
        self.on_mouse_move_abs: Optional[Callable] = None   # (x, y)
        self.on_mouse_button: Optional[Callable] = None     # (button, state)
        self.on_mouse_scroll: Optional[Callable] = None     # (dx, dy)
        self.on_key_event: Optional[Callable] = None        # (keycode, state)
        self.on_switch_active: Optional[Callable] = None    # (target, x, y)
        self.on_cursor_warp: Optional[Callable] = None      # (x, y)
        self.on_clipboard: Optional[Callable] = None        # (content)
        self.on_wake_screen: Optional[Callable] = None      # ()

    def set_screens(self, screens: list):
        """Set screen info to send during handshake."""
        self._screens = screens

    def set_clipboard(self, content: str):
        """Set initial clipboard content."""
        self._clipboard = content

    @property
    def connected(self) -> bool:
        return self._connected

    def _create_ssl_context(self) -> Optional[ssl.SSLContext]:
        """Create SSL context for TLS."""
        if not self.ca_file or not os.path.exists(self.ca_file):
            return None

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.load_verify_locations(self.ca_file)
        if self.cert_file and os.path.exists(self.cert_file):
            key_file = self.cert_file.replace('.crt', '.key')
            ctx.load_cert_chain(self.cert_file, key_file)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        return ctx

    def start(self):
        """Start the connection manager in a background thread."""
        self._running = True
        self._thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self._thread.start()

    def _run_event_loop(self):
        """Run asyncio event loop in the background."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._write_lock = asyncio.Lock()
        try:
            self._loop.run_until_complete(self._connection_loop())
        except Exception as e:
            log.error(f"Connection loop error: {e}")
        finally:
            self._loop.close()

    async def _connection_loop(self):
        """Main connection loop with auto-reconnect."""
        while self._running:
            try:
                await self._connect_and_run()
            except (ConnectionError, OSError, asyncio.TimeoutError) as e:
                log.info(f"Connection lost: {e}")
            except Exception as e:
                log.error(f"Connection error: {e}", exc_info=True)
            finally:
                self._connected = False
                self._msg_reader.reset()
                if self._writer:
                    try:
                        self._writer.close()
                    except Exception:
                        pass
                    self._writer = None
                self._reader = None

                if self.on_disconnected:
                    try:
                        self.on_disconnected()
                    except Exception:
                        pass

            if self._running:
                log.info(f"Reconnecting in {RECONNECT_DELAY}s...")
                await asyncio.sleep(RECONNECT_DELAY)

    async def _connect_and_run(self):
        """Establish connection and run message loop."""
        if not self.host_addr:
            log.error("No host address configured")
            await asyncio.sleep(RECONNECT_DELAY)
            return

        log.info(f"Connecting to {self.host_addr}:{self.host_port}...")

        ssl_ctx = self._create_ssl_context()

        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(
                self.host_addr,
                self.host_port,
                ssl=ssl_ctx,
            ),
            timeout=10.0,
        )

        # Set TCP_NODELAY
        sock = self._writer.get_extra_info('socket')
        if sock:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
            except OSError:
                pass

        log.info(f"Connected to {self.host_addr}:{self.host_port}")

        # Send handshake
        handshake = encode_handshake(
            hostname=self.hostname,
            screens=self._screens,
            clipboard=self._clipboard,
        )
        self._writer.write(handshake)
        await self._writer.drain()

        # Wait for handshake ACK
        ack_data = await asyncio.wait_for(
            self._reader.read(4096),
            timeout=10.0,
        )
        if not ack_data:
            raise ConnectionError("No handshake ACK received")

        self._msg_reader.feed(ack_data)
        messages = self._msg_reader.read_messages()

        ack_received = False
        for msg_type, data in messages:
            if msg_type == MsgType.HANDSHAKE_ACK:
                log.info(f"Handshake completed with host: {data.get('hostname', 'unknown')}")
                ack_received = True
                break

        if not ack_received:
            raise ConnectionError("Invalid handshake ACK")

        self._connected = True
        if self.on_connected:
            try:
                self.on_connected()
            except Exception:
                pass

        # Start heartbeat task
        heartbeat_task = asyncio.ensure_future(self._heartbeat_loop())

        # Main read loop
        try:
            await self._read_loop()
        finally:
            heartbeat_task.cancel()

    async def _read_loop(self):
        """Read and process messages from the host."""
        while self._running and self._reader:
            data = await self._reader.read(65536)
            if not data:
                raise ConnectionError("Connection closed by host")

            self._msg_reader.feed(data)
            for msg_type, msg_data in self._msg_reader.read_messages():
                self._dispatch_message(msg_type, msg_data)

    def _dispatch_message(self, msg_type: int, data: dict):
        """Dispatch a received message to the appropriate callback."""
        try:
            if msg_type == MsgType.MOUSE_MOVE:
                if self.on_mouse_move:
                    self.on_mouse_move(data['dx'], data['dy'])

            elif msg_type == MsgType.MOUSE_MOVE_ABS:
                if self.on_mouse_move_abs:
                    self.on_mouse_move_abs(data['x'], data['y'])

            elif msg_type == MsgType.MOUSE_BUTTON:
                if self.on_mouse_button:
                    self.on_mouse_button(data['button'], data['state'])

            elif msg_type == MsgType.MOUSE_SCROLL:
                if self.on_mouse_scroll:
                    self.on_mouse_scroll(data['dx'], data['dy'])

            elif msg_type == MsgType.KEY_EVENT:
                if self.on_key_event:
                    self.on_key_event(data['keycode'], data['state'])

            elif msg_type == MsgType.SWITCH_ACTIVE:
                if self.on_switch_active:
                    self.on_switch_active(
                        data.get('target', ''),
                        data.get('cursor_x', 0),
                        data.get('cursor_y', 0),
                    )

            elif msg_type == MsgType.CURSOR_WARP:
                if self.on_cursor_warp:
                    self.on_cursor_warp(data.get('x', 0), data.get('y', 0))

            elif msg_type == MsgType.CLIPBOARD_DATA:
                if self.on_clipboard:
                    self.on_clipboard(data.get('content', ''))

            elif msg_type == MsgType.HEARTBEAT:
                pass  # Heartbeat received, connection is alive

            elif msg_type == MsgType.WAKE_SCREEN:
                if self.on_wake_screen:
                    self.on_wake_screen()

            elif msg_type == MsgType.PING:
                # Respond with pong
                self._send_nowait(encode_pong(data.get('t', 0)))

        except Exception as e:
            log.error(f"Message dispatch error ({msg_type}): {e}")

    async def _heartbeat_loop(self):
        """Send periodic heartbeats."""
        while self._running and self._connected:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            try:
                if self._writer:
                    self._writer.write(encode_heartbeat())
                    await self._writer.drain()
            except Exception:
                break

    def send_clipboard(self, content: str):
        """Send clipboard data to the host."""
        self._schedule_send(encode_clipboard(content))

    def send_screen_info(self, screens: list):
        """Send updated screen info to the host."""
        self._screens = screens
        self._schedule_send(encode_screen_info(screens))

    def send_edge_hit(self, edge: str, position: int):
        """Notify the host that cursor hit screen edge."""
        self._schedule_send(encode_edge_hit(edge, position))

    def _schedule_send(self, data: bytes):
        """Schedule sending data on the event loop."""
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(
                self._loop.create_task,
                self._async_send(data),
            )

    def _send_nowait(self, data: bytes):
        """Send data without scheduling (must be called from event loop)."""
        if self._writer:
            try:
                self._writer.write(data)
            except Exception:
                pass

    async def _async_send(self, data: bytes):
        """Async send helper."""
        if self._writer and self._write_lock:
            try:
                async with self._write_lock:
                    self._writer.write(data)
                    await self._writer.drain()
            except Exception as e:
                log.debug(f"Send error: {e}")

    def stop(self):
        """Stop the connection."""
        self._running = False
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5)
        if self._writer:
            try:
                self._writer.close()
            except Exception:
                pass
        log.info("Connection stopped")
