#!/usr/bin/env python3
"""Genera assets/radar-dark.svg y assets/radar-light.svg.

Cambia las notas (0-10) de HABILIDADES y ejecuta:
    python scripts/radar.py
"""

import math
from html import escape
from pathlib import Path

HABILIDADES = {
    "Backend y APIs": 7,
    "Apps móviles": 6,
    "Frontend web": 6,
    "Bases de datos": 7,
    "Cloud / AWS": 5,
    "Sistemas y redes": 8,
    "IA aplicada": 6,
}

TEMAS = {
    "dark": {"titulo": "#e6edf3", "texto": "#c9d1d9", "anillo": "#30363d", "eje": "#21262d", "color": "#ff8a3d"},
    "light": {"titulo": "#1f2328", "texto": "#424a53", "anillo": "#d0d7de", "eje": "#eaeef2", "color": "#e2601a"},
}

W, H = 669, 526
CX, CY, R = 334.5, 289.0, 200.0
SALIDA = Path(__file__).resolve().parents[1] / "assets"


def punto(r: float, i: int, n: int) -> tuple[float, float]:
    a = -math.pi / 2 + 2 * math.pi * i / n
    return r * math.cos(a), r * math.sin(a)


def svg(tema: str) -> str:
    t = TEMAS[tema]
    nombres = list(HABILIDADES)
    n = len(nombres)
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" '
         f'aria-label="Radar de habilidades" font-family="ui-sans-serif,-apple-system,Segoe UI,Helvetica,Arial,sans-serif">',
         f'<text x="{W/2}" y="25" text-anchor="middle" font-size="15" font-weight="700" fill="{t["titulo"]}">Radar de habilidades</text>',
         f'<g transform="translate({CX},{CY})">']
    for f, op in ((1, .85), (.75, .72), (.5, .6), (.25, .47)):
        pts = " ".join("%.1f,%.1f" % punto(R * f, i, n) for i in range(n))
        o.append(f'<polygon points="{pts}" fill="none" stroke="{t["anillo"]}" opacity="{op}"/>')
    for i in range(n):
        x, y = punto(R, i, n)
        o.append(f'<line x1="0" y1="0" x2="{x:.1f}" y2="{y:.1f}" stroke="{t["eje"]}"/>')
    datos = [punto(R * HABILIDADES[k] / 10, i, n) for i, k in enumerate(nombres)]
    o.append('<g><animateTransform attributeName="transform" type="scale" values="0.04;1" dur="1.1s" calcMode="spline" '
             'keyTimes="0;1" keySplines="0.22 1 0.36 1" fill="freeze"/>')
    o.append(f'<polygon points="{" ".join("%.1f,%.1f" % p for p in datos)}" fill="{t["color"]}" fill-opacity="0.22" '
             f'stroke="{t["color"]}" stroke-width="2.5" stroke-linejoin="round"/>')
    o += [f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.6" fill="{t["color"]}"/>' for x, y in datos]
    o.append("</g>")
    for i, k in enumerate(nombres):
        x, y = punto(R + 24, i, n)
        ancla = "middle" if abs(x) < 5 else ("start" if x > 0 else "end")
        y += 10 if y > 0 else (-2 if abs(x) < 5 else 0)
        o.append(f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{ancla}" font-size="13" font-weight="600" fill="{t["texto"]}">{escape(k)}</text>')
    o.append("</g></svg>")
    return "".join(o)


if __name__ == "__main__":
    for tema in TEMAS:
        (SALIDA / f"radar-{tema}.svg").write_text(svg(tema), encoding="utf-8")
        print(f"assets/radar-{tema}.svg")
