"""Static pages for PH Exam Result: Home (landing), About, Mission, Policies, Contact.
build.py passes in head() and FOOT so every page keeps the same header and footer."""
import html
from datetime import datetime

E = html.escape

ICON = {
    "about": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6"/><circle cx="12" cy="7.5" r=".8"/>',
    "target": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5"/>',
    "shield": '<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z"/><path d="m9 12 2 2 4-4"/>',
    "headset": '<path d="M4 14v-2a8 8 0 0 1 16 0v2"/><rect x="3" y="14" width="4" height="6" rx="1"/><rect x="17" y="14" width="4" height="6" rx="1"/>',
    "cap": '<path d="M2 9l10-5 10 5-10 5z"/><path d="M6 11v5c0 1.5 2.7 3 6 3s6-1.5 6-3v-5"/>',
}


def _icon(name):
    return (f'<span class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICON[name]}</svg></span>')


def _fb(CFG):
    url = CFG.get("facebook_url")
    return f'<a href="{E(url)}" rel="noopener" target="_blank">our Facebook Page</a>' if url else "our Facebook Page (coming soon)"


LANDING_CSS = """
.lp{text-align:center}
.eyebrow{color:#2f6fe0;font-weight:700;letter-spacing:.04em;font-size:14px;margin:6px 0 0}
.lp h1{margin:4px 0 2px;font-size:1.9rem;color:var(--text)}
.sub{color:var(--mu);margin:0 0 16px}
.btn{display:inline-block;background:#2f6fe0;color:#fff;padding:10px 18px;border-radius:10px;text-decoration:none;font-weight:700;margin-bottom:16px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.tile{display:block;background:var(--card);border:1px solid var(--line);border-radius:18px;padding:22px 14px;text-decoration:none;color:var(--text)}
.ic{display:inline-flex;align-items:center;justify-content:center;width:56px;height:56px;border-radius:16px;background:#eaf1ff;color:#2f6fe0;margin-bottom:10px}
.ic svg{width:26px;height:26px}
.tile h2{margin:0 0 6px;font-size:1.15rem;color:var(--text)}
.tile p{margin:0 0 8px;color:var(--mu);font-size:15px}
.go{color:#2f6fe0;font-weight:700;font-size:15px}
.brandcard{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:22px 16px;margin-top:14px;text-align:center}
.brandcard h2{margin:6px 0 4px;color:var(--text)}
.brandcard p{margin:0;color:var(--mu)}
.brandcard hr{border:0;border-top:1px solid var(--line);margin:16px 0 12px}
.copy{color:var(--mu);font-size:13px;margin:0}
@media(max-width:480px){.grid{grid-template-columns:1fr}}
"""


def landing_page(head, FOOT, CFG):
    tiles = [
        ("about", "About Us", "Discover who we are and what we do.", "Learn more", "/about/"),
        ("target", "Our Mission", "Our vision and educational purpose.", "Discover more", "/mission/"),
        ("shield", "Our Policies", "Privacy, terms, and website guidelines.", "Read policies", "/policies/"),
        ("headset", "Contact Us", "We're here to help and answer questions.", "Get in touch", "/contact/"),
    ]
    tile_html = "".join(
        f'<a class="tile" href="{href}">{_icon(ic)}<h2>{title}</h2><p>{desc}</p><span class="go">{cta} →</span></a>'
        for ic, title, desc, cta, href in tiles)
    body = (f'<style>{LANDING_CSS}</style><section class="lp">'
            '<p class="eyebrow">DISCOVER OUR PLATFORM</p>'
            '<h1>Everything You Need</h1>'
            '<p class="sub">Learn more about our services and commitment.</p>'
            '<a class="btn" href="/results/">View exam results</a>'
            f'<div class="grid">{tile_html}</div>'
            '<div class="brandcard">' + _icon("cap") + '<h2>PH Exam Result</h2>'
            '<p>Connecting students with the information they need.</p><hr>'
            f'<p class="copy">© {datetime.now().year} PH Exam Result. All rights reserved.</p></div>'
            '</section>')
    return head("PH Exam Result – Board Exam Results",
                "Official passer lists, schedules and information for PRC and CSC examinations.") + body + FOOT


def _card(inner):
    return f'<section class="card">{inner}</section>'


def static_pages(head, FOOT, CFG):
    email = E(CFG["contact_email"])
    fb = _fb(CFG)
    pages = {}

    pages["about/index.html"] = (
        head("About Us – PH Exam Result", "About PH Exam Result, an independent directory of Philippine examination results.", "about/")
        + '<h1>About Us</h1>'
        + _card(f"""
<p>PH Exam Result is an independent online directory that helps Filipino examinees, students, and professionals access and check PRC licensure examination results and CSC civil service examination results in the Philippines.</p>
<p>Our platform provides alphabetical lists of passers, board passing rates, topnotchers, and school performance summaries. We aim to make examination information accessible through a fast, clean, and mobile-friendly website.</p>
<p>PH Exam Result is not affiliated with, associated with, or officially connected to the Professional Regulation Commission (PRC), the Civil Service Commission (CSC), or any government agency. All official examination results, statistics, and announcements remain the property of their respective government agencies. Visitors are encouraged to verify their results and complete official requirements through government websites.</p>
<p>For questions, suggestions, name removal requests, or corrections, please contact us at {fb}.</p>
""")
        + FOOT)

    pages["mission/index.html"] = (
        head("Our Mission – PH Exam Result", "The mission and educational purpose of PH Exam Result.", "mission/")
        + '<h1>Our Mission</h1>'
        + _card("""
<p>PH Exam Result exists to make public licensure and civil service examination information easy to find. We publish official passer lists in alphabetical order, clearly labelled and kept up to date, so examinees can check their results quickly on any device.</p>
<p>Our goal is accuracy, speed, and respect for the people whose names appear on these lists. We want every examinee, student, and professional to have clear, reliable information when it matters most.</p>
""")
        + FOOT)

    pages["policies/index.html"] = (
        head("Our Policies – PH Exam Result", "Privacy policy and terms of service for PH Exam Result.", "policies/")
        + '<h1>Our Policies</h1>'
        + _card("""
<h2 id="privacy">Privacy Policy</h2>
<p>PH Exam Result respects the privacy of its visitors. This Privacy Policy explains how we collect, use, and protect information when visitors access our website.</p>
<p>We may collect non-personally identifiable information through standard log files and analytics tools, including IP addresses, browser types, internet service providers, dates and times of visits, referring pages, and website activity. This information helps us monitor website performance, understand visitor behavior, and improve our services.</p>
<p>Our website uses cookies to remember visitor preferences, improve browsing experiences, and customize website content. Third-party advertising partners, including Google AdSense, may also use cookies and web beacons to display relevant advertisements based on visitors' browsing activities.</p>
<p>Google may use advertising cookies, including technologies described in its advertising policies, to serve ads to visitors. Visitors can learn more about Google's advertising practices and manage their advertising preferences through <a href="https://policies.google.com/technologies/ads" rel="noopener" target="_blank">Google's official website</a>.</p>
<p>PH Exam Result's Privacy Policy does not cover third-party websites or advertising services. Visitors are encouraged to review the privacy policies of those third parties to understand their data collection and usage practices.</p>
<p>By accessing and using our website, visitors acknowledge and agree to this Privacy Policy.</p>
<p>For questions or concerns regarding this Privacy Policy, please contact us at {fb}.</p>
""".replace("{fb}", fb))
        + _card("""
<h2 id="terms">Terms of Service</h2>
<p>By accessing and using PH Exam Result, visitors agree to comply with these Terms of Service.</p>
<p>All examination results, passing rates, schedules, announcements, and educational guides published on this website are provided strictly for general informational purposes. Although we make reasonable efforts to ensure accuracy and provide updated information, we do not guarantee that all published content is complete, accurate, or free from errors or delays.</p>
<p>Visitors are strongly encouraged to verify examination results, official ratings, schedules, and other important information directly through the Professional Regulation Commission (PRC) at <a href="https://online.prc.gov.ph" rel="noopener" target="_blank">online.prc.gov.ph</a> or the Civil Service Commission (CSC) at <a href="https://csc.gov.ph" rel="noopener" target="_blank">csc.gov.ph</a>.</p>
<p>Official examination results and lists of passers are public records issued by the respective Philippine government agencies. However, original articles, editorial content, statistical summaries, website design, and other original materials published on PH Exam Result belong to this website.</p>
<p>PH Exam Result shall not be held responsible for any losses, damages, errors, omissions, or delays resulting from the use of information published on this website. Visitors use the information provided at their own discretion and responsibility.</p>
""")
        + FOOT)

    pages["contact/index.html"] = (
        head("Contact Us – PH Exam Result", "Contact PH Exam Result for questions, corrections, or name removal requests.", "contact/")
        + '<h1>Contact Us</h1>'
        + _card(f"""
<p>PH Exam Result welcomes questions, suggestions, feedback, and reports regarding examination results and published information. If you find an error, need clarification, or wish to request the correction or removal of a published name, please contact us directly via Facebook at {fb}.</p>
<p>For name removal or correction requests, please include your full name as published, the examination name and date, and the URL of the page where your name appears. This information will help us identify and review your request promptly.</p>
<p>Email: <a href="mailto:{email}">{email}</a></p>
<p>We appreciate your feedback and are committed to maintaining accurate, reliable, and accessible examination information for our visitors.</p>
""")
        + FOOT)

    return pages

# ---- Shared shell: the Home page look, reused by Upcoming Release and Exam Results ----
ICON.update({
    "list": '<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r="1"/><circle cx="4.5" cy="12" r="1"/><circle cx="4.5" cy="18" r="1"/>',
    "star": '<path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/>',
    "school": '<path d="M3 10l9-5 9 5-9 5z"/><path d="M7 12v5c0 1 2.2 2.5 5 2.5s5-1.5 5-2.5v-5"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
})

TABLE_CSS = """
.tablecard{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:8px 16px;margin-top:14px;text-align:left}
.tablecard table{width:100%;border-collapse:collapse}
.tablecard th,.tablecard td{padding:10px 6px;border-bottom:1px solid var(--line);text-align:left;font-size:15px}
.tablecard th{color:var(--mu);font-weight:600}
.tablecard tr:last-child td{border-bottom:none}
"""


def tile(icon, title, desc, cta="", href=None):
    inner = (f'{_icon(icon)}<h2>{E(title)}</h2><p>{E(desc)}</p>'
             + (f'<span class="go">{E(cta)} →</span>' if cta else ""))
    return f'<a class="tile" href="{E(href)}">{inner}</a>' if href else f'<div class="tile">{inner}</div>'


def shell(head, FOOT, title, desc, path, eyebrow, heading, sub, inner, extra_css="", main_page=False):
    """main_page=True: no eyebrow, no brand card (Upcoming Release and Exam Results main pages)."""
    eyebrow_html = "" if main_page else f'<p class="eyebrow">{E(eyebrow)}</p>'
    card_html = "" if main_page else (
        '<div class="brandcard">' + _icon("cap") + '<h2>PH Exam Result</h2>'
        '<p>Connecting students with the information they need.</p><hr>'
        f'<p class="copy">© {datetime.now().year} PH Exam Result. All rights reserved.</p></div>')
    body = (f'<style>{LANDING_CSS}{extra_css}</style><section class="lp">'
            f'{eyebrow_html}<h1>{E(heading)}</h1><p class="sub">{E(sub)}</p>'
            f'{inner}{card_html}</section>')
    return head(title, desc, path) + body + FOOT
