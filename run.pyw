"""Atalho para rodar o Artemis sem janela de console.

Duplo clique neste arquivo (se .pyw estiver associado ao pythonw.exe) ou use
o Artemis.cmd, que ja aponta para o Python do .venv.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from artemis.__main__ import main  # noqa: E402

raise SystemExit(main([]))
