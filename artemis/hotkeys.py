"""Hotkeys globais. Escolhe a implementacao da plataforma.

No Windows e um hook WH_KEYBOARD_LL via pynput (hotkeys_win.py). No Linux e
leitura direta de /dev/input via evdev (hotkeys_evdev.py), porque o backend
X11 do pynput nao enxerga teclas sob Wayland. Os dois expoem o mesmo
HotkeyManager e aceitam specs no mesmo formato, entao app.py, tray.py e a
janela de configuracoes nao sabem a diferenca.
"""

from __future__ import annotations

import sys

if sys.platform == "win32":
    from .hotkeys_win import HotkeyManager, describe  # noqa: F401
else:
    from .hotkeys_evdev import HotkeyManager, describe  # noqa: F401
