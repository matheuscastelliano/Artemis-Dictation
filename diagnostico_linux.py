"""Diagnostico do Artemis no Linux. Rodar depois do logout/login.

    .venv/bin/python <este arquivo>

Checa permissoes, le o teclado por 10s (aperte o F6 para descobrir o que ele
manda) e testa a colagem por uinput.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/home/matheus-castelliano/Documents/Projetos/Artemis-Dictation")

FALHAS = []


def secao(titulo):
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


secao("1. Grupos e permissoes")
import grp

grupos = [grp.getgrgid(g).gr_name for g in os.getgroups()]
tem_input = "input" in grupos
print(f"  grupo 'input' nesta sessao: {'SIM' if tem_input else 'NAO'}")
if not tem_input:
    FALHAS.append("Voce nao esta no grupo 'input' NESTA sessao. Faca logout/login.")
for caminho in ("/dev/uinput", "/dev/input/event13"):
    try:
        st = os.stat(caminho)
        legivel = os.access(caminho, os.R_OK)
        gravavel = os.access(caminho, os.W_OK)
        print(f"  {caminho}: leitura={legivel} escrita={gravavel}")
    except FileNotFoundError:
        print(f"  {caminho}: nao existe")


secao("2. Teclados que o Artemis enxerga")
import artemis.hotkeys_evdev as H

teclados = H._open_keyboards()
if not teclados:
    FALHAS.append("Nenhum teclado legivel em /dev/input.")
    print("  NENHUM")
for k in teclados:
    print(f"  {k.path:22} {k.name!r}")


secao("3. Aperte o F6 do MX Keys Mini agora (10 segundos)")
print("  Pode apertar outras teclas tambem. Ctrl+C para pular.\n")
from evdev import categorize, ecodes
import selectors

if teclados:
    sel = selectors.DefaultSelector()
    for k in teclados:
        sel.register(k, selectors.EVENT_READ)
    vistos = []
    fim = time.monotonic() + 10
    try:
        while time.monotonic() < fim:
            for chave, _ in sel.select(timeout=0.5):
                for ev in chave.fileobj.read():
                    if ev.type == ecodes.EV_KEY and ev.value == 1:
                        nome = ecodes.KEY.get(ev.code, f"?{ev.code}")
                        if isinstance(nome, list):
                            nome = nome[0]
                        vistos.append(nome)
                        print(f"    PRESS  {nome}  (code={ev.code})")
    except KeyboardInterrupt:
        print("    (pulado)")
    sel.close()
    print()
    if "KEY_LEFTMETA" in vistos and "KEY_H" in vistos:
        print("  >>> CONFIRMADO: o F6 manda Super+H. O preset <cmd>+h esta certo.")
    elif "KEY_DICTATE" in vistos:
        print("  >>> O F6 manda KEY_DICTATE. Troque o preset para <dictate>.")
    elif vistos:
        print(f"  >>> Chegaram: {sorted(set(vistos))}. Me manda isso.")
    else:
        FALHAS.append("Nenhuma tecla chegou - o evdev nao esta lendo.")
        print("  >>> NENHUMA tecla chegou.")
for k in teclados:
    k.close()


secao("4. Colagem por uinput")
from artemis.linux import _get_uinput, copy, read_clipboard

try:
    d = _get_uinput()
    print(f"  dispositivo virtual criado: {d.device.path}")
except Exception as e:
    FALHAS.append(f"uinput indisponivel: {e}")
    print(f"  FALHOU: {e}")


secao("5. Clipboard")
try:
    copy("artemis: teste de acentuacao ção")
    lido = read_clipboard()
    print(f"  escrito e lido de volta: {lido!r}")
    if lido != "artemis: teste de acentuacao ção":
        FALHAS.append("Clipboard nao devolveu o mesmo texto.")
except Exception as e:
    FALHAS.append(f"clipboard: {e}")
    print(f"  FALHOU: {e}")


secao("RESULTADO")
if FALHAS:
    for f in FALHAS:
        print(f"  FALHA: {f}")
    sys.exit(1)
print("  Tudo certo. Pode rodar: .venv/bin/python -m artemis --debug")
