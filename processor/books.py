"""Academic book search page for /books/.
Uses the site's shared layout (shell in pages.py) so it matches Home, About and Contact.
The search runs in the visitor's browser using free public catalogs (Open Library and Google Books).
No keys, no accounts, nothing stored on the server."""
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
.note{color:var(--mu);font-size:13px;text-align:left;margin-top:16px}
"""

BOOKS_JS = """
const RES = document.getElementById("bres"), ST = document.getElementById("bstatus"), Q = document.getElementById("bq");
const LIMIT = 20;

function el(tag, text, cls) {
  const e = document.createElement(tag);
  if (text != null) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}

function fromOL(d) {
  const isbn13 = (d.isbn || []).find(x => x.length === 13) || null;
  const tags = d.ebook_access === "public" ? ["Free to read"]
             : d.ebook_access === "borrowable" ? ["Borrow on Open Library"] : [];
  return {
    title: d.title || "Untitled",
    authors: (d.author_name || []).join(", "),
    year: d.first_publish_year ? String(d.first_publish_year) : "",
    isbn13: isbn13,
    cover: d.cover_i ? "https://covers.openlibrary.org/b/id/" + d.cover_i + "-M.jpg" : "",
    link: d.key ? "https://openlibrary.org" + d.key : "https://openlibrary.org",
    source: "Open Library",
    tags: tags
  };
}

function fromGB(v) {
  const vi = v.volumeInfo || {}, ai = v.accessInfo || {};
  const i13 = (vi.industryIdentifiers || []).find(x => x.type === "ISBN_13");
  const thumb = (vi.imageLinks || {}).thumbnail || "";
  const tags = [];
  if (ai.publicDomain) tags.push("Public domain");
  else if (ai.viewability === "ALL_PAGES") tags.push("Full view");
  else if (ai.viewability === "PARTIAL") tags.push("Preview");
  return {
    title: vi.title || "Untitled",
    authors: (vi.authors || []).join(", "),
    year: (vi.publishedDate || "").slice(0, 4),
    isbn13: i13 ? i13.identifier : null,
    cover: thumb.replace(/^http:/, "https:"),
    link: vi.infoLink || ("https://books.google.com/books?id=" + v.id),
    source: "Google Books",
    tags: tags
  };
}

// Same ISBN-13 means the same book: merge and show both sources. Otherwise keep books separate.
function merge(list) {
  const seen = new Map(), out = [];
  for (const b of list) {
    if (b.isbn13 && seen.has(b.isbn13)) {
      const o = seen.get(b.isbn13);
      o.tags = [...new Set([...o.tags, ...b.tags])];
      o.sources.push(b.source);
      continue;
    }
    b.sources = [b.source];
    out.push(b);
    if (b.isbn13) seen.set(b.isbn13, b);
  }
  return out;
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
  const a = el("a", "Visit source →");
  a.href = b.link;
  a.target = "_blank";
  a.rel = "noopener";
  body.append(a);
  li.append(img, body);
  return li;
}

async function run(raw) {
  const q = (raw || "").trim();
  RES.replaceChildren();
  if (q.length < 2) { ST.textContent = "Please type at least 2 characters."; return; }
  if (q.length > 100) { ST.textContent = "Please use fewer than 100 characters."; return; }
  ST.textContent = "Searching…";
  const get = u => fetch(u).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); });
  const ol = "https://openlibrary.org/search.json?limit=" + LIMIT + "&q=" + encodeURIComponent(q);
  const gb = "https://www.googleapis.com/books/v1/volumes?printType=books&maxResults=" + LIMIT + "&q=" + encodeURIComponent(q);
  const results = await Promise.allSettled([get(ol), get(gb)]);
  const list = [], failed = [];
  if (results[0].status === "fulfilled") list.push(...(results[0].value.docs || []).map(fromOL));
  else failed.push("Open Library");
  if (results[1].status === "fulfilled") list.push(...(results[1].value.items || []).map(fromGB));
  else failed.push("Google Books");
  const books = merge(list);
  ST.textContent = books.length
    ? books.length + " result(s) for \\u201c" + q + "\\u201d"
    : "No books found for \\u201c" + q + "\\u201d. Try another word or spelling.";
  if (failed.length) ST.textContent += " (" + failed.join(" and ") + " did not respond.)";
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
        '<div id="bres"></div>'
        '<p class="note">Results come from public catalogs. "Preview", "Free to read", and "Public domain" '
        "labels appear only when the provider reports them. Check the source for current terms.</p>"
        f"<script>{BOOKS_JS}</script>"
    )
    return shell(
        head, FOOT,
        "Academic Book Search – PH Exam Result",
        "Search free academic books by title, author, ISBN, or subject.",
        "books/",
        "ACADEMIC LIBRARY",
        "Academic Book Search",
        "Search academic books from Open Library and Google Books. No account needed.",
        inner,
    )
