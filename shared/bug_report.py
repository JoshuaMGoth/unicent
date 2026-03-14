"""
UniCent bug report sender — posts reports to the bug report server.

Sends structured JSON reports directly to the Cloudflare Worker endpoint.
No email client required.  System info is collected automatically.

This module is designed to be universal — any JoshuaGoth Software project
can copy it (along with shared/version.py) and call send_bug_report().
"""

import logging
import platform
import os
import sys
import json
from typing import Optional
from urllib import request as urllib_request, error as urllib_error

from shared.version import (
    __version__, __app_name__,
    __report_endpoint__, __report_api_key__,
)

log = logging.getLogger(__name__)

_SYSTEM = platform.system()

# ── Endpoint config ────────────────────────────────────────────
# These come from shared/version.py so they're easy to update
# across releases.  The API key is NOT a secret — it's a
# project-level token that ships with the app.  Abuse is
# prevented by server-side IP rate limiting (10 req/hr/IP).
# ───────────────────────────────────────────────────────────────


def _get_system_info() -> dict:
    """Gather system info for the bug report (as a dict)."""
    info = {
        'os': f"{platform.system()} {platform.release()}",
        'arch': platform.machine(),
        'python': platform.python_version(),
        'hostname': platform.node(),
    }
    if _SYSTEM == 'Linux':
        info['display'] = os.environ.get('XDG_SESSION_TYPE', 'unknown')
        info['desktop'] = os.environ.get(
            'XDG_CURRENT_DESKTOP',
            os.environ.get('DESKTOP_SESSION', 'unknown'),
        )
    return info


def _get_recent_logs(max_lines: int = 100) -> str:
    """Try to read the last N lines from the log file, if any."""
    # Common log paths used by UniCent
    candidates = [
        '/tmp/unicent-host.log',
        '/tmp/unicent-client.log',
        os.path.expanduser('~/unicent-host.log'),
        os.path.expanduser('~/unicent-client.log'),
    ]
    for path in candidates:
        try:
            with open(path, 'r', errors='replace') as f:
                lines = f.readlines()
                return ''.join(lines[-max_lines:])
        except (OSError, IOError):
            continue
    return ''


def send_bug_report(error_text: str, user_description: str = '',
                    title: str = '', include_logs: bool = True,
                    callback=None):
    """Send a bug report to the bug report server.

    Posts JSON to the Cloudflare Worker endpoint.  Runs in a
    background thread so the UI stays responsive.

    Args:
        error_text: The error/traceback text
        user_description: User's description of what happened
        title: Optional short title (auto-generated if empty)
        include_logs: Whether to attach recent log file output
        callback: Optional function(success: bool, message: str)
    """
    import threading

    def _send():
        system_info = _get_system_info()

        payload = {
            'software': __app_name__.lower(),
            'version': __version__,
            'description': user_description or '(no description)',
            'error': error_text,
            'system': system_info,
        }
        if title:
            payload['title'] = title

        if include_logs:
            logs = _get_recent_logs()
            if logs:
                payload['logs'] = logs

        # ── POST to bug report server ──
        try:
            data = json.dumps(payload).encode('utf-8')
            req = urllib_request.Request(
                __report_endpoint__,
                data=data,
                headers={
                    'Content-Type': 'application/json',
                    'X-API-Key': __report_api_key__,
                },
                method='POST',
            )
            with urllib_request.urlopen(req, timeout=15) as resp:
                body = json.loads(resp.read().decode('utf-8'))
                report_id = body.get('id', '?')
                issue_url = body.get('issue_url')
                msg = f"Bug report submitted (ID: {report_id[:8]}…)."
                if issue_url:
                    msg += f"\nGitHub Issue: {issue_url}"
                msg += "\nThank you!"
                log.info("Bug report submitted: %s", report_id)
                if callback:
                    callback(True, msg)

        except urllib_error.HTTPError as e:
            err_body = ''
            try:
                err_body = e.read().decode('utf-8', errors='replace')
            except Exception:
                pass
            log.error("Bug report HTTP error %d: %s", e.code, err_body)
            if e.code == 429:
                msg = "Rate limited — please try again later."
            elif e.code == 401:
                msg = "Authentication failed. Please update the software."
            else:
                msg = f"Server error ({e.code}). Report not submitted."
            if callback:
                callback(False, msg)

        except Exception as e:
            log.error("Bug report failed: %s", e)
            msg = (f"Could not reach the bug report server.\n"
                   f"Error: {e}\n\n"
                   f"Please report manually at:\n"
                   f"https://github.com/JoshuaMGoth/unicent/issues")
            if callback:
                callback(False, msg)

    thread = threading.Thread(target=_send, daemon=True)
    thread.start()
    return thread


def format_report_text(error_text: str, user_description: str = '') -> str:
    """Format a complete bug report as text (fallback for manual copy)."""
    system_info = _get_system_info()
    parts = [
        f"Software: {__app_name__} v{__version__}",
        "",
    ]
    if user_description:
        parts.append(f"Description:\n{user_description}")
        parts.append("")
    parts.append(f"Error / Log:\n{error_text}")
    parts.append("")
    parts.append("System Info:")
    for k, v in system_info.items():
        parts.append(f"  {k}: {v}")
    return '\n'.join(parts)
