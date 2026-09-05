"""Entrega do texto na aplicacao ativa. Escolhe a implementacao da plataforma.

A logica real esta em output_win.py (Win32: clipboard + Ctrl+V por SendInput)
e em linux.py (wl-copy/xclip + Ctrl+V por /dev/uinput). O codigo do Windows
nao foi alterado no porte para Linux - so passou a ficar atras deste if.
"""

from __future__ import annotations

import sys

if sys.platform == "win32":
    from .output_win import (  # noqa: F401
        copy,
        deliver,
        foreground_window,
        read_clipboard,
        restore_focus,
        send_paste,
    )
else:
    from .linux import (  # noqa: F401
        copy,
        deliver,
        foreground_window,
        read_clipboard,
        restore_focus,
        send_paste,
    )
