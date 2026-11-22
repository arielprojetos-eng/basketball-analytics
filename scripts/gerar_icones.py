"""Gera os ícones do app (public/icons/) a partir de um desenho vetorial simples.

Uso (na raiz):  python scripts/gerar_icones.py
Requer Pillow (pip install pillow). Desenha em alta resolução e reduz, para bordas suaves.

Conceito: fundo verde do app, quadra discreta ao fundo, bola dividida pelas costuras em
quatro quartos (um deles destacado) e a linha de tendência saindo desse quarto.
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "public" / "icons"
S = 2048  # tela de desenho

GREEN = (18, 96, 62, 255)        # #12603E, acento do app
GREEN_DARK = (13, 74, 48, 255)
COURT = (255, 255, 255, 34)      # linhas da quadra, discretas
BALL = (247, 250, 248, 255)
SEAM = (18, 96, 62, 255)
OCHRE = (217, 137, 58, 255)      # quarto destacado (ocre da equipe B, mais claro)
TREND = (255, 255, 255, 255)


def px(v):
    return int(round(v * S))


def layer():
    return Image.new("RGBA", (S, S), (0, 0, 0, 0))


def draw_icon(rounded, scale=1.0):
    """rounded: cantos arredondados com fundo transparente (ícone comum).
    scale < 1 encolhe o desenho para caber na zona segura dos ícones adaptáveis."""
    img = layer()
    d = ImageDraw.Draw(img)
    if rounded:
        d.rounded_rectangle([0, 0, S - 1, S - 1], radius=px(0.225), fill=GREEN)
    else:
        d.rectangle([0, 0, S, S], fill=GREEN)

    def P(x, y):  # coordenadas do desenho, encolhidas em torno do centro
        return (px(0.5 + (x - 0.5) * scale), px(0.5 + (y - 0.5) * scale))

    def R(r):
        return px(r * scale)

    # leve variação de tom de cima para baixo (sem gradiente chamativo)
    shade = layer()
    sd = ImageDraw.Draw(shade)
    for i in range(64):
        y0 = int(S * i / 64)
        sd.rectangle([0, y0, S, y0 + S // 64 + 1], fill=(GREEN_DARK[0], GREEN_DARK[1], GREEN_DARK[2], int(70 * i / 63)))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=px(0.225) if rounded else 0, fill=255)
    img.paste(Image.alpha_composite(img, shade), (0, 0), mask)

    # quadra: garrafão, círculo do lance livre e arco de três, vistos de cima, saindo da base
    court = layer()
    c = ImageDraw.Draw(court)
    w = R(0.014)
    cx, base = 0.5, 1.0
    x0, y0 = P(0.37, 0.70)
    x1, y1 = P(0.63, 1.05)
    c.rectangle([x0, y0, x1, y1], outline=COURT, width=w)
    fx, fy = P(0.5, 0.70)
    fr = R(0.13)
    c.arc([fx - fr, fy - fr, fx + fr, fy + fr], 180, 360, fill=COURT, width=w)
    ax, ay = P(cx, base)
    ar = R(0.47)
    c.arc([ax - ar, ay - ar, ax + ar, ay + ar], 180, 360, fill=COURT, width=w)
    img = Image.alpha_composite(img, court)

    # bola com um quarto destacado
    bx, by = P(0.42, 0.57)
    br = R(0.27)
    ball = layer()
    b = ImageDraw.Draw(ball)
    b.ellipse([bx - br, by - br, bx + br, by + br], fill=BALL)
    b.pieslice([bx - br, by - br, bx + br, by + br], 270, 360, fill=OCHRE)
    # costuras: cruz e as duas curvas laterais, recortadas pelo círculo da bola
    seams = layer()
    s = ImageDraw.Draw(seams)
    sw = R(0.02)
    s.line([bx, by - br, bx, by + br], fill=SEAM, width=sw)
    s.line([bx - br, by, bx + br, by], fill=SEAM, width=sw)
    cr = R(0.30)
    off = R(0.40)
    s.ellipse([bx - off - cr, by - cr, bx - off + cr, by + cr], outline=SEAM, width=sw)
    s.ellipse([bx + off - cr, by - cr, bx + off + cr, by + cr], outline=SEAM, width=sw)
    clip = Image.new("L", (S, S), 0)
    ImageDraw.Draw(clip).ellipse([bx - br, by - br, bx + br, by + br], fill=255)
    seams.putalpha(Image.composite(seams.getchannel("A"), Image.new("L", (S, S), 0), clip))
    ball = Image.alpha_composite(ball, seams)
    img = Image.alpha_composite(img, ball)

    # linha de tendência saindo do quarto destacado
    t = layer()
    td = ImageDraw.Draw(t)
    a = math.radians(-45)
    start = (bx + br * math.cos(a) * 0.55, by + br * math.sin(a) * 0.55)
    pts = [start, P(0.67, 0.40), P(0.725, 0.455), P(0.84, 0.24)]
    lw = R(0.046)
    td.line(pts, fill=TREND, width=lw, joint="curve")
    for p in pts[:-1]:
        td.ellipse([p[0] - lw / 2, p[1] - lw / 2, p[0] + lw / 2, p[1] + lw / 2], fill=TREND)
    # ponta da seta na direção do último segmento
    (x2, y2), (x3, y3) = pts[-2], pts[-1]
    ang = math.atan2(y3 - y2, x3 - x2)
    hl, hw = R(0.11), R(0.075)
    tip = (x3 + math.cos(ang) * hl * 0.35, y3 + math.sin(ang) * hl * 0.35)
    left = (tip[0] - math.cos(ang) * hl + math.cos(ang + math.pi / 2) * hw,
            tip[1] - math.sin(ang) * hl + math.sin(ang + math.pi / 2) * hw)
    right = (tip[0] - math.cos(ang) * hl - math.cos(ang + math.pi / 2) * hw,
             tip[1] - math.sin(ang) * hl - math.sin(ang + math.pi / 2) * hw)
    td.polygon([tip, left, right], fill=TREND)
    img = Image.alpha_composite(img, t)
    return img


def save(img, size, name, flatten=False):
    out = img.resize((size, size), Image.LANCZOS)
    if flatten:  # iPhone não aceita transparência no ícone da tela inicial
        bg = Image.new("RGB", (size, size), GREEN[:3])
        bg.paste(out, (0, 0), out)
        out = bg
    out.save(OUT / name, optimize=True)
    print(f"{name}: {size}x{size}")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    regular = draw_icon(rounded=True)
    full = draw_icon(rounded=False)
    maskable = draw_icon(rounded=False, scale=0.8)  # Android corta até 20% nas bordas
    save(regular, 192, "icon-192.png")
    save(regular, 512, "icon-512.png")
    save(maskable, 512, "icon-maskable-512.png")
    save(full, 180, "apple-touch-icon.png", flatten=True)
    save(regular, 48, "favicon-48.png")


if __name__ == "__main__":
    main()
