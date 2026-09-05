"""Iniciar o Artemis junto com o sistema. Escolhe a implementacao da plataforma.

No Windows e a chave Run do usuario atual (startup_win.py); no Linux e um
arquivo .desktop em ~/.config/autostart (linux.py). Os dois expoem a mesma
API, entao app.py e settings_window.py nao sabem a diferenca.
"""

from __future__ import annotations

import sys

if sys.platform == "win32":
    from .startup_win import (  # noqa: F401
        command,
        is_enabled,
        registered_command,
        set_enabled,
        sync,
    )
else:
    from .linux import (  # noqa: F401
        command,
        is_enabled,
        registered_command,
        set_enabled,
        sync,
    )
