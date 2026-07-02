#!/usr/bin/env python3
"""Генератор текстуры флага Казахстана для мода CQC-1 "One True Flag" (Helldivers 2).

Рисует стилизованный флаг Республики Казахстан: голубое полотнище,
золотое солнце с 32 лучами, парящий степной орёл (беркут) и
национальный орнамент "кошкар-мюиз" у древка.

Выход: PNG-файлы в каталоге textures/ в нескольких разрешениях
(2:1 — родные пропорции флага, 1:1 — растянутый вариант под квадратные UV).

Запуск:  python3 tools/generate_flag.py
"""

import math
import os

from PIL import Image, ImageDraw

# Официальные цвета флага
BLUE = (0, 175, 202)    # небесно-голубой
GOLD = (254, 197, 12)   # золотой

# Базовое полотно (2:1), рисуем с 4x суперсэмплингом для сглаживания
W, H = 2000, 1000
SS = 4


def qbez(p0, p1, p2, n=24):
    """Точки квадратичной кривой Безье."""
    pts = []
    for i in range(n + 1):
        t = i / n
        x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0]
        y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1]
        pts.append((x, y))
    return pts


def scale(pts, k):
    return [(x * k, y * k) for x, y in pts]


def draw_sun(d, k, cx=1060.0, cy=360.0):
    """Солнце: диск и 32 луча."""
    r_disc = 108
    r_in, r_out = 132, 210
    half = math.radians(3.0)
    for i in range(32):
        a = i * (2 * math.pi / 32)
        tri = [
            (cx + r_in * math.cos(a - half), cy + r_in * math.sin(a - half)),
            (cx + r_out * math.cos(a), cy + r_out * math.sin(a)),
            (cx + r_in * math.cos(a + half), cy + r_in * math.sin(a + half)),
        ]
        d.polygon(scale(tri, k), fill=GOLD)
    d.ellipse(scale([(cx - r_disc, cy - r_disc), (cx + r_disc, cy + r_disc)], k),
              fill=GOLD)


def draw_eagle(d, k, cx=1060.0):
    """Стилизованный силуэт парящего беркута под солнцем."""
    def sym(x):
        return 2 * cx - x

    # Правое крыло: верхняя кромка (плавная дуга к законцовке),
    # плечо ниже головы, чтобы силуэт читался
    top = qbez((cx + 18, 652), (cx + 170, 592), (cx + 330, 620))
    # Нижняя кромка: перья (зубцы), от законцовки внутрь к телу
    tips = [(cx + 300, 706), (cx + 252, 730), (cx + 200, 746),
            (cx + 146, 756), (cx + 92, 758), (cx + 44, 750)]
    trailing = []
    prev = top[-1]
    for t in tips:
        vx = (prev[0] + t[0]) / 2
        trailing.append((vx, t[1] - 56))
        trailing.append(t)
        prev = t
    right_wing = top + trailing + [(cx + 14, 730)]
    d.polygon(scale(right_wing, k), fill=GOLD)
    # Левое крыло — зеркально
    d.polygon(scale([(sym(x), y) for x, y in right_wing], k), fill=GOLD)

    # Тело (веретенообразное)
    d.ellipse(scale([(cx - 40, 622), (cx + 40, 752)], k), fill=GOLD)
    # Шея
    d.polygon(scale([(cx - 22, 588), (cx + 14, 588), (cx + 22, 660),
                     (cx - 26, 660)], k), fill=GOLD)
    # Голова (клюв к древку, т.е. влево)
    d.ellipse(scale([(cx - 30, 566), (cx + 14, 610)], k), fill=GOLD)
    d.polygon(scale([(cx - 24, 576), (cx - 70, 592), (cx - 24, 600)], k),
              fill=GOLD)  # клюв

    # Хвост: веер с зубцами, сужается от тела
    tail_tips = [(cx - 60, 830), (cx - 20, 844), (cx + 20, 844), (cx + 60, 830)]
    tail = [(cx - 30, 740)]
    prev = None
    for t in tail_tips:
        if prev is not None:
            vx = (prev[0] + t[0]) / 2
            tail.append((vx, t[1] - 48))
        tail.append(t)
        prev = t
    tail.append((cx + 30, 740))
    d.polygon(scale(tail, k), fill=GOLD)


def draw_ornament(d, k, img_ss):
    """Полоса национального орнамента (кошкар-мюиз, "бараньи рога") у древка."""
    band_cx = 130.0
    motif_h = 250.0
    n = 4
    total = n * motif_h
    y0 = (H - total) / 2
    lw = int(20 * k)  # толщина линий орнамента

    def horn(cy, mx, my):
        """Один рог: стебель от оси + спиральный завиток на конце."""
        # стебель — дуга от центра мотива наружу
        stem = qbez((band_cx + mx * 8, cy + my * 20),
                    (band_cx + mx * 78, cy + my * 34),
                    (band_cx + mx * 74, cy + my * 92))
        d.line(scale(stem, k), fill=GOLD, width=lw, joint="curve")
        # завиток: незамкнутая дуга ~250°, закручивается внутрь
        ex, ey = stem[-1]
        r = 26
        ccx, ccy = ex - mx * r, ey
        start = -90 * my * mx
        # рисуем дугу по точкам, чтобы управлять направлением закрутки
        pts = []
        for i in range(41):
            a = math.radians(start + (250 * i / 40) * (1 if mx * my > 0 else -1))
            pts.append((ccx + r * math.cos(a), ccy + r * math.sin(a)))
        d.line(scale(pts, k), fill=GOLD, width=lw, joint="curve")

    for i in range(n):
        cy = y0 + motif_h * (i + 0.5)
        # центральный ромб
        d.polygon(scale([(band_cx, cy - 50), (band_cx + 36, cy),
                         (band_cx, cy + 50), (band_cx - 36, cy)], k), fill=GOLD)
        # стержень между мотивами
        d.line(scale([(band_cx, cy - motif_h / 2), (band_cx, cy + motif_h / 2)], k),
               fill=GOLD, width=int(14 * k))
        # четыре рога (вверх/вниз, влево/вправо)
        for my in (-1, 1):
            for mx in (-1, 1):
                horn(cy, mx, my)


def render():
    k = SS
    img = Image.new("RGB", (W * k, H * k), BLUE)
    d = ImageDraw.Draw(img)
    draw_sun(d, k)
    draw_eagle(d, k)
    draw_ornament(d, k, img)
    return img


def main():
    out_dir = os.path.join(os.path.dirname(__file__), "..", "textures")
    os.makedirs(out_dir, exist_ok=True)

    big = render()

    outputs = {
        "kz_flag_4096x2048.png": (4096, 2048),
        "kz_flag_2048x1024.png": (2048, 1024),
        "kz_flag_2048x2048.png": (2048, 2048),  # растянутый под квадратные UV
        "kz_flag_1024x1024.png": (1024, 1024),
    }
    for name, size in outputs.items():
        big.resize(size, Image.LANCZOS).save(os.path.join(out_dir, name))
        print("wrote", name)


if __name__ == "__main__":
    main()
