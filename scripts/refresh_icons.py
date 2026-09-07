"""Refresh the Kerfox and Axis icons shown in README.md from the live sites.

Pulls the icon each product actually ships (the same file a phone home screen
would get), then writes the light and dark tiles the README's <picture> tags
point at:

    assets/kerfox-light.png   fox on its cream tile, as shipped
    assets/kerfox-dark.png    same fox, tile swapped for a warm near-black
    assets/axis-light.svg     navy mark on its light tile, as shipped
    assets/axis-dark.svg      light mark on the navy tile

Runs weekly from .github/workflows/refresh-icons.yml and commits only when a
file changed. Fails soft: any fetch or parse problem leaves the existing files
in place and exits 0, so a site outage never breaks the README.
"""
from __future__ import annotations

import io
import sys
import urllib.request
from collections import deque
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"

SIZE = 256            # output tile size in px
RADIUS = 0.22         # corner radius as a fraction of SIZE, same as both apps' own icons

KERFOX_URL = "https://www.kerfox.app/apple-touch-icon.png"
KERFOX_DARK_TILE = (26, 21, 18)        # warm near-black, sits just above GitHub's dark canvas
KERFOX_TOLERANCE = 34                  # colour distance treated as "still the tile"

AXIS_URL = "https://aroundaxis.co.uk/icon.svg"
AXIS_SWAPS = {                         # light-tile colour -> dark-tile colour
    "#FBFBFD": "#0F2043",              # tile becomes navy
    "#0F2043": "#FBFBFD",              # mark becomes light
    "#74858F": "#8FA0AD",              # ring lifts a step so it still reads on navy
}


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "EivanKolchin-profile-readme icon refresh"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def rounded(img: Image.Image) -> Image.Image:
    """Resize to SIZE and clip to the app-icon corner radius, supersampled for clean edges."""
    img = img.convert("RGBA").resize((SIZE, SIZE), Image.LANCZOS)
    big = SIZE * 4
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, big - 1, big - 1], radius=int(big * RADIUS), fill=255)
    mask = mask.resize((SIZE, SIZE), Image.LANCZOS)
    out = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def retile(img: Image.Image, tile: tuple[int, int, int], tol: int) -> Image.Image:
    """Replace the background tile with `tile`, touching only pixels connected to the edges.

    A flood fill from the four corners finds the tile; anything enclosed by the
    artwork (the fox's cream chest, say) is never reached, so it survives intact.
    Edge pixels are blended by how close they are to the tile colour, which keeps
    the anti-aliased outline from leaving a halo.
    """
    img = img.convert("RGBA")
    w, h = img.size
    px = img.load()
    bg = px[0, 0][:3]

    def dist(c):
        return max(abs(c[0] - bg[0]), abs(c[1] - bg[1]), abs(c[2] - bg[2]))

    seen = bytearray(w * h)
    q = deque([(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)])
    wide = tol * 2  # pixels this far from the tile colour are still walked, so the fill reaches the outline
    while q:
        x, y = q.popleft()
        if x < 0 or y < 0 or x >= w or y >= h or seen[y * w + x]:
            continue
        if dist(px[x, y][:3]) > wide:
            continue
        seen[y * w + x] = 1
        q.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))

    out = img.copy()
    op = out.load()
    for y in range(h):
        for x in range(w):
            if not seen[y * w + x]:
                continue
            r, g, b, a = px[x, y]
            k = min(1.0, dist((r, g, b)) / wide)     # 0 = pure tile, 1 = pure artwork
            op[x, y] = (round(tile[0] * (1 - k) + r * k), round(tile[1] * (1 - k) + g * k), round(tile[2] * (1 - k) + b * k), a)
    return out


def kerfox() -> None:
    src = Image.open(io.BytesIO(fetch(KERFOX_URL)))
    if src.size[0] < 120:
        raise ValueError(f"Kerfox icon unexpectedly small: {src.size}")
    rounded(src).save(ASSETS / "kerfox-light.png", optimize=True)
    rounded(retile(src, KERFOX_DARK_TILE, KERFOX_TOLERANCE)).save(ASSETS / "kerfox-dark.png", optimize=True)
    print(f"kerfox: ok ({src.size[0]}px source)")


def axis() -> None:
    svg = fetch(AXIS_URL).decode("utf-8")
    missing = [c for c in AXIS_SWAPS if c not in svg]
    if missing:
        raise ValueError(f"Axis icon.svg no longer uses {missing}; dark variant left as is")
    dark = svg
    for i, (old, _) in enumerate(AXIS_SWAPS.items()):
        dark = dark.replace(old, f"@@{i}@@")
    for i, (_, new) in enumerate(AXIS_SWAPS.items()):
        dark = dark.replace(f"@@{i}@@", new)
    (ASSETS / "axis-light.svg").write_text(svg, encoding="utf-8")
    (ASSETS / "axis-dark.svg").write_text(dark, encoding="utf-8")
    print("axis: ok")


def main() -> int:
    ASSETS.mkdir(exist_ok=True)
    strict = "--strict" in sys.argv
    failed = False
    for job in (kerfox, axis):
        try:
            job()
        except Exception as e:  # noqa: BLE001 - fail soft on purpose
            failed = True
            print(f"{job.__name__}: skipped, {e}", file=sys.stderr)
    return 1 if (strict and failed) else 0


if __name__ == "__main__":
    sys.exit(main())
