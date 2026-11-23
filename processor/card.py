"""Headline picture (1200 x 630) for a "results expected" Facebook post.

    python card.py ABELE November 2026 "Agricultural and Biosystems Engineer Licensure Exam" card.png

Layout (same idea as the PRC Board News example, but with this site's own name and colors):
    PH EXAM RESULT mark (top left)
    BIG HEADLINE        e.g. "ABELE RESULTS"
    month year + full exam name, stretched to the same width as the headline
    site address (bottom)

Fonts: the tall headline font is Anton (free, SIL Open Font License). The first font file found in this list is used:
    processor/fonts/Anton-Regular.ttf   <- put the file here so it works on GitHub
    the system copy of Anton, then Liberation Sans Narrow Bold, then DejaVu Sans Condensed Bold
Nothing breaks if Anton is missing; the picture just looks a little different."""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
W, H = 1200, 630
MARGIN = 70
NAVY = (22, 41, 84)
BLUE = (31, 94, 168)
GREY = (96, 105, 120)
WHITE = (255, 255, 255)

HEADLINE_FONTS = [
    HERE / "fonts" / "Anton-Regular.ttf",
    "/usr/share/fonts/truetype/google-fonts/ofl/anton/Anton-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSansNarrow-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
]
SUBLINE_FONTS = [
    "/usr/share/fonts/truetype/liberation/LiberationSansNarrow-Bold.ttf",
    HERE / "fonts" / "Anton-Regular.ttf",
    "/usr/share/fonts/truetype/google-fonts/ofl/anton/Anton-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
]
TEXT_FONTS = [
    "/usr/share/fonts/truetype/liberation/LiberationSansNarrow-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
]


def font_path(candidates):
    for c in candidates:
        if Path(c).exists():
            return str(c)
    return None


def load(candidates, size):
    path = font_path(candidates)
    return ImageFont.truetype(path, size) if path else ImageFont.load_default()


def text_w(font, text):
    box = font.getbbox(text)
    return box[2] - box[0]


def fit(candidates, text, max_w, max_size, min_size=14):
    """The biggest font (up to max_size) whose text is not wider than max_w."""
    size = max_size
    while size > min_size:
        f = load(candidates, size)
        if text_w(f, text) <= max_w:
            return f
        size -= 2
    return load(candidates, min_size)


def wrap(candidates, text, max_w, size, max_lines=2):
    """Break text into at most max_lines lines no wider than max_w (shrinks the font if it still does not fit)."""
    while size >= 14:
        f = load(candidates, size)
        lines, cur = [], ""
        for word in text.split():
            trial = (cur + " " + word).strip()
            if text_w(f, trial) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
        if len(lines) <= max_lines and all(text_w(f, ln) <= max_w for ln in lines):
            return f, lines
        size -= 2
    f = load(candidates, 14)
    return f, [text]


def draw_mark(d, x, y, brand="PH EXAM RESULT"):
    """Small "PH / EXAM RESULT" mark, like the Page picture."""
    d.rounded_rectangle([x, y, x + 74, y + 74], radius=16, fill=NAVY)
    d.text((x + 37, y + 30), "PH", font=load(HEADLINE_FONTS, 40), fill=WHITE, anchor="mm")
    d.text((x + 37, y + 58), "EXAM RESULT", font=load(TEXT_FONTS, 11), fill=WHITE, anchor="mm")
    d.text((x + 92, y + 37), brand.upper(), font=load(HEADLINE_FONTS, 34), fill=NAVY, anchor="lm")


def draw_globe(d, cx, cy, r, color):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=3)
    d.ellipse([cx - r * 0.45, cy - r, cx + r * 0.45, cy + r], outline=color, width=2)
    d.line([cx - r, cy, cx + r, cy], fill=color, width=2)
    d.line([cx, cy - r, cx, cy + r], fill=color, width=2)


def make_card_lines(headline, subtitle, out_path, site="ph-exam-result.pages.dev", brand="PH EXAM RESULT"):
    """headline = the big line (e.g. "ABELE RESULTS"); subtitle = month, year and full exam name."""
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    # thin color bar at the top, so the picture is recognisable in the feed
    d.rectangle([0, 0, W, 12], fill=BLUE)
    draw_mark(d, MARGIN, 44, brand)

    headline = headline.upper()
    box_w = W - 2 * MARGIN
    hf = fit(HEADLINE_FONTS, headline, box_w, 300, 80)
    hb = hf.getbbox(headline)
    head_h = hb[3] - hb[1]
    head_w = hb[2] - hb[0]
    top = 168
    d.text((MARGIN - hb[0], top - hb[1]), headline, font=hf, fill=NAVY)

    # the second line is stretched to the same width as the headline (up to a sensible size), wrapping if very long
    sf, lines = wrap(SUBLINE_FONTS, subtitle.upper(), head_w, 64, max_lines=2)
    y = top + head_h + 36
    for ln in lines:
        b = sf.getbbox(ln)
        d.text((MARGIN - b[0], y - b[1]), ln, font=sf, fill=NAVY)
        y += (b[3] - b[1]) + 14

    # footer
    fy = H - 62
    draw_globe(d, MARGIN + 16, fy + 16, 16, NAVY)
    d.text((MARGIN + 44, fy + 16), site, font=load(TEXT_FONTS, 30), fill=NAVY, anchor="lm")
    d.rectangle([0, H - 12, W, H], fill=BLUE)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG", optimize=True)
    return out_path


def make_card(abbr, month, year, exam_full, out_path, site="ph-exam-result.pages.dev"):
    return make_card_lines(f"{abbr} RESULTS", f"{month} {year} {exam_full}", out_path, site)


if __name__ == "__main__":
    if len(sys.argv) < 6:
        sys.exit('usage: python card.py ABBR Month Year "Full exam name" out.png')
    print(make_card(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]))
