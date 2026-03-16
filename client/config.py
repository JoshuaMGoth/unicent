"""
Client configuration management.

Stores and retrieves the host's IP address for auto-connection.
"""

import os
import json
import logging
from typing import Optional

log = logging.getLogger(__name__)

CONFIG_DIR = os.path.expanduser('~/.config/unicent')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'client.json')


def ensure_config_dir():
    """Ensure the config directory exists."""
    try:
        os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
    except OSError as e:
        log.warning(f"Could not create config directory: {e}")


def get_host_ip() -> Optional[str]:
    """Get the stored host IP address (e.g., Tailscale IP)."""
    try:
        if not os.path.exists(CONFIG_FILE):
            return None
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
            return config.get('host_ip')
    except Exception as e:
        log.debug(f"Could not read config: {e}")
        return None


def set_host_ip(ip: str) -> bool:
    """Store the host IP address."""
    try:
        ensure_config_dir()
        config = {}
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
        config['host_ip'] = ip
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        log.info(f"Stored host IP: {ip}")
        return True
    except Exception as e:
        log.error(f"Could not write config: {e}")
        return False


def get_config() -> dict:
    """Get all configuration."""
    try:
        if not os.path.exists(CONFIG_FILE):
            return {}
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        log.debug(f"Could not read config: {e}")
        return {}
