"""Study Tips page. Reads two plain-text files (English and Filipino) and shows them with a language switch."""
import html
import re
from pathlib import Path

E = html.escape
CONTENT = Path(__file__).resolve().parent / "content"
LANGS = [("en", "English", "study-tips-en.txt"), ("tl", "Filipino", "study-tips-tl.txt")]

CSS = """
.lang{display:flex;gap:8px;margin:8px 0 12px;flex-wrap:wrap}
.lang button{padding:8px 16px;border-radius:99px;border:1px solid var(--line);background:var(--card);color:var(--text);font:600 14px system-ui;cursor:pointer}
.lang button[aria-pressed="true"]{background:#2f6fe0;border-color:#2f6fe0;color:#fff}
.tip-body h2{font-size:1.2rem;margin:18px 0 6px}
.tip-body h3{font-size:1.05rem;margin:16px 0 4px}
.tip-body p{margin:0 0 10px;line-height:1.6}
.tip-body ul{margin:0 0 10px;padding-left:22px}
.tip-body[hidden]{display:none}
"""


def _heading(block):
    """Returns 'h2' for ALL-CAPS section titles, 'h3' for numbered tip titles, else None."""
    if "\n" in block:
        return None
    t = block.strip().rstrip("*").strip()
    if len(t) < 100 and re.fullmatch(r"[A-Z0-9 ,.:'()&\-–—!?]+", t) and re.search(r"[A-Z]", t):
        return "h2"
    if len(t) < 100 and re.match(r"^\d+\.\s", t) and not t.endswith("."):
        return "h3"
    return None


def _render(text):
    out = []
    for block in re.split(r"\n\s*\n", text.strip()):
        block = block.strip()
        if not block:
            continue
        # "* 3. HAVE A WORK PLAN" is a section title, not a bullet
        if re.match(r"^\* \d+\.\s", block):
            block = block[2:]
        lines = [l.strip() for l in block.split("\n") if l.strip()]
        h = _heading(block)
        if h:
            out.append(f"<{h}>{E(block.rstrip('*').strip())}</{h}>")
        elif all(l.startswith("* ") for l in lines):
            out.append("<ul>" + "".join(f"<li>{E(l[2:])}</li>" for l in lines) + "</ul>")
        else:
            out.append("<p>" + "<br>".join(E(l) for l in lines) + "</p>")
    return "\n".join(out)


def study_tips_page(head, FOOT):
    tabs, bodies = [], []
    for i, (code, label, fname) in enumerate(LANGS):
        f = CONTENT / fname
        text = f.read_text(encoding="utf-8") if f.exists() else "Content coming soon."
        tabs.append(f'<button type="button" data-lang="{code}" aria-pressed="{"true" if i == 0 else "false"}">{label}</button>')
        hidden = "" if i == 0 else " hidden"
        bodies.append(f'<section class="card tip-body" id="lang-{code}"{hidden}>{_render(text)}</section>')
    js = ("<script>document.querySelectorAll('.lang button').forEach(function(b){b.onclick=function(){"
          "document.querySelectorAll('.lang button').forEach(function(x){x.setAttribute('aria-pressed',x===b)});"
          "document.querySelectorAll('.tip-body').forEach(function(s){s.hidden=s.id!=='lang-'+b.dataset.lang});"
          "}});</script>")
    return (head("Study Tips – PH Exam Result", "Study tips for board examinations, in English and Filipino.", "study-tips/")
            + f'<style>{CSS}</style><h1>Study Tips</h1><div class="lang">{"".join(tabs)}</div>'
            + "".join(bodies) + js + FOOT)
