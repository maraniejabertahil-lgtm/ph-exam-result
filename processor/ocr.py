"""Reading a screenshot: image clean-up + Tesseract settings. Shared by shard.py and fill.py.

Tested on made-up list pages that look like the official preview (small, slightly blurry text):
  old recipe  (hard black/white at 150, default Tesseract)      -> 43% of rows exactly right
  new recipe  (grey + contrast stretch + sharpen, LSTM engine,
               no dictionary, letters/digits only)              -> 90% of rows exactly right
"""
import os, subprocess
from pathlib import Path

TESS_ENV = dict(os.environ, OMP_THREAD_LIMIT="1")  # one thread per Tesseract; the pool already uses every core


def _detect_lang():
    if os.environ.get("OCR_LANG"):
        return os.environ["OCR_LANG"]
    try:
        out = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, timeout=5).stdout
        if "spa" in {line.strip() for line in out.splitlines()}:
            return "eng+spa"
    except Exception:
        pass
    return "eng"


LANG = _detect_lang()
# names are capital letters; no dictionary (surnames are not dictionary words); keep only characters that can occur
ALLOWED = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,'- " + ("ÑÁÉÍÓÚÜ" if "spa" in LANG else "")
MODES = ("up", "norm", "otsu")  # OCR passes in this order. Pass 1 always runs, the others add votes while time allows.

FIND = """() => { let b=null,m=0; for (const e of document.querySelectorAll('*')) {
  if (!/(auto|scroll)/.test(getComputedStyle(e).overflowY)) continue;
  if (e.scrollHeight > e.clientHeight+200 && e.scrollHeight > m) { m=e.scrollHeight; b=e; } }
  if (!b && document.scrollingElement && document.scrollingElement.scrollHeight > window.innerHeight+200) b=document.scrollingElement;
  if (!b) return null; window.__sc=b; return {h:b.scrollHeight, c:b.clientHeight}; }"""


def launch(p):
    """The runner's own Google Chrome when present (no download); else Playwright's Chromium."""
    try:
        return p.chromium.launch(channel="chrome")
    except Exception:
        return p.chromium.launch()


def _scale_factor(im):
    scale = 2.0 if im.width < 1400 else (1.5 if im.width < 2400 else 1.0)
    if im.width * im.height * scale * scale > 20_000_000:
        scale = min(scale, (20_000_000 / max(1, im.width * im.height)) ** 0.5)
    return max(1.0, scale)


def _stretch_contrast(im):
    hist = im.histogram()
    total = sum(hist)
    lo_target = max(1, int(total * 0.0005))
    hi_target = max(1, int(total * 0.005))
    acc, lo = 0, 0
    for i, c in enumerate(hist):
        acc += c
        if acc >= lo_target:
            lo = i
            break
    acc, hi = 0, 255
    for i in range(255, -1, -1):
        acc += hist[i]
        if acc >= hi_target:
            hi = i
            break
    if hi <= lo + 20:  # sparse page (e.g. last page with few rows): fall back to actual extrema
        lo = next((i for i, c in enumerate(hist) if c > 0), 0)
        hi = next((i for i in range(255, -1, -1) if hist[i] > 0), 255)
    if hi <= lo:
        return im
    s = 255.0 / (hi - lo)
    return im.point(lambda p: 0 if p <= lo else (255 if p >= hi else int((p - lo) * s + 0.5)))


def _remove_bg(im):
    from PIL import Image, ImageChops, ImageFilter, ImageOps
    small = im.resize((max(1, im.width // 4), max(1, im.height // 4)), Image.BILINEAR)
    bg = small.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(2))
    bg = bg.resize(im.size, Image.BILINEAR)
    return ImageOps.invert(ImageChops.subtract(bg, im))


def _otsu(im):
    hist = im.histogram()
    total = sum(hist)
    sum_total = sum(i * h for i, h in enumerate(hist))
    sum_bg, w_bg, max_var, thresh = 0, 0, -1.0, 150
    for t in range(256):
        w_bg += hist[t]
        if w_bg == 0:
            continue
        w_fg = total - w_bg
        if w_fg == 0:
            break
        sum_bg += t * hist[t]
        m_bg = sum_bg / w_bg
        m_fg = (sum_total - sum_bg) / w_fg
        var = w_bg * w_fg * (m_bg - m_fg) ** 2
        if var > max_var:
            max_var, thresh = var, t
    return thresh


def prepare(im, mode):
    from PIL import Image, ImageFilter, ImageOps
    box = im.point(lambda p: 255 if p > 235 else 0).getbbox()   # the white page, without the grey viewer around it
    if not box:
        return None
    im = im.crop(box)
    if mode == "t150":                                           # legacy fallback mode
        return ImageOps.expand(im.point(lambda p: 255 if p > 150 else 0), border=24, fill=255)
    if mode in ("norm", "otsu"):
        im = _remove_bg(im)
    scale = _scale_factor(im)
    if scale > 1.05:
        im = im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS)
    g = _stretch_contrast(im)
    if mode == "otsu":
        g = g.filter(ImageFilter.UnsharpMask(radius=1.5, percent=120, threshold=2))
        th = _otsu(g)
        g = g.point(lambda p: 255 if p > th else 0)
    elif mode == "sharp":
        g = g.filter(ImageFilter.UnsharpMask(radius=2, percent=160, threshold=2))
    else:                                                        # "up" or "norm"
        g = g.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=2))
    return ImageOps.expand(g, border=24, fill=255)


def ocr_task(a):
    """a = (screenshot path, mode) -> text read from it"""
    from PIL import Image
    f, mode = a
    with Image.open(f) as src:
        im = prepare(src.convert("L"), mode)
    if im is None:
        return ""
    o = f"{f}.{mode}.png"
    im.save(o, compress_level=1)
    cmd = ["tesseract", o, "-", "-l", LANG, "--oem", "1", "--psm", os.environ.get("OCR_PSM") or "6", "--dpi", "300",
           "-c", "preserve_interword_spaces=1", "-c", "load_system_dawg=0", "-c", "load_freq_dawg=0",
           "-c", "tessedit_do_invert=0", f"-c", f"tessedit_char_whitelist={ALLOWED}"]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, env=TESS_ENV, timeout=60).stdout
    except subprocess.TimeoutExpired:
        print(f"tesseract timed out on {Path(f).name} ({mode})")
        return ""
