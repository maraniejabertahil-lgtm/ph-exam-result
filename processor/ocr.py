"""Reading a screenshot: image clean-up + Tesseract settings. Shared by shard.py and fill.py.

Tested on made-up list pages that look like the official preview (small, slightly blurry text):
  old recipe  (hard black/white at 150, default Tesseract)      -> 43% of rows exactly right
  new recipe  (grey + contrast stretch + sharpen, LSTM engine,
               no dictionary, letters/digits only)              -> 90% of rows exactly right
"""
import os, subprocess
from pathlib import Path

TESS_ENV = dict(os.environ, OMP_THREAD_LIMIT="1")  # one thread per Tesseract; the pool already uses every core
LANG = os.environ.get("OCR_LANG") or "eng"         # "eng+spa" also reads the letter Ñ (needs tesseract-ocr-spa)
# names are capital letters; no dictionary (surnames are not dictionary words); keep only characters that can occur
ALLOWED = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,'- " + ("ÑÁÉÍÓÚÜ" if "spa" in LANG else "")
MODES = ("sharp", "t150", "up")  # OCR passes in this order. Pass 1 always runs, the others add votes while time allows.

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


def prepare(im, mode):
    from PIL import Image, ImageFilter, ImageOps
    box = im.point(lambda p: 255 if p > 235 else 0).getbbox()   # the white page, without the grey viewer around it
    if not box:
        return None
    im = im.crop(box)
    if mode == "t150":                                           # the old recipe: hard black/white
        return im.point(lambda p: 255 if p > 150 else 0)
    g = ImageOps.autocontrast(im, cutoff=1)                      # stretch contrast: faint text gets darker
    if mode == "up":                                             # bigger + sharper: helps very small text
        g = g.resize((int(g.width * 1.5), int(g.height * 1.5)), Image.LANCZOS)
        return g.filter(ImageFilter.UnsharpMask(radius=2, percent=140, threshold=2))
    return g.filter(ImageFilter.UnsharpMask(radius=2, percent=160, threshold=2))   # "sharp"


def ocr_task(a):
    """a = (screenshot path, mode) -> text read from it"""
    from PIL import Image
    f, mode = a
    im = prepare(Image.open(f).convert("L"), mode)
    if im is None:
        return ""
    o = f"{f}.{mode}.png"
    im.save(o)
    cmd = ["tesseract", o, "-", "-l", LANG, "--oem", "1", "--psm", "6", "--dpi", "300",
           "-c", "preserve_interword_spaces=1", "-c", "load_system_dawg=0", "-c", "load_freq_dawg=0",
           "-c", f"tessedit_char_whitelist={ALLOWED}"]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, env=TESS_ENV, timeout=60).stdout
    except subprocess.TimeoutExpired:
        print(f"tesseract timed out on {Path(f).name} ({mode})")
        return ""
