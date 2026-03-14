"""
UniCent auto-updater — checks GitHub releases for new versions
and performs one-click updates.
"""

import json
import logging
import os
import platform
import subprocess
import sys
import threading
from typing import Optional, Tuple

from shared.version import __version__, __repo_url__

log = logging.getLogger(__name__)

_SYSTEM = platform.system()

# GitHub API endpoint for latest release
_API_URL = "https://api.github.com/repos/JoshuaMGoth/unicent/releases/latest"
_RAW_VERSION_URL = "https://raw.githubusercontent.com/JoshuaMGoth/unicent/main/shared/version.py"


def _parse_version(v: str) -> Tuple[int, ...]:
    """Parse a version string like '1.2.3' into a tuple (1, 2, 3)."""
    try:
        return tuple(int(x) for x in v.strip().lstrip('v').split('.'))
    except (ValueError, AttributeError):
        return (0, 0, 0)


def check_for_update() -> Optional[dict]:
    """Check GitHub for a newer version.

    Returns dict with keys: 'current', 'latest', 'url', 'notes'
    or None if already up to date or check failed.
    """
    try:
        import urllib.request
        req = urllib.request.Request(
            _API_URL,
            headers={'Accept': 'application/vnd.github.v3+json',
                     'User-Agent': 'UniCent-Updater'},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))

        latest_tag = data.get('tag_name', '').lstrip('v')
        if not latest_tag:
            return None

        current = _parse_version(__version__)
        latest = _parse_version(latest_tag)

        if latest > current:
            return {
                'current': __version__,
                'latest': latest_tag,
                'url': data.get('html_url', f'{__repo_url__}/releases'),
                'notes': data.get('body', ''),
            }
        return None  # up to date
    except Exception as e:
        log.debug(f"Update check failed: {e}")
        # Fallback: try fetching version.py directly from main branch
        try:
            return _check_version_from_raw()
        except Exception as e2:
            log.debug(f"Fallback update check also failed: {e2}")
            return None


def _check_version_from_raw() -> Optional[dict]:
    """Fallback: compare version from raw main branch version.py."""
    import urllib.request
    req = urllib.request.Request(
        _RAW_VERSION_URL,
        headers={'User-Agent': 'UniCent-Updater'},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        content = resp.read().decode('utf-8')

    # Parse __version__ from the raw file
    latest_ver = None
    for line in content.splitlines():
        if line.startswith('__version__'):
            latest_ver = line.split('=')[1].strip().strip('"').strip("'")
            break

    if not latest_ver:
        return None

    current = _parse_version(__version__)
    latest = _parse_version(latest_ver)

    if latest > current:
        return {
            'current': __version__,
            'latest': latest_ver,
            'url': f'{__repo_url__}/releases',
            'notes': '',
        }
    return None


def get_install_dir() -> str:
    """Get the installation directory."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def perform_update(callback=None):
    """Perform a one-click update via git pull.

    Args:
        callback: Optional function(success: bool, message: str) called when done.
    """
    def _do_update():
        install_dir = get_install_dir()
        git_dir = os.path.join(install_dir, '.git')

        try:
            if os.path.isdir(git_dir):
                # Git-based install — just pull
                result = subprocess.run(
                    ['git', 'pull', '--ff-only'],
                    cwd=install_dir,
                    capture_output=True, text=True, timeout=60,
                )
                if result.returncode == 0:
                    msg = f"Updated successfully.\n\n{result.stdout.strip()}\n\nPlease restart UniCent."
                    log.info(f"Update successful: {result.stdout.strip()}")
                    if callback:
                        callback(True, msg)
                else:
                    msg = f"Update failed:\n{result.stderr.strip()}"
                    log.error(f"Git pull failed: {result.stderr.strip()}")
                    if callback:
                        callback(False, msg)
            else:
                # Not a git repo — clone fresh into a temp dir and copy
                import shutil
                import tempfile
                tmp = tempfile.mkdtemp(prefix='unicent-update-')
                result = subprocess.run(
                    ['git', 'clone', '--depth', '1', f'{__repo_url__}.git', tmp],
                    capture_output=True, text=True, timeout=120,
                )
                if result.returncode == 0:
                    # Copy files over (skip .git)
                    for item in os.listdir(tmp):
                        if item == '.git':
                            continue
                        src = os.path.join(tmp, item)
                        dst = os.path.join(install_dir, item)
                        if os.path.isdir(src):
                            if os.path.exists(dst):
                                shutil.rmtree(dst)
                            shutil.copytree(src, dst)
                        else:
                            shutil.copy2(src, dst)
                    shutil.rmtree(tmp, ignore_errors=True)
                    msg = "Updated successfully.\n\nPlease restart UniCent."
                    log.info("Update via fresh clone successful")
                    if callback:
                        callback(True, msg)
                else:
                    shutil.rmtree(tmp, ignore_errors=True)
                    msg = f"Update failed:\n{result.stderr.strip()}"
                    log.error(f"Clone failed: {result.stderr.strip()}")
                    if callback:
                        callback(False, msg)
        except Exception as e:
            msg = f"Update error: {e}"
            log.error(msg)
            if callback:
                callback(False, msg)

    thread = threading.Thread(target=_do_update, daemon=True)
    thread.start()
    return thread


def check_for_update_async(callback):
    """Check for updates in background thread.

    Args:
        callback: function(result: dict|None) — called with update info or None.
    """
    def _check():
        result = check_for_update()
        callback(result)

    thread = threading.Thread(target=_check, daemon=True)
    thread.start()
    return thread
