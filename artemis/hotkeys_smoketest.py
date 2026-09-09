"""Teste da reemissao de teclas do backend evdev, sem tocar no teclado real.

    python -m artemis.hotkeys_smoketest

Com a supressao ligada, o Artemis captura o teclado com exclusividade e passa
a ser responsavel por devolver ao sistema tudo que nao for atalho. Um erro
nessa logica nao aparece como excecao: aparece como tecla que some, tecla que
fica presa ou atalho que continua vazando. Por isso a maquina de estados e
exercitada aqui contra um teclado virtual de mentira, com o writer trocado
por um dublê que so anota o que sairia.

O caminho de verdade - grab, uinput, kernel - nao e testado aqui; para isso
rode o app e olhe o log ("Capturando com exclusividade: ...").
"""

from __future__ import annotations

import sys

from evdev import ecodes

from .hotkeys_evdev import HotkeyManager

_PRESETS = (("<cmd>+h", "toggle"), ("<ctrl>+<alt>+1", "toggle"))


class _FakeWriter:
    """No lugar do /dev/uinput: guarda o que teria sido reemitido."""

    def __init__(self):
        self.out: list[str] = []

    def key(self, code: int, value: int) -> None:
        name = ecodes.KEY[code]
        name = name if isinstance(name, str) else name[0]
        self.out.append(f"{name.replace('KEY_', '')}{'v' if value else '^'}")

    def release(self, codes) -> None:
        pass

    def close(self) -> None:
        pass


def _run(specs, sequence):
    """Toca uma sequencia de teclas capturadas e devolve (reemitido, atalhos)."""
    fired: list[tuple[str, str]] = []
    manager = HotkeyManager(lambda *_: None)
    for index, (spec, trigger) in enumerate(specs):
        manager.register(f"p{index}", spec, trigger)
    writer = _FakeWriter()
    manager._writer = writer
    for name, value in sequence:
        manager._on_key(ecodes.ecodes[name], value, grabbed=True)
    while True:  # a thread de despacho nao roda no teste; esvazia a fila
        try:
            fired.append(manager._events.get_nowait())
        except Exception:
            break
    return writer.out, fired, manager


def main() -> int:
    falhas = []

    def checa(titulo, esperado_teclas, esperado_atalhos, sequence, specs=_PRESETS):
        teclas, atalhos, manager = _run(specs, sequence)
        ok = teclas == esperado_teclas and atalhos == esperado_atalhos
        print(("OK   " if ok else "FALHA") + f"  {titulo}")
        if not ok:
            print(f"         teclas   {teclas}  esperado {esperado_teclas}")
            print(f"         atalhos  {atalhos}  esperado {esperado_atalhos}")
            falhas.append(titulo)
        return manager

    atalho1 = [("p0", "activate"), ("p0", "deactivate")]

    checa(
        "o atalho nao chega na aplicacao",
        [],
        atalho1,
        [("KEY_LEFTMETA", 1), ("KEY_H", 1), ("KEY_H", 0), ("KEY_LEFTMETA", 0)],
    )
    checa("a letra do atalho, sozinha, continua digitando",
          ["Hv", "H^"], [], [("KEY_H", 1), ("KEY_H", 0)])
    checa(
        "outra combinacao com o mesmo modificador passa inteira",
        ["LEFTMETAv", "Av", "A^", "LEFTMETA^"],
        [],
        [("KEY_LEFTMETA", 1), ("KEY_A", 1), ("KEY_A", 0), ("KEY_LEFTMETA", 0)],
    )
    checa(
        "tocar no Super sozinho abre o panorama (press + release)",
        ["LEFTMETAv", "LEFTMETA^"],
        [],
        [("KEY_LEFTMETA", 1), ("KEY_LEFTMETA", 0)],
    )
    checa(
        "Ctrl+C nao e engolido por causa do Ctrl+Alt+1",
        ["LEFTCTRLv", "Cv", "C^", "LEFTCTRL^"],
        [],
        [("KEY_LEFTCTRL", 1), ("KEY_C", 1), ("KEY_C", 0), ("KEY_LEFTCTRL", 0)],
    )
    checa(
        "atalho de tres teclas nao vaza",
        [],
        [("p1", "activate"), ("p1", "deactivate")],
        [("KEY_LEFTCTRL", 1), ("KEY_LEFTALT", 1), ("KEY_1", 1),
         ("KEY_1", 0), ("KEY_LEFTALT", 0), ("KEY_LEFTCTRL", 0)],
    )
    checa(
        "combinacao parecida, mas nao registrada, passa inteira",
        ["LEFTCTRLv", "LEFTALTv", "SPACEv", "SPACE^", "LEFTALT^", "LEFTCTRL^"],
        [],
        [("KEY_LEFTCTRL", 1), ("KEY_LEFTALT", 1), ("KEY_SPACE", 1),
         ("KEY_SPACE", 0), ("KEY_LEFTALT", 0), ("KEY_LEFTCTRL", 0)],
    )
    checa(
        "atalho sem modificador tambem nao vaza",
        [],
        atalho1,
        [("KEY_F6", 1), ("KEY_F6", 0)],
        specs=(("<f6>", "hold"),),
    )
    checa(
        "soltar o modificador antes da tecla nao vaza",
        [],
        atalho1,
        [("KEY_LEFTMETA", 1), ("KEY_H", 1), ("KEY_LEFTMETA", 0), ("KEY_H", 0)],
    )
    checa("auto-repeat nao duplica a tecla",
          ["Av", "A^"], [],
          [("KEY_A", 1), ("KEY_A", 2), ("KEY_A", 2), ("KEY_A", 0)])

    manager = checa(
        "depois do atalho nao sobra tecla presa",
        ["Av", "A^"],
        atalho1,
        [("KEY_LEFTMETA", 1), ("KEY_H", 1), ("KEY_H", 0), ("KEY_LEFTMETA", 0),
         ("KEY_A", 1), ("KEY_A", 0)],
    )
    sujo = manager._visible or manager._held_back or manager._consumed or manager._pressed
    print(("FALHA" if sujo else "OK   ") + "  estado limpo no fim")
    if sujo:
        falhas.append("estado limpo no fim")

    # Enquanto o atalho esta segurado, o compositor nao pode achar que ha
    # modificador pressionado - senao o Ctrl+V da colagem viraria Super+Ctrl+V.
    _, _, manager = _run(_PRESETS, [("KEY_LEFTMETA", 1), ("KEY_H", 1)])
    ok = manager.modifiers_held() is False
    print(("OK   " if ok else "FALHA") + "  o atalho nao deixa modificador visivel")
    if not ok:
        falhas.append("modificador visivel durante o atalho")

    print()
    if falhas:
        print(f"{len(falhas)} falha(s): {', '.join(falhas)}")
        return 1
    print("Tudo certo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
