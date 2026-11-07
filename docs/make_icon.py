"""Build the timetrace app icon: docs/icon.svg plus every PNG/icns the package ships.

    python docs/make_icon.py            # writes docs/icon.svg, docs/icon-small.svg and renders all sizes

The ring is drawn as four closed paths, not dashed strokes. A dashed stroke cuts each segment along
its own radius, so a gap is a wedge (wider outside than inside) and the two faces of a gap are not
parallel. Here every gap is a straight channel of constant width: both faces are offset by g/2 from
the same radius, and every corner gets a small fillet.

Rendering uses headless Google Chrome (no extra dependencies); icns via macOS `iconutil`.
"""
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
STATIC = ROOT / "src" / "timetrace" / "dashboard" / "static"
HELPER = ROOT / "src" / "timetrace" / "helper"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

C = 512.0
# create / grow / keep / leisure — the dashboard's evaluation colours (light palette)
COLORS = ["#2a78d6", "#1baf7a", "#eda100", "#e34948"]
# segment boundaries in clock hours: gaps sit on 12, 3, 5 and 8 o'clock
HOURS = [0, 3, 5, 8, 12]

FULL = dict(ro=298, ri=202, gap=28, corner=14, hand=28, minute=140, hour=96, hub=30, pin=10)
# 16–32 px: wider gaps and hands so the four segments still read as four
SMALL = dict(ro=318, ri=190, gap=56, corner=18, hand=52, minute=128, hour=86, hub=40, pin=0)


def _f(v):
    return f"{v:.2f}".rstrip("0").rstrip(".")


def _p(x, y):
    return f"{_f(C + x)} {_f(C + y)}"


def segment(a, b, ro, ri, gap, corner):
    """Closed path for the annular segment from angle a to b (radians, clockwise from 12 o'clock)."""
    h, rc = gap / 2, corner
    u = lambda t: (math.sin(t), -math.cos(t))       # radial unit vector
    ncw = lambda t: (math.cos(t), math.sin(t))      # clockwise tangent

    def corner_pts(t, n, r_circle, outer):
        # fillet circle: tangent to the face line (n·p = h) and to the ring edge
        d = r_circle - rc if outer else r_circle + rc
        along = math.sqrt(d * d - (h + rc) ** 2)
        c = ((h + rc) * n[0] + along * u(t)[0], (h + rc) * n[1] + along * u(t)[1])
        face = (c[0] - rc * n[0], c[1] - rc * n[1])
        edge = (c[0] * r_circle / d, c[1] * r_circle / d)
        return face, edge

    n1 = ncw(a)
    n2 = tuple(-v for v in ncw(b))
    f_o1, p_o1 = corner_pts(a, n1, ro, True)
    f_i1, p_i1 = corner_pts(a, n1, ri, False)
    f_o2, p_o2 = corner_pts(b, n2, ro, True)
    f_i2, p_i2 = corner_pts(b, n2, ri, False)
    large = 1 if (b - a) > math.pi else 0
    return (f"M{_p(*p_o1)} A{_f(ro)} {_f(ro)} 0 {large} 1 {_p(*p_o2)} "
            f"A{_f(rc)} {_f(rc)} 0 0 1 {_p(*f_o2)} L{_p(*f_i2)} "
            f"A{_f(rc)} {_f(rc)} 0 0 1 {_p(*p_i2)} A{_f(ri)} {_f(ri)} 0 {large} 0 {_p(*p_i1)} "
            f"A{_f(rc)} {_f(rc)} 0 0 1 {_p(*f_i1)} L{_p(*f_o1)} "
            f"A{_f(rc)} {_f(rc)} 0 0 1 {_p(*p_o1)} Z")


def svg(ro, ri, gap, corner, hand, minute, hour, hub, pin):
    segs = "\n".join(
        f'    <path fill="{col}" d="{segment(HOURS[i] * math.pi / 6, HOURS[i + 1] * math.pi / 6, ro, ri, gap, corner)}"/>'
        for i, col in enumerate(COLORS))
    pin_el = f'\n  <circle cx="512" cy="512" r="{_f(pin)}" fill="#1f1f22"/>' if pin else ""
    hx, hy = C + hour * math.sin(math.radians(120)), C - hour * math.cos(math.radians(120))  # 4 o'clock
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2a2a2e"/><stop offset="1" stop-color="#141416"/></linearGradient>
    <linearGradient id="rim" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".14"/><stop offset=".5" stop-color="#fff" stop-opacity="0"/></linearGradient>
  </defs>
  <rect x="100" y="100" width="824" height="824" rx="185.4" fill="url(#bg)"/>
  <rect x="101.5" y="101.5" width="821" height="821" rx="184" fill="none" stroke="url(#rim)" stroke-width="3"/>
  <g>
{segs}
  </g>
  <g stroke="#f2f1ee" stroke-width="{_f(hand)}" stroke-linecap="round">
    <line x1="512" y1="512" x2="512" y2="{_f(C - minute)}"/>
    <line x1="512" y1="512" x2="{_f(hx)}" y2="{_f(hy)}"/>
  </g>
  <circle cx="512" cy="512" r="{_f(hub)}" fill="#f2f1ee"/>{pin_el}
</svg>
"""


def render(svg_path, out_png, size, tmp):
    """Rasterise at 1024 with Chrome, then downscale with sips (Lanczos-quality, keeps alpha)."""
    big = tmp / (svg_path.stem + "-1024.png")
    if not big.exists():
        html = tmp / (svg_path.stem + ".html")
        html.write_text("<!doctype html><style>html,body{margin:0;background:transparent}svg{display:block}</style>"
                        + svg_path.read_text())
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                        f"--user-data-dir={tmp / 'chrome'}", "--default-background-color=00000000",
                        "--window-size=1024,1024", f"--screenshot={big}", html.as_uri()],
                       check=True, capture_output=True)
    shutil.copy2(big, out_png)
    if size != 1024:
        subprocess.run(["sips", "-z", str(size), str(size), str(out_png)], check=True, capture_output=True)


def main():
    full, small = DOCS / "icon.svg", DOCS / "icon-small.svg"
    full.write_text(svg(**FULL))
    small.write_text(svg(**SMALL))
    if "--svg-only" in sys.argv:
        return
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        iconset = tmp / "AppIcon.iconset"
        iconset.mkdir()
        for base in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                px = base * scale
                name = f"icon_{base}x{base}{'@2x' if scale == 2 else ''}.png"
                render(small if px <= 32 else full, iconset / name, px, tmp)
        subprocess.run(["iconutil", "-c", "icns", "-o", str(HELPER / "AppIcon.icns"), str(iconset)], check=True)
        render(full, STATIC / "icon-512.png", 512, tmp)
        render(full, STATIC / "apple-touch-icon.png", 180, tmp)
        render(small, STATIC / "favicon.png", 64, tmp)
    print("wrote", full.relative_to(ROOT), small.relative_to(ROOT), "AppIcon.icns, icon-512, apple-touch-icon, favicon")


if __name__ == "__main__":
    main()
