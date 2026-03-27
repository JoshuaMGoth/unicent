"""
Host network server.

TLS-encrypted TCP server that manages client connections and forwards
input events to the active client. Uses asyncio for non-blocking I/O
with TCP_NODELAY for minimal latency.
"""

import asyncio
import ssl
import os
import socket
import logging
import time
import threading
from typing import Dict, Optional, Callable, List

from shared.protocol import (
    MsgType, MessageReader, HEADER_SIZE,
    encode_mouse_move, encode_mouse_button, encode_mouse_scroll,
    encode_key_event, encode_handshake_ack, encode_heartbeat,
    encode_switch_active, encode_clipboard, encode_cursor_warp,
    encode_json_message, encode_wake_screen, encode_disconnect,
    decode_header, decode_payload,
)

log = logging.getLogger(__name__)

DEFAULT_PORT = 27183
HEARTBEAT_INTERVAL = 5.0
CLIENT_TIMEOUT = 15.0


class ClientConnection:
    """Represents a connected client."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                 client_id: str):
        self.reader = reader
        self.writer = writer
        self.client_id = client_id
        self.hostname: str = ''
        self.screens: list = []
        self.connected_at: float = time.time()
        self.last_heartbeat: float = time.time()
        self.clipboard: str = ''
        self.msg_reader = MessageReader()
        self._write_lock = asyncio.Lock()

    async def send(self, data: bytes):
        """Send data to the client."""
        try:
            async with self._write_lock:
                self.writer.write(data)
                await self.writer.drain()
        except (ConnectionError, OSError) as e:
            log.error(f"Send error to {self.client_id}: {e}")
            raise

    async def send_nowait(self, data: bytes):
        """Send data without waiting for drain (for high-frequency events)."""
        try:
            self.writer.write(data)
        except (ConnectionError, OSError):
            pass

    @property
    def address(self) -> str:
        try:
            peername = self.writer.get_extra_info('peername')
            return f"{peername[0]}:{peername[1]}" if peername else 'unknown'
        except Exception:
            return 'unknown'

    def close(self):
        try:
            self.writer.close()
        except Exception:
            pass


class HostServer:
    """TLS server that manages client connections and input forwarding.

    The server:
    1. Accepts TLS client connections
    2. Performs handshake (exchange screen info)
    3. Forwards input events to the active client
    4. Handles clipboard synchronization
    5. Manages heartbeats and timeouts
    """

    def __init__(self, port: int = DEFAULT_PORT,
                 cert_file: Optional[str] = None,
                 key_file: Optional[str] = None,
                 ca_file: Optional[str] = None):
        self.port = port
        self.cert_file = cert_file
        self.key_file = key_file
        self.ca_file = ca_file
        self.clients: Dict[str, ClientConnection] = {}
        self._server: Optional[asyncio.AbstractServer] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

        # Callbacks
        self.on_client_connected: Optional[Callable] = None
        self.on_client_disconnected: Optional[Callable] = None
        self.on_client_screens: Optional[Callable] = None
        self.on_clipboard_received: Optional[Callable] = None

        # Local state
        self._host_hostname: str = socket.gethostname()
        self._host_screens: list = []
        self._layout_info: list = []
        self._clipboard: str = ''
        self._active_client: Optional[str] = None

        # Track which hostnames are currently connected to prevent duplicates
        self._connected_hostnames: Dict[str, str] = {}  # hostname -> client_id

        # Buffered writes for high-frequency events
        self._write_buffer: Dict[str, list] = {}
        self._flush_task: Optional[asyncio.Task] = None
        self._move_forward_count: int = 0

    def set_host_info(self, hostname: str, screens: list, layout: list):
        """Set host information for handshake."""
        self._host_hostname = hostname
        self._host_screens = screens
        self._layout_info = layout

    def set_active_client(self, client_id: Optional[str]):
        """Set which client should receive input events."""
        self._active_client = client_id

    def _create_ssl_context(self) -> Optional[ssl.SSLContext]:
        """Create SSL context for TLS encryption."""
        if not self.cert_file or not os.path.exists(self.cert_file):
            log.warning("No TLS certificate configured, running without encryption")
            return None

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(self.cert_file, self.key_file)
        if self.ca_file and os.path.exists(self.ca_file):
            ctx.load_verify_locations(self.ca_file)
            ctx.verify_mode = ssl.CERT_OPTIONAL
        else:
            ctx.verify_mode = ssl.CERT_NONE
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        return ctx

    def start(self):
        """Start the server in a background thread."""
        self._running = True
        self._thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self._thread.start()
        log.info(f"Host server starting on port {self.port}")

    def _run_event_loop(self):
        """Run the asyncio event loop in the background thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._start_server())
            self._loop.run_forever()
        except Exception as e:
            log.error(f"Server event loop error: {e}")
        finally:
            self._loop.close()

    async def _start_server(self):
        """Start the async TCP server."""
        ssl_ctx = self._create_ssl_context()
        self._server = await asyncio.start_server(
            self._handle_client,
            '0.0.0.0',
            self.port,
            ssl=ssl_ctx,
        )

        # Set TCP_NODELAY on the server socket
        for sock in self._server.sockets:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        # Start heartbeat task
        asyncio.ensure_future(self._heartbeat_loop())

        # Start buffer flush task
        self._flush_task = asyncio.ensure_future(self._flush_loop())

        addrs = ', '.join(str(s.getsockname()) for s in self._server.sockets)
        log.info(f"Host server listening on {addrs}")

    async def _handle_client(self, reader: asyncio.StreamReader,
                             writer: asyncio.StreamWriter):
        """Handle a new client connection."""
        peername = writer.get_extra_info('peername')
        client_addr = f"{peername[0]}:{peername[1]}" if peername else 'unknown'
        log.info(f"New connection from {client_addr}")

        # Set TCP_NODELAY on the client socket
        sock = writer.get_extra_info('socket')
        if sock:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            # Reduce socket buffer for lower latency
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
            except OSError:
                pass

        # Wait for client handshake
        msg_reader = MessageReader()
        client: Optional[ClientConnection] = None

        try:
            # Read handshake with timeout — loop until we get a complete
            # message, because large clipboards can exceed a single read.
            handshake_msg = None
            deadline = asyncio.get_event_loop().time() + 10.0
            while True:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    break
                handshake_data = await asyncio.wait_for(
                    reader.read(65536), timeout=remaining
                )
                if not handshake_data:
                    writer.close()
                    return
                msg_reader.feed(handshake_data)
                messages = msg_reader.read_messages()
                for msg_type, data in messages:
                    if msg_type == MsgType.HANDSHAKE:
                        handshake_msg = data
                        break
                if handshake_msg:
                    break

            if not handshake_msg:
                log.warning(f"No handshake from {client_addr}")
                writer.close()
                return

            # Create client connection
            hostname = handshake_msg.get('hostname', client_addr)
            client_id = hostname

            # Evict stale duplicate connection from same hostname
            if hostname in self._connected_hostnames:
                existing_client_id = self._connected_hostnames[hostname]
                log.info(f"Evicting stale connection from {hostname} ({existing_client_id}), accepting new one")
                old_client = self.clients.pop(existing_client_id, None)
                self._write_buffer.pop(existing_client_id, None)
                del self._connected_hostnames[hostname]
                if old_client:
                    old_client.close()
                    if self.on_client_disconnected:
                        self.on_client_disconnected(existing_client_id)

            client = ClientConnection(reader, writer, client_id)
            client.hostname = handshake_msg.get('hostname', '')
            client.screens = handshake_msg.get('screens', [])
            client.clipboard = handshake_msg.get('clipboard', '')
            client.msg_reader = msg_reader

            # Send handshake ACK
            ack = encode_handshake_ack(
                self._host_hostname,
                self._host_screens,
                self._layout_info,
            )
            await client.send(ack)

            # Register client
            self.clients[client_id] = client
            self._write_buffer[client_id] = []
            self._connected_hostnames[hostname] = client_id
            log.info(f"Client registered: {client_id} ({client.address})")

            # Notify callback
            if self.on_client_connected:
                self.on_client_connected(client_id, client.screens)

            if client.clipboard and self.on_clipboard_received:
                self.on_clipboard_received(client_id, client.clipboard)

            # Main read loop
            await self._client_read_loop(client)

        except asyncio.TimeoutError:
            log.warning(f"Handshake timeout from {client_addr}")
        except (ConnectionError, OSError) as e:
            log.info(f"Client disconnected: {client_addr}: {e}")
        except Exception as e:
            log.error(f"Client handler error: {e}", exc_info=True)
        finally:
            if client and client.client_id in self.clients:
                del self.clients[client.client_id]
                self._write_buffer.pop(client.client_id, None)
                # Remove from connected hostnames
                if client.hostname in self._connected_hostnames:
                    del self._connected_hostnames[client.hostname]
                client.close()
                log.info(f"Client removed: {client.client_id}")
                if self.on_client_disconnected:
                    self.on_client_disconnected(client.client_id)

    async def _client_read_loop(self, client: ClientConnection):
        """Read messages from a connected client."""
        while self._running:
            data = await client.reader.read(65536)
            if not data:
                break

            client.msg_reader.feed(data)
            for msg_type, msg_data in client.msg_reader.read_messages():
                await self._handle_client_message(client, msg_type, msg_data)

    async def _handle_client_message(self, client: ClientConnection,
                                      msg_type: int, data: dict):
        """Process a message from a client."""
        if msg_type == MsgType.HEARTBEAT:
            client.last_heartbeat = time.time()

        elif msg_type == MsgType.SCREEN_INFO:
            client.screens = data.get('screens', [])
            if self.on_client_screens:
                self.on_client_screens(client.client_id, client.screens)

        elif msg_type == MsgType.CLIPBOARD_DATA:
            client.clipboard = data.get('content', '')
            if self.on_clipboard_received:
                self.on_clipboard_received(client.client_id, client.clipboard)

        elif msg_type == MsgType.EDGE_HIT:
            # Client reports cursor hit screen edge
            log.debug(f"Edge hit from {client.client_id}: {data}")

        elif msg_type == MsgType.PONG:
            rtt = (time.time() - data.get('t', time.time())) * 1000
            log.debug(f"RTT to {client.client_id}: {rtt:.1f}ms")

    # --- Input forwarding methods (called from the input capture thread) ---

    def forward_mouse_move(self, dx: int, dy: int):
        """Forward a relative mouse move to the active client."""
        if not self._active_client:
            return
        self._move_forward_count += 1
        if self._move_forward_count % 200 == 0:
            log.debug(
                f"Forwarded mouse moves: {self._move_forward_count} "
                f"(latest dx={dx}, dy={dy}, active={self._active_client})"
            )
        data = encode_mouse_move(dx, dy)
        self._buffer_write(self._active_client, data)

    def forward_mouse_button(self, button: int, state: int):
        """Forward a mouse button event to the active client immediately."""
        if not self._active_client:
            return
        data = encode_mouse_button(button, state)
        self._schedule_send(self._active_client, data)

    def forward_mouse_scroll(self, dx: int, dy: int):
        """Forward a scroll event to the active client immediately."""
        if not self._active_client:
            return
        data = encode_mouse_scroll(dx, dy)
        self._schedule_send(self._active_client, data)

    def forward_key_event(self, keycode: int, state: int):
        """Forward a key event to the active client immediately."""
        if not self._active_client:
            return
        data = encode_key_event(keycode, state)
        self._schedule_send(self._active_client, data)

    def send_cursor_warp(self, client_id: str, x: int, y: int):
        """Tell a client to warp its cursor to a position."""
        if client_id not in self.clients:
            return
        data = encode_cursor_warp(x, y)
        self._schedule_send(client_id, data)

    def send_switch_active(self, client_id: str, cursor_x: int, cursor_y: int):
        """Notify a client that it is now the active target."""
        if client_id not in self.clients:
            return
        data = encode_switch_active(client_id, cursor_x, cursor_y)
        self._schedule_send(client_id, data)
        self._active_client = client_id

    def send_switch_inactive(self, client_id: str):
        """Notify a client that it is no longer the active target."""
        if client_id not in self.clients:
            return
        data = encode_switch_active('', 0, 0)
        self._schedule_send(client_id, data)

    def send_clipboard(self, content: str):
        """Send clipboard content to all connected clients."""
        data = encode_clipboard(content)
        for client_id in list(self.clients.keys()):
            self._schedule_send(client_id, data)

    def send_wake_screen(self, client_id: str):
        """Send a wake-screen signal to a specific client."""
        if client_id not in self.clients:
            return
        data = encode_wake_screen()
        self._schedule_send(client_id, data)
        log.info(f"Sent wake-screen to {client_id}")

    def _buffer_write(self, client_id: str, data: bytes):
        """Buffer a write for batch sending (reduces syscalls)."""
        if client_id in self._write_buffer:
            self._write_buffer[client_id].append(data)

    def _schedule_send(self, client_id: str, data: bytes):
        """Schedule a send on the event loop."""
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(
                self._loop.create_task,
                self._do_send(client_id, data)
            )

    async def _do_send(self, client_id: str, data: bytes):
        """Actually send data to a client."""
        client = self.clients.get(client_id)
        if client:
            try:
                await client.send(data)
            except Exception:
                pass

    async def _flush_loop(self):
        """Periodically flush buffered writes for minimal latency."""
        while self._running:
            await asyncio.sleep(0.001)  # 1ms flush interval
            for client_id, buffer in list(self._write_buffer.items()):
                if not buffer:
                    continue
                client = self.clients.get(client_id)
                if not client:
                    buffer.clear()
                    continue
                # Concatenate all buffered data and send at once
                data = b''.join(buffer)
                buffer.clear()
                try:
                    client.writer.write(data)
                    await client.writer.drain()
                except (ConnectionError, OSError):
                    pass

    async def _heartbeat_loop(self):
        """Send heartbeats and check for timed-out clients."""
        while self._running:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            hb = encode_heartbeat()
            now = time.time()

            for client_id, client in list(self.clients.items()):
                # Check timeout
                if now - client.last_heartbeat > CLIENT_TIMEOUT:
                    log.warning(f"Client timed out: {client_id}")
                    client.close()
                    continue

                # Send heartbeat
                try:
                    await client.send(hb)
                except Exception:
                    pass

    def stop(self):
        """Stop the server."""
        self._running = False
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5)
        for client in self.clients.values():
            client.close()
        self.clients.clear()
        log.info("Host server stopped")

    def disconnect_client(self, client_id: str):
        """Disconnect a specific client by ID."""
        client = self.clients.get(client_id)
        if not client:
            log.warning(f"Cannot disconnect unknown client: {client_id}")
            return
        log.info(f"Disconnecting client: {client_id}")
        # Schedule the async disconnect on the event loop thread
        # (writer.close is not thread-safe from the tray thread)
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(
                self._loop.create_task,
                self._async_disconnect_client(client_id)
            )
        else:
            client.close()

    async def _async_disconnect_client(self, client_id: str):
        """Disconnect a client by closing the socket (runs on event loop)."""
        client = self.clients.get(client_id)
        if not client:
            return
        # Close the connection
        try:
            client.writer.write(encode_disconnect('disconnected_by_user'))
            await client.writer.drain()
        except Exception:
            pass
        try:
            client.writer.close()
            await client.writer.wait_closed()
        except Exception:
            pass
        log.info(f"Client disconnected by user: {client_id}")

    def allow_client(self, hostname: str):
        """No longer needed - clients can always reconnect after normal disconnect."""
        log.info(f"Client reconnection allowed (was always permitted): {hostname}")

    def get_client_list(self) -> List[dict]:
        """Get list of connected clients."""
        return [
            {
                'client_id': c.client_id,
                'hostname': c.hostname,
                'address': c.address,
                'screens': c.screens,
                'connected_at': c.connected_at,
            }
            for c in self.clients.values()
        ]
