"""Academic book search page for /books/.
Uses the site's shared layout (shell in pages.py) so it matches Home, About and Contact.
Search runs in the visitor's browser using two free public sources:
the Internet Archive (embedded reader on this page) and the OAPEN Library (open-access books, linked to source).
No keys, no accounts, nothing stored on the server. Books are never copied or downloaded by this site."""
from pages import shell

SUBJECTS = ["Health Sciences", "Engineering", "Computer Science", "Mathematics", "Natural Sciences",
            "Education", "Business and Accountancy", "Social Sciences", "Humanities", "Law",
            "Agriculture", "General Academic"]

PAGE_CSS = """
.sr{position:absolute;left:-9999px}
.mu{color:var(--mu);font-size:14px}
.bsearch{display:flex;gap:8px;margin:12px 0}
.bsearch input{flex:1;min-width:0}
.bsearch button{padding:10px 16px;border:0;border-radius:10px;background:#2f6fe0;color:#fff;font-weight:700;cursor:pointer}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
.chips button{border:1px solid var(--line);background:var(--card);color:var(--text);border-radius:99px;padding:5px 12px;cursor:pointer;font:600 13px system-ui}
.chips button:hover{border-color:#2f6fe0}
.bk{display:flex;gap:12px;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px;margin:10px 0;text-align:left}
.bk img,.bkph{width:60px;height:90px;object-fit:cover;border-radius:6px;background:var(--line);flex:0 0 auto}
.bk h3{margin:0 0 2px;font-size:1rem;color:var(--text)}
.bk p{margin:2px 0;color:var(--mu);font-size:14px}
.tag{display:inline-block;font-size:12px;border-radius:99px;padding:2px 8px;background:var(--gbg);color:var(--g2);margin:0 4px 4px 0}
.actions{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin-top:6px}
.actions button{padding:6px 12px;border:0;border-radius:8px;background:#2f6fe0;color:#fff;font-weight:700;cursor:pointer;font-size:14px}
.actions a{font-size:14px}
#reader{margin:12px 0;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:10px}
#reader .rhead{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:8px}
#reader .rhead strong{font-size:15px;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#reader .rhead button{padding:6px 12px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--text);cursor:pointer;font:600 13px system-ui;flex:0 0 auto}
#reader iframe{width:100%;height:70vh;min-height:420px;border:0;border-radius:8px;background:var(--bg)}
#reader .rsrc{font-size:13px;color:var(--mu);margin:8px 0 0}
.note{color:var(--mu);font-size:13px;text-align:left;margin-top:16px}
"""

BOOKS_JS = """
const RES = document.getElementById("bres"), ST = document.getElementById("bstatus"), Q = document.getElementById("bq");
const READER = document.getElementById("reader");
const LIMIT = 20;

function el(tag, text, cls) {
  const e = document.createElement(tag);
  if (text != null) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}

function fromIA(d) {
  const creator = Array.isArray(d.creator) ? d.creator.join(", ") : (d.creator || "");
  return {
    title: d.title || "Untitled",
    authors: creator,
    year: d.year ? String(d.year) : "",
    isbn13: null,
    cover: d.identifier ? "https://archive.org/services/img/" + encodeURIComponent(d.identifier) : "",
    link: d.identifier ? "https://archive.org/details/" + encodeURIComponent(d.identifier) : "https://archive.org",
    embed: d.identifier ? "https://archive.org/embed/" + encodeURIComponent(d.identifier) : "",
    source: "Internet Archive",
    tags: []
  };
}

function meta(item, key) {
  const m = (item.metadata || []).filter(x => x.key === key).map(x => x.value).filter(Boolean);
  return m;
}

function fromOAPEN(item) {
  const isbn = meta(item, "dc.identifier.isbn")[0] || "";
  const digits = isbn.replace(/[^0-9Xx]/g, "");
  const issued = meta(item, "dc.date.issued")[0] || "";
  return {
    title: meta(item, "dc.title")[0] || item.name || "Untitled",
    authors: meta(item, "dc.contributor.author").join(", "),
    year: issued.slice(0, 4),
    isbn13: digits.length === 13 ? digits : null,
    cover: "",
    link: item.handle ? "https://library.oapen.org/handle/" + item.handle : "https://library.oapen.org",
    embed: "",
    source: "OAPEN Library",
    tags: ["Open access"]
  };
}

// Same ISBN-13 means the same book: merge and show every source. Otherwise keep books separate.
function merge(list) {
  const seen = new Map(), out = [];
  for (const b of list) {
    if (b.isbn13 && seen.has(b.isbn13)) {
      const o = seen.get(b.isbn13);
      o.tags = [...new Set([...o.tags, ...b.tags])];
      o.sources.push(b.source);
      if (!o.embed && b.embed) o.embed = b.embed;
      continue;
    }
    b.sources = [b.source];
    out.push(b);
    if (b.isbn13) seen.set(b.isbn13, b);
  }
  return out;
}

function openReader(b) {
  READER.replaceChildren();
  READER.hidden = false;
  const head = el("div", null, "rhead");
  head.append(el("strong", b.title));
  const close = el("button", "Close reader");
  close.type = "button";
  close.onclick = () => { READER.replaceChildren(); READER.hidden = true; };
  head.append(close);
  const frame = el("iframe");
  frame.src = b.embed;
  frame.title = "Reader: " + b.title;
  frame.loading = "lazy";
  frame.allowFullscreen = true;
  READER.append(head, frame, el("p", "Shown from " + b.sources.join(" & ") + ". The Internet Archive controls what can be viewed.", "rsrc"));
  READER.scrollIntoView({ behavior: "smooth", block: "start" });
}

function card(b) {
  const li = el("article", null, "bk");
  let img;
  if (b.cover) {
    img = el("img");
    img.src = b.cover;
    img.alt = "Cover of " + b.title;
    img.loading = "lazy";
    img.onerror = () => img.replaceWith(el("div", null, "bkph"));
  } else {
    img = el("div", null, "bkph");
  }
  const body = el("div");
  body.append(el("h3", b.title));
  body.append(el("p", [b.authors, b.year].filter(Boolean).join(" · ") || "Author unknown"));
  const tags = el("p");
  for (const t of b.tags) tags.append(el("span", t, "tag"));
  tags.append(el("span", "From " + b.sources.join(" & "), "tag"));
  body.append(tags);
  const actions = el("div", null, "actions");
  if (b.embed) {
    const read = el("button", "Read here");
    read.type = "button";
    read.onclick = () => openReader(b);
    actions.append(read);
  }
  const src = el("a", b.embed ? "Source →" : "Open book →");
  src.href = b.link;
  src.target = "_blank";
  src.rel = "noopener";
  actions.append(src);
  body.append(actions);
  li.append(img, body);
  return li;
}

async function run(raw) {
  const q = (raw || "").trim();
  RES.replaceChildren();
  READER.replaceChildren();
  READER.hidden = true;
  if (q.length < 2) { ST.textContent = "Please type at least 2 characters."; return; }
  if (q.length > 100) { ST.textContent = "Please use fewer than 100 characters."; return; }
  ST.textContent = "Searching…";
  const enc = encodeURIComponent(q);
  const ia = "https://archive.org/advancedsearch.php?q=" + encodeURIComponent("(" + q + ") AND mediatype:texts")
           + "&fl[]=identifier&fl[]=title&fl[]=creator&fl[]=year&rows=" + LIMIT + "&page=1&output=json";
  const oa = "https://library.oapen.org/rest/search?query=" + enc + "&expand=metadata&limit=" + LIMIT;
  const get = (u, json) => fetch(u, json ? { headers: { Accept: "application/json" } } : undefined)
    .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); });
  const results = await Promise.allSettled([get(ia), get(oa, true)]);
  const list = [], failed = [];
  if (results[0].status === "fulfilled") list.push(...((results[0].value.response || {}).docs || []).map(fromIA));
  else failed.push("Internet Archive");
  if (results[1].status === "fulfilled") list.push(...(Array.isArray(results[1].value) ? results[1].value : []).map(fromOAPEN));
  else failed.push("OAPEN Library");
  const books = merge(list);
  ST.textContent = books.length
    ? books.length + " result(s) for \\u201c" + q + "\\u201d"
    : "No books found for \\u201c" + q + "\\u201d. Try another word or spelling.";
  if (failed.length) ST.textContent += " (" + failed.join(", ") + " did not respond.)";
  RES.replaceChildren(...books.map(card));
}

document.getElementById("bf").addEventListener("submit", e => { e.preventDefault(); run(Q.value); });
document.querySelectorAll(".subj").forEach(btn => btn.addEventListener("click", () => {
  Q.value = btn.dataset.q;
  run(btn.dataset.q);
}));
"""


def books_page(head, FOOT):
    chips = "".join(f'<button type="button" class="subj" data-q="{s}">{s}</button>' for s in SUBJECTS)
    inner = (
        f"<style>{PAGE_CSS}</style>"
        '<form class="bsearch" id="bf" role="search">'
        '<label for="bq" class="sr">Search books, authors, ISBN, or subjects</label>'
        '<input id="bq" type="search" placeholder="Search books, authors, ISBN, or subjects…" autocomplete="off">'
        '<button type="submit">Search Books</button>'
        "</form>"
        f'<div class="chips" aria-label="Subjects">{chips}</div>'
        '<p class="mu" id="bstatus" role="status" aria-live="polite"></p>'
        '<div id="reader" hidden></div>'
        '<div id="bres"></div>'
        '<p class="note">Results come from the Internet Archive and the OAPEN Library. '
        '"Read here" opens the Internet Archive\'s reader on this page. "Open book" takes you to the OAPEN Library. '
        'Check each source for its current terms.</p>'
        f"<script>{BOOKS_JS}</script>"
    )
    return shell(
        head, FOOT,
        "Academic Book Search – PH Exam Result",
        "Search free academic books by title, author, ISBN, or subject, and read embedded copies here.",
        "books/",
        "ACADEMIC LIBRARY",
        "Academic Book Search",
        "Search academic books from the Internet Archive and the OAPEN Library. No account needed.",
        inner,
    )
