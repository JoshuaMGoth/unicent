"""
UniCent cross-platform GUI dialogs — About, Settings, Update, Bug Report.

Uses tkinter (bundled with Python) for maximum portability.
All dialogs run in their own thread to avoid blocking the main loop.
"""

import logging
import os
import platform
import subprocess
import threading
import webbrowser
from typing import Optional, Callable

from shared.version import (
    __version__, __app_name__, __author__, __website__,
    __support_email__, __repo_url__, __description__,
)

log = logging.getLogger(__name__)

_SYSTEM = platform.system()

# Lazy tkinter import — may not be available
_tk = None
_ttk = None
_messagebox = None
_scrolledtext = None


def _ensure_tk():
    """Import tkinter lazily."""
    global _tk, _ttk, _messagebox, _scrolledtext
    if _tk is None:
        import tkinter as tk
        import tkinter.ttk as ttk
        import tkinter.messagebox as messagebox
        import tkinter.scrolledtext as scrolledtext
        _tk = tk
        _ttk = ttk
        _messagebox = messagebox
        _scrolledtext = scrolledtext
    return _tk


def _center_window(win, width: int, height: int):
    """Center a tkinter window on screen."""
    win.update_idletasks()
    x = (win.winfo_screenwidth() // 2) - (width // 2)
    y = (win.winfo_screenheight() // 2) - (height // 2)
    win.geometry(f'{width}x{height}+{x}+{y}')


def _apply_theme(root):
    """Apply a clean dark theme."""
    bg = '#2b2b2b'
    fg = '#e0e0e0'
    accent = '#6a0dad'
    btn_bg = '#3c3c3c'
    entry_bg = '#3c3c3c'

    root.configure(bg=bg)

    style = _ttk.Style(root)
    style.theme_use('clam')

    style.configure('.', background=bg, foreground=fg, borderwidth=0,
                    font=('Segoe UI', 10) if _SYSTEM == 'Windows' else ('Helvetica', 11))
    style.configure('TLabel', background=bg, foreground=fg, padding=2)
    style.configure('TButton', background=btn_bg, foreground=fg, padding=(12, 6),
                    borderwidth=1, relief='flat')
    style.map('TButton',
              background=[('active', accent), ('pressed', accent)],
              foreground=[('active', '#ffffff'), ('pressed', '#ffffff')])
    style.configure('Accent.TButton', background=accent, foreground='#ffffff')
    style.map('Accent.TButton',
              background=[('active', '#7b1fa2'), ('pressed', '#4a0072')])
    style.configure('TFrame', background=bg)
    style.configure('TLabelframe', background=bg, foreground=fg)
    style.configure('TLabelframe.Label', background=bg, foreground=fg)
    style.configure('Header.TLabel', font=('Helvetica', 18, 'bold'),
                    foreground=accent)
    style.configure('Sub.TLabel', foreground='#aaaaaa',
                    font=('Helvetica', 9))
    style.configure('Link.TLabel', foreground='#7da6ff', cursor='hand2',
                    font=('Helvetica', 10, 'underline'))
    style.configure('Version.TLabel', foreground='#88cc88',
                    font=('Helvetica', 10))

    return bg, fg, accent, btn_bg, entry_bg


def _run_in_thread(func):
    """Run a dialog function in a new thread."""
    def wrapper(*args, **kwargs):
        t = threading.Thread(target=func, args=args, kwargs=kwargs, daemon=True)
        t.start()
        return t
    return wrapper


# ────────────────────────────────────────────────────────────
#  About Dialog
# ────────────────────────────────────────────────────────────

@_run_in_thread
def show_about_dialog():
    """Show the About UniCent dialog."""
    tk = _ensure_tk()
    root = tk.Tk()
    root.title(f'About {__app_name__}')
    root.resizable(False, False)
    bg, fg, accent, _, _ = _apply_theme(root)

    frame = _ttk.Frame(root, padding=30)
    frame.pack(fill='both', expand=True)

    # Icon
    icon_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'assets', 'icon-u-128.png',
    )
    photo = None
    if os.path.exists(icon_path):
        try:
            from PIL import Image, ImageTk
            img = Image.open(icon_path).resize((80, 80), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            icon_label = _ttk.Label(frame, image=photo)
            icon_label.image = photo  # keep reference
            icon_label.pack(pady=(0, 10))
        except ImportError:
            pass

    # App name
    _ttk.Label(frame, text=__app_name__, style='Header.TLabel').pack()

    # Version
    _ttk.Label(frame, text=f'Version {__version__}',
               style='Version.TLabel').pack(pady=(2, 8))

    # Description
    _ttk.Label(frame, text=__description__).pack(pady=(0, 4))

    # Author
    _ttk.Label(frame, text=f'A {__author__} Product',
               style='Sub.TLabel').pack(pady=(8, 2))

    # Website link
    link = _ttk.Label(frame, text=__website__, style='Link.TLabel')
    link.pack(pady=(2, 2))
    link.bind('<Button-1>', lambda e: webbrowser.open(__website__))

    # Support email
    email_link = _ttk.Label(frame, text=__support_email__, style='Link.TLabel')
    email_link.pack(pady=(2, 8))
    email_link.bind('<Button-1>', lambda e: webbrowser.open(f'mailto:{__support_email__}'))

    # GitHub
    gh_link = _ttk.Label(frame, text='GitHub Repository', style='Link.TLabel')
    gh_link.pack(pady=(2, 12))
    gh_link.bind('<Button-1>', lambda e: webbrowser.open(__repo_url__))

    # Close button
    _ttk.Button(frame, text='Close', command=root.destroy).pack(pady=(8, 0))

    _center_window(root, 360, 440)
    root.attributes('-topmost', True)
    root.focus_force()
    root.mainloop()


# ────────────────────────────────────────────────────────────
#  Update Dialog
# ────────────────────────────────────────────────────────────

@_run_in_thread
def show_update_dialog(update_info: Optional[dict] = None):
    """Show the update checker / installer dialog.

    Args:
        update_info: Pre-fetched update info dict, or None to check now.
    """
    from shared.updater import check_for_update, perform_update

    tk = _ensure_tk()
    root = tk.Tk()
    root.title(f'{__app_name__} — Updates')
    root.resizable(False, False)
    bg, fg, accent, _, _ = _apply_theme(root)

    frame = _ttk.Frame(root, padding=24)
    frame.pack(fill='both', expand=True)

    _ttk.Label(frame, text='Software Update', style='Header.TLabel').pack(pady=(0, 16))

    status_var = tk.StringVar(value='Checking for updates...')
    status_label = _ttk.Label(frame, textvariable=status_var, wraplength=340)
    status_label.pack(pady=(0, 12))

    notes_text = None
    btn_frame = _ttk.Frame(frame)
    btn_frame.pack(pady=(8, 0))

    update_btn = _ttk.Button(btn_frame, text='Install Update', style='Accent.TButton')
    close_btn = _ttk.Button(btn_frame, text='Close', command=root.destroy)
    close_btn.pack(side='right', padx=(4, 0))

    _center_window(root, 420, 320)
    root.attributes('-topmost', True)
    root.focus_force()

    def _on_check_result(info):
        if info:
            root.after(0, lambda: _show_update_available(info))
        else:
            root.after(0, lambda: status_var.set(
                f'You are running the latest version.\n\n'
                f'Current version: {__version__}'))

    def _show_update_available(info):
        status_var.set(
            f'A new version is available!\n\n'
            f'Current: v{info["current"]}  →  Latest: v{info["latest"]}')
        if info.get('notes'):
            nonlocal notes_text
            notes_frame = _ttk.LabelFrame(frame, text='Release Notes', padding=8)
            notes_frame.pack(fill='both', expand=True, pady=(8, 0))
            notes_text = _scrolledtext.ScrolledText(
                notes_frame, width=45, height=6, wrap='word',
                bg='#3c3c3c', fg='#e0e0e0', insertbackground='#e0e0e0',
                relief='flat', borderwidth=0,
            )
            notes_text.insert('1.0', info['notes'])
            notes_text.configure(state='disabled')
            notes_text.pack(fill='both', expand=True)
            _center_window(root, 420, 460)

        def _do_install():
            update_btn.configure(state='disabled')
            status_var.set('Installing update...')
            perform_update(callback=lambda ok, msg: root.after(
                0, lambda: _on_update_done(ok, msg)))

        update_btn.configure(command=_do_install)
        update_btn.pack(side='right', padx=(4, 0))

    def _on_update_done(success, message):
        status_var.set(message)
        update_btn.pack_forget()
        if success:
            root.after(0, lambda: _center_window(root, 420, 280))

    # Start check
    if update_info:
        _show_update_available(update_info)
    else:
        from shared.updater import check_for_update_async
        check_for_update_async(_on_check_result)

    root.mainloop()


# ────────────────────────────────────────────────────────────
#  Bug Report Dialog
# ────────────────────────────────────────────────────────────

@_run_in_thread
def show_bug_report_dialog():
    """Show the bug report submission dialog."""
    from shared.bug_report import send_bug_report, format_report_text

    tk = _ensure_tk()
    root = tk.Tk()
    root.title(f'{__app_name__} — Report a Bug')
    root.resizable(True, True)
    bg, fg, accent, _, entry_bg = _apply_theme(root)

    frame = _ttk.Frame(root, padding=20)
    frame.pack(fill='both', expand=True)

    _ttk.Label(frame, text='Report a Bug', style='Header.TLabel').pack(pady=(0, 8))
    _ttk.Label(frame, text='Reports are submitted directly — no email required.',
               style='Sub.TLabel').pack(pady=(0, 12))

    # Description
    _ttk.Label(frame, text='What happened?').pack(anchor='w')
    desc_text = tk.Text(frame, width=55, height=3, wrap='word',
                        bg=entry_bg, fg=fg, insertbackground=fg,
                        relief='flat', borderwidth=1, highlightthickness=1,
                        highlightbackground='#555555')
    desc_text.pack(fill='x', pady=(4, 12))

    # Error text
    _ttk.Label(frame, text='Paste error / log output here (optional):').pack(anchor='w')
    error_text = _scrolledtext.ScrolledText(
        frame, width=55, height=12, wrap='word',
        bg=entry_bg, fg=fg, insertbackground=fg,
        relief='flat', borderwidth=1, highlightthickness=1,
        highlightbackground='#555555',
    )
    error_text.pack(fill='both', expand=True, pady=(4, 12))

    # Status
    status_var = tk.StringVar(value='')
    status_label = _ttk.Label(frame, textvariable=status_var, wraplength=400)
    status_label.pack(pady=(0, 8))

    # Buttons
    btn_frame = _ttk.Frame(frame)
    btn_frame.pack(fill='x')

    def _on_send():
        err = error_text.get('1.0', 'end-1c').strip()
        desc = desc_text.get('1.0', 'end-1c').strip()
        if not desc and not err:
            status_var.set('Please describe the issue or paste an error.')
            return
        send_btn.configure(state='disabled')
        status_var.set('Submitting report...')

        def _on_result(success, message):
            root.after(0, lambda: _handle_result(success, message))

        send_bug_report(err, desc, callback=_on_result)

    def _handle_result(success, message):
        if success:
            status_var.set(message)
            root.after(3000, root.destroy)
        else:
            # Show the formatted report for manual copy
            status_var.set(message)
            err = error_text.get('1.0', 'end-1c').strip()
            desc = desc_text.get('1.0', 'end-1c').strip()
            report = format_report_text(err, desc)
            error_text.configure(state='normal')
            error_text.delete('1.0', 'end')
            error_text.insert('1.0', report)
            send_btn.configure(state='normal', text='Copy & Report Manually',
                               command=lambda: _copy_report(report))

    def _copy_report(text):
        root.clipboard_clear()
        root.clipboard_append(text)
        status_var.set('Copied! Open https://github.com/JoshuaMGoth/unicent/issues to submit.')

    send_btn = _ttk.Button(btn_frame, text='Submit Report',
                           style='Accent.TButton', command=_on_send)
    send_btn.pack(side='right', padx=(4, 0))
    _ttk.Button(btn_frame, text='Cancel', command=root.destroy).pack(side='right')

    _center_window(root, 520, 520)
    root.attributes('-topmost', True)
    root.focus_force()
    root.mainloop()


# ────────────────────────────────────────────────────────────
#  Settings Dialog (Host)
# ────────────────────────────────────────────────────────────

@_run_in_thread
def show_settings_dialog(host=None):
    """Show host settings dialog.

    Args:
        host: UniCentHost instance (if available) for live settings.
    """
    tk = _ensure_tk()
    root = tk.Tk()
    root.title(f'{__app_name__} — Settings')
    root.resizable(False, False)
    bg, fg, accent, btn_bg, entry_bg = _apply_theme(root)

    frame = _ttk.Frame(root, padding=20)
    frame.pack(fill='both', expand=True)

    _ttk.Label(frame, text='Settings', style='Header.TLabel').pack(pady=(0, 16))

    # Client side
    side_frame = _ttk.LabelFrame(frame, text='Client Placement', padding=10)
    side_frame.pack(fill='x', pady=(0, 12))

    current_side = 'right'
    if host:
        current_side = getattr(host, 'client_side', 'right')

    side_var = tk.StringVar(value=current_side)
    _ttk.Radiobutton(side_frame, text='Left side', variable=side_var,
                     value='left').pack(anchor='w')
    _ttk.Radiobutton(side_frame, text='Right side', variable=side_var,
                     value='right').pack(anchor='w')

    # Clipboard sync
    clip_frame = _ttk.LabelFrame(frame, text='Clipboard', padding=10)
    clip_frame.pack(fill='x', pady=(0, 12))

    auto_clip_var = tk.BooleanVar(value=True)
    _ttk.Checkbutton(clip_frame, text='Auto-sync clipboard on machine switch',
                     variable=auto_clip_var).pack(anchor='w')

    # Network
    net_frame = _ttk.LabelFrame(frame, text='Network', padding=10)
    net_frame.pack(fill='x', pady=(0, 12))

    port_val = 27183
    if host and hasattr(host, 'port'):
        port_val = host.port

    port_frame = _ttk.Frame(net_frame)
    port_frame.pack(fill='x')
    _ttk.Label(port_frame, text='Port:').pack(side='left')
    port_var = tk.StringVar(value=str(port_val))
    port_entry = tk.Entry(port_frame, textvariable=port_var, width=8,
                          bg=entry_bg, fg=fg, insertbackground=fg,
                          relief='flat', borderwidth=1)
    port_entry.pack(side='left', padx=(8, 0))
    _ttk.Label(port_frame, text='(requires restart)', style='Sub.TLabel').pack(
        side='left', padx=(8, 0))

    # Status
    status_var = tk.StringVar(value='')
    _ttk.Label(frame, textvariable=status_var).pack(pady=(4, 0))

    # Buttons
    btn_frame = _ttk.Frame(frame)
    btn_frame.pack(fill='x', pady=(12, 0))

    def _apply():
        new_side = side_var.get()
        if host:
            if new_side != getattr(host, 'client_side', 'right'):
                host.client_side = new_side
                host.layout.client_side = new_side
                host.layout._recalculate_layout()
                if hasattr(host, 'tray') and host.tray:
                    host.tray.update_menu()
                status_var.set(f'Client side changed to {new_side}')
            else:
                status_var.set('Settings applied')
        else:
            status_var.set('Settings applied (restart required)')

    _ttk.Button(btn_frame, text='Apply', style='Accent.TButton',
                command=_apply).pack(side='right', padx=(4, 0))
    _ttk.Button(btn_frame, text='Close', command=root.destroy).pack(side='right')

    _center_window(root, 400, 440)
    root.attributes('-topmost', True)
    root.focus_force()
    root.mainloop()
