"""O desenho do icone do Artemis, em um lugar so.

Serve a bandeja (um PNG por estado, trocado a cada mudanca de status) e a
instalacao no menu de aplicativos do Linux, que precisa do mesmo simbolo em
varios tamanhos. Desenhado em codigo, e nao carregado de um .ico, porque o
icone muda de cor conforme o estado e porque assim nao ha binario no repo.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

# A cor de cada estado do app. "idle" e o cinza neutro da barra.
COLORS = {
    "idle": (120, 120, 128),
    "recording": (229, 72, 77),
    "processing": (245, 165, 36),
    "done": (48, 164, 108),
    "error": (229, 72, 77),
}


def make_icon(color: tuple[int, int, int], size: int = 128) -> Image.Image:
    """Um microfone claro sobre o disco da cor do estado.

    Desenhado em 4x e reduzido no fim: o painel do GNOME exibe isto com uns
    22 px de altura, e sem o supersampling as curvas ficam serrilhadas.
    """
    scale = 4
    box = size * scale
    image = Image.new("RGBA", (box, box), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    pad = box * 0.04
    draw.ellipse([pad, pad, box - pad, box - pad], fill=(*color, 255))

    ink = (255, 255, 255, 255)
    cx = box / 2
    # Capsula do microfone.
    capsule_w = box * 0.22
    capsule_top = box * 0.24
    capsule_bottom = box * 0.56
    draw.rounded_rectangle(
        [cx - capsule_w / 2, capsule_top, cx + capsule_w / 2, capsule_bottom],
        radius=capsule_w / 2,
        fill=ink,
    )
    # Arco que abraca a capsula por baixo.
    stroke = box * 0.055
    arc_w = box * 0.42
    arc_top = box * 0.36
    arc_bottom = box * 0.70
    draw.arc(
        [cx - arc_w / 2, arc_top, cx + arc_w / 2, arc_bottom],
        start=0,
        end=180,
        fill=ink,
        width=int(stroke),
    )
    # Haste e base.
    draw.line(
        [cx, arc_bottom - stroke / 2, cx, box * 0.82], fill=ink, width=int(stroke)
    )
    base_w = box * 0.26
    draw.line(
        [cx - base_w / 2, box * 0.82, cx + base_w / 2, box * 0.82],
        fill=ink,
        width=int(stroke),
    )

    return image.resize((size, size), Image.LANCZOS)
