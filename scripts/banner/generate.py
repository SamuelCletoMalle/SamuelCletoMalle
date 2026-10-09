#!/usr/bin/env python3
"""Genera los banners animados del perfil (tema oscuro y claro).

La foto se convierte en una nube de puntos (dithering de 1 bit) que se
transforma en los logos de las tecnologías que hay en scripts/banner/logos/.

Uso (desde la raíz del repo):
    pip install numpy scipy pillow
    python scripts/banner/generate.py

Para cambiar los logos: añade o quita PNG con fondo transparente en
scripts/banner/logos/ y ajusta ORDEN_LOGOS.
"""

from __future__ import annotations

import html
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from scipy.optimize import linear_sum_assignment
from scipy.spatial.distance import cdist

RAIZ = Path(__file__).resolve().parents[2]
FOTO = Path(__file__).resolve().parent / "portrait.jpg"
LOGOS = Path(__file__).resolve().parent / "logos"
SALIDA = RAIZ / "assets"

ORDEN_LOGOS = ("linux", "java", "python", "javascript", "react", "android", "git", "postgresql")
RELLENAR_HUECOS: set[str] = set()  # nombres de logos de contorno que quieras rellenar

W, H = 1180, 610
INTRO = 3.2           # segundos de aparición inicial
RETRATO = 3.0         # segundos que se ve la cara en cada vuelta
TRANSICION = 1.3
PAUSA_LOGO = 3.6
VIAJEROS = 900
PUNTOS_LOGO = 3800
SEMILLA = 2026

# Zona visual (marco izquierdo)
VX, VY, VW, VH = 49, 124, 390, 414
RW, RH = 300, 340      # tamaño del retrato en puntos
RX, RY = VX + (VW - RW) // 2, VY + (VH - RH) // 2
LOGO_LADO = 300        # lado del logo dentro del marco
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"

FILAS_YAML = [
    (0, "perfil", ""),
    (1, "nombre", "Samuel Cleto Malle"),
    (1, "rol", "Desarrollador junior"),
    (1, "formacion", "2º DAM · antes SMR"),
    (1, "busco", "prácticas / primer puesto"),
    (1, "enfoque", "Apps móviles · Backend · IA"),
    (0, "stack", ""),
    (1, "lenguajes", "Java · Python · JavaScript · TypeScript · SQL"),
    (1, "frontend", "HTML · CSS · React · Vite"),
    (1, "mobile", "React Native · Expo · Android Studio"),
    (1, "backend", "Node.js · Supabase · Firebase"),
    (1, "bases_datos", "MySQL · PostgreSQL · SQLite"),
    (1, "cloud_git", "AWS · Git · GitHub"),
    (1, "sistemas", "Windows · Linux · Redes · Hardware"),
    (0, "extra", ""),
    (1, "certs", "AWS Cloud Practitioner · Python Essentials"),
    (1, "github", "SamuelCletoMalle"),
]

TEMAS = {
    "dark": {
        "fondo": "#0A0E17", "panel": "#0F1522", "panel2": "#131B2B",
        "linea": "#25324A", "suave": "#7F8BA3", "texto": "#EEF2F8",
        "puntos": "#FF8A3D", "cromo": "#2DD4BF", "sombra": "#02050B",
    },
    "light": {
        "fondo": "#FFF6EE", "panel": "#FFFFFF", "panel2": "#FFF1E4",
        "linea": "#F3CFB0", "suave": "#9A7B66", "texto": "#2A1A10",
        "puntos": "#E2601A", "cromo": "#0F8F82", "sombra": "#E5BFA0",
    },
}


# ---------------------------------------------------------------- utilidades

def conectado_al_borde(mascara: np.ndarray) -> np.ndarray:
    """Píxeles True de la máscara conectados con el borde de la imagen."""
    alto, ancho = mascara.shape
    visto = np.zeros_like(mascara, dtype=bool)
    cola: deque[tuple[int, int]] = deque()
    for x in range(ancho):
        cola.extend(((0, x), (alto - 1, x)))
    for y in range(alto):
        cola.extend(((y, 0), (y, ancho - 1)))
    while cola:
        y, x = cola.popleft()
        if visto[y, x] or not mascara[y, x]:
            continue
        visto[y, x] = True
        if y > 0: cola.append((y - 1, x))
        if y < alto - 1: cola.append((y + 1, x))
        if x > 0: cola.append((y, x - 1))
        if x < ancho - 1: cola.append((y, x + 1))
    return visto


def f1(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


def f4(v: float) -> str:
    return f"{v:.4f}".rstrip("0").rstrip(".")


def trazos(puntos: np.ndarray) -> str:
    """Agrupa puntos contiguos en horizontal en segmentos de path."""
    if not len(puntos):
        return ""
    unicos = sorted({(int(x), int(y)) for x, y in np.rint(puntos)}, key=lambda p: (p[1], p[0]))
    partes, i = [], 0
    while i < len(unicos):
        x0, y = unicos[i]
        x1 = x0
        i += 1
        while i < len(unicos) and unicos[i][1] == y and unicos[i][0] <= x1 + 1:
            x1 = unicos[i][0]
            i += 1
        partes.append(f"M{x0} {y}h{x1 - x0 + 1}")
    return "".join(partes)


def particulas(puntos: np.ndarray) -> str:
    unicos = sorted({(int(x), int(y)) for x, y in np.rint(puntos)}, key=lambda p: (p[1], p[0]))
    return "".join(f"M{x} {y}h1" for x, y in unicos)


# ---------------------------------------------------------------- retrato

def mascara_persona(img: Image.Image) -> np.ndarray:
    """Quita el fondo liso de la foto (rellenando desde los bordes por color)."""
    rgb = np.asarray(img.convert("RGB"), dtype=np.float32)
    borde = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    color_fondo = np.median(borde, axis=0)
    distancia = np.linalg.norm(rgb - color_fondo, axis=2)
    fondo = conectado_al_borde(distancia < 45)
    persona = ~fondo
    m = Image.fromarray((persona * 255).astype("uint8")).filter(ImageFilter.MedianFilter(5)).filter(ImageFilter.MinFilter(5))
    return np.asarray(m) > 127


def puntos_retrato(tema: str) -> np.ndarray:
    foto = ImageOps.exif_transpose(Image.open(FOTO)).convert("RGB")
    w, h = foto.size
    ancho = int(w * 0.92)
    alto = int(ancho * RH / RW)
    izq = (w - ancho) // 2
    arriba = int(h * 0.02)
    recorte = foto.crop((izq, arriba, izq + ancho, min(h, arriba + alto))).resize((RW, RH), Image.Resampling.LANCZOS)
    persona = mascara_persona(recorte)

    gris = ImageOps.grayscale(recorte)
    gris = ImageOps.autocontrast(gris, cutoff=1)
    # Difumina la parte baja (hombros) para que el retrato no acabe en un corte recto.
    g = np.asarray(gris, dtype=np.float32)
    fundido = np.clip((np.arange(RH) - (RH - 70)) / 70, 0, 1)[:, None]
    g = g * (1 - fundido) + (0 if tema == "dark" else 255) * fundido
    gris = Image.fromarray(g.astype("uint8"))
    if tema == "dark":
        gris = ImageEnhance.Contrast(gris).enhance(1.35)
        gris = ImageEnhance.Brightness(gris).enhance(1.05)
        gris = gris.filter(ImageFilter.UnsharpMask(radius=2, percent=160, threshold=1))
        bits = np.asarray(gris.convert("1")) > 0          # Floyd-Steinberg de PIL
        activos = bits & persona
    else:
        gris = ImageEnhance.Contrast(gris).enhance(1.25)
        gris = gris.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=1))
        bits = np.asarray(gris.convert("1")) > 0
        activos = (~bits) & persona

    ys, xs = np.where(activos)
    return np.column_stack((RX + xs, RY + ys)).astype(np.float32)


# ---------------------------------------------------------------- logos

def cargar_logo(ruta: Path, nombre: str) -> np.ndarray:
    icono = Image.open(ruta).convert("RGBA")
    caja = icono.getchannel("A").getbbox()
    icono = icono.crop(caja)
    icono.thumbnail((LOGO_LADO, LOGO_LADO), Image.Resampling.LANCZOS)
    alfa = np.asarray(icono.getchannel("A")) > 127
    if nombre in RELLENAR_HUECOS:
        alfa = ~conectado_al_borde(np.pad(~alfa, 1, constant_values=True))[1:-1, 1:-1]
    ys, xs = np.where(alfa)
    ox = VX + (VW - icono.width) / 2
    oy = VY + (VH - icono.height) / 2
    return np.column_stack((ox + xs, oy + ys)).astype(np.float32)


def cargar_logos() -> dict[str, np.ndarray]:
    disponibles = {p.stem.lower(): p for p in LOGOS.glob("*.png")}
    orden = [n for n in ORDEN_LOGOS if n in disponibles]
    orden += sorted(n for n in disponibles if n not in orden)
    if not orden:
        raise SystemExit("No hay logos PNG en scripts/banner/logos")
    return {n: cargar_logo(disponibles[n], n) for n in orden}


def muestrear(puntos: np.ndarray, rng: np.random.Generator, n: int) -> np.ndarray:
    return puntos[rng.choice(len(puntos), n, replace=len(puntos) < n)]


def emparejar(origen: np.ndarray, destino: np.ndarray) -> np.ndarray:
    """Asignación de coste mínimo: cada punto viaja al destino más cercano posible."""
    filas, cols = linear_sum_assignment(cdist(origen, destino, "sqeuclidean"))
    ordenado = np.empty_like(destino)
    ordenado[filas] = destino[cols]
    return ordenado


# ---------------------------------------------------------------- SVG

def render(tema: str, retrato: np.ndarray, logos: dict[str, np.ndarray], rng: np.random.Generator) -> str:
    t = TEMAS[tema]
    n = min(VIAJEROS, len(retrato))
    origen = retrato[rng.choice(len(retrato), n, replace=False)]

    destinos, actual = [], origen
    for pts in logos.values():
        actual = emparejar(actual, muestrear(pts, rng, n))
        destinos.append(actual)

    tiempos, fotogramas = [0.0, RETRATO], [origen, origen]
    for d in destinos:
        tiempos += [tiempos[-1] + TRANSICION, tiempos[-1] + TRANSICION + PAUSA_LOGO]
        fotogramas += [d, d]
    tiempos.append(tiempos[-1] + TRANSICION)
    fotogramas.append(origen)
    total = tiempos[-1]
    dur = f4(total)
    claves = ";".join(f4(v / total) for v in tiempos)
    anim = f'begin="{INTRO}s" dur="{dur}s" repeatCount="indefinite" keyTimes="{claves}"'

    o: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="t d">',
        '<title id="t">Samuel Cleto Malle · perfil</title>',
        '<desc id="d">Retrato hecho de puntos que se transforma en los logos de las tecnologías que uso, junto a un panel profile.yml.</desc>',
        '<defs>',
        f'<filter id="sombra" x="-20%" y="-20%" width="140%" height="150%"><feDropShadow dx="0" dy="12" stdDeviation="16" flood-color="{t["sombra"]}" flood-opacity=".3"/></filter>',
        f'<clipPath id="marco"><rect x="{VX}" y="{VY}" width="{VW}" height="{VH}" rx="3"/></clipPath>',
        '</defs>',
        f'<rect width="{W}" height="{H}" rx="18" fill="{t["fondo"]}"/>',
        f'<rect x="13" y="13" width="1154" height="584" rx="13" fill="{t["panel"]}" stroke="{t["linea"]}" filter="url(#sombra)"/>',
        f'<path d="M13 62H1167" stroke="{t["linea"]}"/>',
        '<circle cx="38" cy="38" r="6" fill="#FF5F57"/><circle cx="59" cy="38" r="6" fill="#FEBC2E"/><circle cx="80" cy="38" r="6" fill="#28C840"/>',
        f'<text x="590" y="43" text-anchor="middle" fill="{t["suave"]}" font-family="{MONO}" font-size="13">samu@dev: ~ — nvim profile.yml</text>',
        # marco izquierdo
        f'<rect x="35" y="88" width="418" height="472" rx="6" fill="{t["panel2"]}" stroke="{t["linea"]}"/>',
        f'<path d="M35 124H453" stroke="{t["linea"]}"/>',
        f'<text x="49" y="111" fill="{t["cromo"]}" font-family="{MONO}" font-size="13" font-weight="700" letter-spacing="1.2">RETRATO.SYS</text>',
        f'<text x="438" y="111" text-anchor="end" fill="{t["suave"]}" font-family="{MONO}" font-size="11">{RW}×{RH} · 1-BIT</text>',
        f'<path d="M49 141h12M49 141v12M439 141h-12M439 141v12M49 539h12M49 539v-12M439 539h-12M439 539v-12" fill="none" stroke="{t["cromo"]}" opacity=".6"/>',
        '<g clip-path="url(#marco)" shape-rendering="crispEdges">',
        '<g>',
    ]

    # Retrato en bandas: se desvanece al empezar el primer logo y vuelve al final.
    centro_logo = destinos[0].mean(axis=0)
    bandas = rng.integers(0, 80, size=len(retrato))
    ruido = rng.normal(0, 4, size=(80, 2))
    for b in range(80):
        pts = retrato[bandas == b]
        if not len(pts):
            continue
        delta = (centro_logo - pts.mean(axis=0)) * 0.18 + ruido[b]
        pos = ["0 0", "0 0", f"{f1(delta[0])} {f1(delta[1])}", f"{f1(delta[0])} {f1(delta[1])}"]
        pos += ["0 0"] * (len(fotogramas) - len(pos))
        op = [".95", ".95", "0", "0"] + ["0"] * (len(fotogramas) - 5) + [".95"]
        o.append(
            f'<path d="{trazos(pts)}" fill="none" stroke="{t["puntos"]}" stroke-width="1" opacity=".95">'
            f'<animateTransform attributeName="transform" type="translate" {anim} calcMode="linear" values="{";".join(pos)}"/>'
            f'<animate attributeName="opacity" {anim} values="{";".join(op)}"/></path>'
        )

    # Viajeros: cuadraditos que van de la cara a cada logo.
    op_viajeros = ";".join(["0", "0"] + ["1"] * (len(fotogramas) - 3) + ["0"])
    for i in range(n):
        valores = ";".join(f"{f1(f[i, 0])} {f1(f[i, 1])}" for f in fotogramas)
        o.append(
            f'<path d="M-.65-.65h1.3v1.3h-1.3z" fill="{t["puntos"]}">'
            f'<animateTransform attributeName="transform" type="translate" {anim} calcMode="linear" values="{valores}"/>'
            f'<animate attributeName="opacity" {anim} calcMode="linear" values="{op_viajeros}"/></path>'
        )

    # Nube densa de cada logo mientras está quieto.
    for idx, pts in enumerate(logos.values()):
        vis = ["0"] * len(fotogramas)
        vis[idx * 2 + 2] = vis[idx * 2 + 3] = ".85"
        o.append(
            f'<path d="{particulas(muestrear(pts, rng, PUNTOS_LOGO))}" fill="none" stroke="{t["puntos"]}" stroke-width="1" opacity="0">'
            f'<animate attributeName="opacity" {anim} calcMode="linear" values="{";".join(vis)}"/></path>'
        )
    o.append("</g>")

    # Intro: la cara aparece a trozos aleatorios y luego cede el paso al bucle.
    grupos = rng.integers(0, 50, size=len(retrato))
    inicios = np.empty(50)
    inicios[rng.permutation(50)] = np.linspace(0.05, 1.2, 50)
    for g in range(50):
        pts = retrato[grupos == g]
        if not len(pts):
            continue
        o.append(
            f'<path d="{trazos(pts)}" fill="none" stroke="{t["puntos"]}" stroke-width="1" opacity="0">'
            f'<animate attributeName="opacity" begin="{f1(inicios[g])}s" dur=".8s" values="0;1" fill="freeze"/>'
            f'<animate attributeName="opacity" begin="{INTRO - 0.12:.2f}s" dur=".12s" values="1;0" fill="freeze"/></path>'
        )
    o.append("</g>")

    o += [
        f'<text x="58" y="551" fill="{t["suave"]}" font-family="{MONO}" font-size="10">PTS {len(retrato):05d} · {len(logos)} LOGOS · FLOYD-STEINBERG</text>',
        # panel derecho
        f'<rect x="474" y="88" width="672" height="472" rx="6" fill="{t["panel2"]}" stroke="{t["linea"]}"/>',
        f'<path d="M474 124H1146" stroke="{t["linea"]}"/>',
        f'<text x="490" y="111" fill="{t["cromo"]}" font-family="{MONO}" font-size="13" font-weight="700">profile.yml</text>',
        f'<text x="582" y="111" fill="{t["suave"]}" font-family="{MONO}" font-size="11">[YAML]</text>',
        f'<rect x="958" y="94" width="170" height="24" rx="12" fill="{t["cromo"]}" opacity=".15" stroke="{t["cromo"]}"/>',
        f'<text x="1043" y="111" text-anchor="middle" fill="{t["cromo"]}" font-family="{MONO}" font-size="13" font-weight="700">@SamuelCletoMalle</text>',
    ]

    y = 148.0
    for i, (sangria, clave, valor) in enumerate(FILAS_YAML, 1):
        if sangria == 0:
            contenido = f'<tspan fill="{t["cromo"]}" font-weight="700">{html.escape(clave)}:</tspan>'
            x = 525.0
        else:
            contenido = (f'<tspan fill="{t["puntos"]}">{html.escape(clave)}: </tspan>'
                         f'<tspan fill="{t["texto"]}">{html.escape(valor)}</tspan>')
            x = 542.0
        o.append(f'<text x="506" y="{f1(y)}" text-anchor="end" fill="{t["suave"]}" opacity=".5" font-family="{MONO}" font-size="13">{i:2d}</text>')
        o.append(f'<text x="{f1(x)}" y="{f1(y)}" font-family="{MONO}" font-size="13">{contenido}</text>')
        y += 21.5

    o += [
        f'<path d="M474 526H1146" stroke="{t["linea"]}"/>',
        f'<rect x="475" y="527" width="670" height="32" fill="{t["panel"]}"/>',
        f'<rect x="485" y="533" width="72" height="20" rx="3" fill="{t["puntos"]}"/>',
        f'<text x="521" y="547" text-anchor="middle" fill="{t["fondo"]}" font-family="{MONO}" font-size="11" font-weight="700">NORMAL</text>',
        f'<text x="569" y="547" fill="{t["texto"]}" font-family="{MONO}" font-size="12" font-weight="600">profile.yml</text>',
        f'<text x="740" y="547" fill="{t["suave"]}" font-family="{MONO}" font-size="11">[utf-8]</text>',
        f'<text x="1134" y="547" text-anchor="end" fill="{t["suave"]}" font-family="{MONO}" font-size="11">{len(FILAS_YAML)}L  100%  {len(FILAS_YAML)}:1</text>',
        "</svg>",
    ]
    return "".join(o)


def main() -> None:
    if not FOTO.exists():
        raise SystemExit(f"Falta la foto: {FOTO}")
    SALIDA.mkdir(parents=True, exist_ok=True)
    logos = cargar_logos()
    for i, tema in enumerate(TEMAS):
        rng = np.random.default_rng(SEMILLA + i)
        svg = render(tema, puntos_retrato(tema), logos, rng)
        ruta = SALIDA / f"banner-{tema}.svg"
        ruta.write_text(svg, encoding="utf-8")
        print(f"{ruta.relative_to(RAIZ)}: {ruta.stat().st_size / 1024:.0f} KiB")
    print("secuencia:", " → ".join(logos))


if __name__ == "__main__":
    main()
