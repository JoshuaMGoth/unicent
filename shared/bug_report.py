"""
UniCent bug report sender — emails reports to support@joshuagoth.com.
Uses SMTP or a mailto: fallback.
"""

import logging
import platform
import os
import subprocess
import sys
from typing import Optional

from shared.version import __version__, __support_email__, __app_name__

log = logging.getLogger(__name__)

_SYSTEM = platform.system()


def _get_system_info() -> str:
    """Gather system info for the bug report."""
    lines = [
        f"UniCent Version: {__version__}",
        f"Platform: {platform.system()} {platform.release()}",
        f"Architecture: {platform.machine()}",
        f"Python: {platform.python_version()}",
        f"Hostname: {platform.node()}",
    ]
    # Display server on Linux
    if _SYSTEM == 'Linux':
        session_type = os.environ.get('XDG_SESSION_TYPE', 'unknown')
        lines.append(f"Display Server: {session_type}")
        desktop = os.environ.get('XDG_CURRENT_DESKTOP', os.environ.get('DESKTOP_SESSION', 'unknown'))
        lines.append(f"Desktop: {desktop}")
    return '\n'.join(lines)


def send_bug_report(error_text: str, user_description: str = '',
                    callback=None):
    """Send a bug report email.

    Tries mailto: URL to open the default mail client.
    Falls back to printing the info for manual sending.

    Args:
        error_text: The error/traceback text
        user_description: User's description of what happened
        callback: Optional function(success: bool, message: str)
    """
    import threading

    def _send():
        system_info = _get_system_info()

        subject = f"[UniCent Bug Report] v{__version__} — {platform.system()}"
        body_parts = []
        if user_description:
            body_parts.append(f"Description:\n{user_description}")
        body_parts.append(f"Error / Log:\n{error_text}")
        body_parts.append(f"System Info:\n{system_info}")
        body = '\n\n---\n\n'.join(body_parts)

        # Try mailto: URI
        success = _open_mailto(subject, body)

        if success:
            msg = "Email client opened with bug report.\nPlease click Send."
            if callback:
                callback(True, msg)
        else:
            # Fallback: copy to clipboard and instruct user
            msg = (f"Could not open email client.\n\n"
                   f"Please email the following to {__support_email__}:\n\n"
                   f"Subject: {subject}\n\n{body}")
            if callback:
                callback(False, msg)

    thread = threading.Thread(target=_send, daemon=True)
    thread.start()
    return thread


def _open_mailto(subject: str, body: str) -> bool:
    """Open a mailto: link in the default email client."""
    import urllib.parse
    params = urllib.parse.urlencode({
        'subject': subject,
        'body': body,
    }, quote_via=urllib.parse.quote)
    mailto_url = f"mailto:{__support_email__}?{params}"

    try:
        if _SYSTEM == 'Linux':
            subprocess.Popen(['xdg-open', mailto_url],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        elif _SYSTEM == 'Darwin':
            subprocess.Popen(['open', mailto_url],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        elif _SYSTEM == 'Windows':
            os.startfile(mailto_url)
            return True
    except Exception as e:
        log.debug(f"mailto failed: {e}")

    # Fallback: try webbrowser
    try:
        import webbrowser
        webbrowser.open(mailto_url)
        return True
    except Exception:
        pass

    return False


def format_report_text(error_text: str, user_description: str = '') -> str:
    """Format a complete bug report as text (for when email fails)."""
    system_info = _get_system_info()
    subject = f"[UniCent Bug Report] v{__version__} — {platform.system()}"
    parts = [
        f"To: {__support_email__}",
        f"Subject: {subject}",
        "",
    ]
    if user_description:
        parts.append(f"Description:\n{user_description}")
        parts.append("")
    parts.append(f"Error / Log:\n{error_text}")
    parts.append("")
    parts.append(f"System Info:\n{system_info}")
    return '\n'.join(parts)
