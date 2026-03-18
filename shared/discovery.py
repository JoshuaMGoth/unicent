"""
Network auto-discovery using UDP broadcast.

The host broadcasts its presence; clients listen and auto-connect.
Clients also broadcast so the host can discover them for the toggle menu.
"""

import socket
import json
import threading
import time
import logging
from typing import Callable, Dict, Optional

log = logging.getLogger(__name__)

DISCOVERY_PORT = 27182
DISCOVERY_MAGIC = 'UNICENT_DISC'
BROADCAST_INTERVAL = 2.0
STALE_TIMEOUT = 10.0


class DiscoveryBeacon:
    """Broadcasts presence on the local network via UDP."""

    def __init__(self, service_port: int, hostname: str, role: str,
                 extra: Optional[dict] = None):
        """
        Args:
            service_port: The TCP port the service is listening on.
            hostname: Human-readable name for this machine.
            role: 'host' or 'client'.
            extra: Additional info to include in broadcast.
        """
        self.service_port = service_port
        self.hostname = hostname
        self.role = role
        self.extra = extra or {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._sock: Optional[socket.socket] = None

    def start(self):
        """Start broadcasting."""
        self._running = True
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._sock.settimeout(1.0)
        self._thread = threading.Thread(target=self._broadcast_loop, daemon=True)
        self._thread.start()
        log.info(f"Discovery beacon started ({self.role}: {self.hostname})")

    def stop(self):
        """Stop broadcasting."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
        log.info("Discovery beacon stopped")

    def _broadcast_loop(self):
        message = {
            'magic': DISCOVERY_MAGIC,
            'port': self.service_port,
            'hostname': self.hostname,
            'role': self.role,
            **self.extra,
        }
        while self._running:
            try:
                message['timestamp'] = time.time()
                data = json.dumps(message).encode('utf-8')
                self._sock.sendto(data, ('<broadcast>', DISCOVERY_PORT))
            except Exception as e:
                log.debug(f"Broadcast send error: {e}")
            time.sleep(BROADCAST_INTERVAL)


class DiscoveryListener:
    """Listens for discovery broadcasts on the local network."""

    def __init__(self, on_discovered: Optional[Callable] = None,
                 filter_role: Optional[str] = None):
        """
        Args:
            on_discovered: Callback(info_dict) when a new peer is found.
            filter_role: Only report peers with this role (e.g. 'host').
        """
        self.on_discovered = on_discovered
        self.filter_role = filter_role
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._sock: Optional[socket.socket] = None
        self._peers: Dict[str, dict] = {}
        self._lock = threading.Lock()

    def start(self):
        """Start listening for broadcasts."""
        self._running = True
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except (AttributeError, OSError):
            pass
        self._sock.bind(('', DISCOVERY_PORT))
        self._sock.settimeout(1.0)
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        log.info("Discovery listener started")

    def stop(self):
        """Stop listening."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
        log.info("Discovery listener stopped")

    def _listen_loop(self):
        while self._running:
            try:
                data, addr = self._sock.recvfrom(4096)
                info = json.loads(data.decode('utf-8'))
                if info.get('magic') != DISCOVERY_MAGIC:
                    continue
                info['ip'] = addr[0]
                role = info.get('role', '')
                if self.filter_role and role != self.filter_role:
                    continue

                key = f"{info.get('hostname', addr[0])}_{addr[0]}"
                with self._lock:
                    is_new = key not in self._peers
                    self._peers[key] = info

                if is_new and self.on_discovered:
                    try:
                        self.on_discovered(info)
                    except Exception as e:
                        log.error(f"Discovery callback error: {e}")

            except socket.timeout:
                continue
            except json.JSONDecodeError:
                continue
            except Exception as e:
                if self._running:
                    log.debug(f"Discovery listen error: {e}")
                continue

    def get_peers(self) -> Dict[str, dict]:
        """Get all discovered peers (pruning stale entries)."""
        now = time.time()
        with self._lock:
            # Prune stale entries
            stale_keys = [
                k for k, v in self._peers.items()
                if now - v.get('timestamp', 0) > STALE_TIMEOUT
            ]
            for k in stale_keys:
                del self._peers[k]
            return dict(self._peers)

    def get_hosts(self) -> list:
        """Get list of discovered hosts."""
        return [
            v for v in self.get_peers().values()
            if v.get('role') == 'host'
        ]

    def get_clients(self) -> list:
        """Get list of discovered clients."""
        return [
            v for v in self.get_peers().values()
            if v.get('role') == 'client'
        ]


# ────────────────────────────────────────────────────────────
# Active host scanning (TCP probe on Tailscale + LAN peers)
# ────────────────────────────────────────────────────────────

DEFAULT_PORT = 27183


def _get_tailscale_peers() -> list:
    """Get IP addresses of online Tailscale peers."""
    import subprocess
    try:
        result = subprocess.run(
            ['tailscale', 'status', '--json'],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return []
        import json as _json
        status = _json.loads(result.stdout)
        peers = []
        for peer in (status.get('Peer') or {}).values():
            if not peer.get('Online', False):
                continue
            addrs = peer.get('TailscaleIPs', [])
            for addr in addrs:
                if ':' not in addr:  # IPv4 only
                    peers.append(addr)
        return peers
    except Exception as e:
        log.debug(f"Tailscale peer scan unavailable: {e}")
        return []


def _probe_port(ip: str, port: int, timeout: float = 1.0) -> bool:
    """Check if a TCP port is open on the given IP."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((ip, port))
            return True
    except (OSError, socket.timeout):
        return False


def scan_for_host(port: int = DEFAULT_PORT, timeout: float = 1.5) -> Optional[str]:
    """Scan Tailscale peers and return the first IP with UniCent port open.

    Returns the host IP address, or None if not found.
    """
    peers = _get_tailscale_peers()
    if not peers:
        log.debug("No Tailscale peers found, skipping scan")
        return None

    log.info(f"Scanning {len(peers)} Tailscale peer(s) for UniCent host on port {port}...")

    # Scan in parallel for speed
    import concurrent.futures
    found_ip = None
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(peers), 10)) as pool:
        future_to_ip = {pool.submit(_probe_port, ip, port, timeout): ip for ip in peers}
        for future in concurrent.futures.as_completed(future_to_ip):
            ip = future_to_ip[future]
            try:
                if future.result():
                    log.info(f"Found UniCent host at {ip}:{port}")
                    found_ip = ip
                    break
            except Exception:
                pass

    return found_ip
