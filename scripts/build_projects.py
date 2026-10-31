#!/usr/bin/env python3
"""Keep the amaris ct studio site's project gallery and studio log up to date.

The GitHub Actions workflow .github/workflows/add-new-projects.yml runs this
every 30 minutes. It can also be run by hand:

  python3 scripts/build_projects.py                 re-render from data/ (no network)
  python3 scripts/build_projects.py --fetch         also look on GitHub for new projects
  python3 scripts/build_projects.py --covers        also draw covers for new projects with no share image

What counts as a new project: a public repo on the account that isn't a fork,
isn't archived, has at least one commit, isn't already listed in
data/projects.json ("projects" or "not_shown"), and has either a description
or a live website. New projects are added to the gallery and to the studio log.
Their picture is the site's own share image (og:image); without one, a cover is
drawn from the project's icon, name, tagline and theme color. Never a screenshot.

Files:
  data/projects.json   the gallery: curated entries, auto-added entries, and repos to leave off
  data/repos.json      what GitHub reported about each public repo (written by --fetch)
  data/log.json        the studio log, newest first
  assets/projects/     pictures and icons for projects
"""

import argparse
import datetime as dt
import html
import io
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECTS_FILE = ROOT / "data" / "projects.json"
REPOS_FILE = ROOT / "data" / "repos.json"
LOG_FILE = ROOT / "data" / "log.json"
ASSETS = ROOT / "assets" / "projects"
INDEX = ROOT / "index.html"
SITEMAP = ROOT / "sitemap.xml"
STUDIO_URL = "https://amarisct.github.io/Amaris/"
USER_AGENT = "amaris-ct-studio-site (+https://amarisct.github.io/Amaris/)"
RECENT_LOG_ENTRIES = 6

try:
    from PIL import Image
except ImportError:  # pictures are optional; the gallery still renders
    Image = None


# ---------------------------------------------------------------- files

def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def save_json(path, data):
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return True
    return False


def write_if_changed(path, text):
    if path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")
        return True
    return False


# ---------------------------------------------------------------- network

def http_get(url, accept="*/*", token=None, limit=12_000_000):
    headers = {"User-Agent": USER_AGENT, "Accept": accept}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=25) as resp:
        body = resp.read(limit + 1)
        if len(body) > limit:
            raise ValueError(f"{url} is larger than {limit} bytes")
        return resp.status, resp.geturl(), resp.headers.get("Content-Type", ""), body


def github_repos(owner, token):
    """All repos GitHub lists publicly for the account."""
    repos, page = [], 1
    while True:
        url = f"https://api.github.com/users/{owner}/repos?type=owner&per_page=100&page={page}"
        _, _, _, body = http_get(url, "application/vnd.github+json", token)
        batch = json.loads(body)
        repos.extend(batch)
        if len(batch) < 100:
            return repos
        page += 1


class PageInfo(HTMLParser):
    """Reads a page's title, description, share image and app icon."""

    def __init__(self):
        super().__init__()
        self.meta, self.icons, self.title, self._in_title = {}, [], "", False

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key and "content" in a and key not in self.meta:
                self.meta[key] = a["content"].strip()
        elif tag == "link":
            rel = a.get("rel", "").lower()
            if "apple-touch-icon" in rel or ("icon" in rel and a.get("href", "").lower().endswith(".png")):
                self.icons.append((0 if "apple" in rel else 1, a.get("href", "")))
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def site_info(url):
    """What a project's website says about itself, or None if it isn't up."""
    try:
        status, final, ctype, body = http_get(url, "text/html", limit=3_000_000)
    except (urllib.error.URLError, ValueError, TimeoutError, OSError):
        return None
    if status != 200 or "html" not in ctype.lower():
        return None
    page = PageInfo()
    page.feed(body.decode("utf-8", "replace"))
    m = page.meta
    absolute = lambda u: urllib.parse.urljoin(final, u) if u else ""
    icon = sorted(page.icons)[0][1] if page.icons else ""
    return {
        "title": m.get("og:title") or page.title.strip(),
        "description": m.get("og:description") or m.get("description", ""),
        "image": absolute(m.get("og:image", "")),
        "icon": absolute(icon),
        "theme": m.get("theme-color", ""),
    }


def save_picture(url, dest, width):
    if Image is None or not url:
        return False
    try:
        _, _, _, body = http_get(url, "image/*")
        im = Image.open(io.BytesIO(body))
        im = im.convert("RGBA" if dest.suffix == ".png" else "RGB")
        if im.width > width:
            im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.suffix == ".png":
            im.save(dest, optimize=True)
        else:
            im.save(dest, quality=84, method=6)
        return True
    except Exception as exc:  # a bad picture shouldn't stop the run
        print(f"  could not save picture {url}: {exc}")
        return False


COVER = """<!doctype html><html><head><meta charset="utf-8"><style>
html, body { margin: 0; width: 1440px; height: 900px; overflow: hidden; }
body { font-family: -apple-system, "Segoe UI", "Helvetica Neue", "Liberation Sans", Arial, sans-serif; color: %(ink)s;
  background: radial-gradient(ellipse 80%% 70%% at 50%% 38%%, %(light)s 0%%, %(base)s 58%%, %(dark)s 100%%); }
svg { position: absolute; inset: 0; }
.c { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; padding: 0 0 50px; }
.icon { width: 150px; height: 150px; border-radius: 36px; object-fit: cover; margin-bottom: 30px; box-shadow: 0 26px 50px -24px #0009, 0 0 0 1px #ffffff40; }
.eyebrow { margin: 0 0 16px; font-size: 18px; font-weight: 600; letter-spacing: .3em; text-transform: uppercase; opacity: .72; }
h1 { margin: 0; max-width: 780px; font-size: 112px; line-height: 1; font-weight: 800; letter-spacing: -.025em; }
p.tag { margin: 24px 0 0; max-width: 760px; font-size: 32px; line-height: 1.35; opacity: .86;
  display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
</style></head><body>
<svg viewBox="0 0 1440 900"><g fill="none" stroke="%(ink)s" stroke-opacity=".08" stroke-width="2"><circle cx="720" cy="410" r="300"/><circle cx="720" cy="410" r="440"/><circle cx="720" cy="410" r="600"/></g></svg>
<div class="c">%(icon)s<p class="eyebrow">An amaris ct project</p><h1 id="t">%(title)s</h1><p class="tag">%(tagline)s</p></div>
<script>const h = document.getElementById("t"); let s = 112; while (h.scrollWidth > 780 && s > 56) { s -= 4; h.style.fontSize = s + "px"; }</script>
</body></html>"""


def mix(hex_color, other, amount):
    a = [int(hex_color[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(other[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * amount):02x}" for x, y in zip(a, b))


def make_cover(p, theme, dest):
    """Draw a cover for a project with no share image: its icon, name and
    tagline on its own brand color (or silver)."""
    import base64
    from playwright.sync_api import sync_playwright

    base = theme if re.fullmatch(r"#[0-9a-fA-F]{6}", theme or "") else "#c9c9c7"
    r, g, b = (int(base[i:i + 2], 16) / 255 for i in (1, 3, 5))
    light_bg = (0.2126 * r + 0.7152 * g + 0.0722 * b) > 0.45
    icon = ""
    icon_file = ROOT / p["icon"] if p["icon"] else None
    if icon_file and icon_file.exists():
        icon = f'<img class="icon" src="data:image/png;base64,{base64.b64encode(icon_file.read_bytes()).decode()}">'
    page = COVER % {
        "base": base, "light": mix(base, "#ffffff", .38), "dark": mix(base, "#000000", .22),
        "ink": "#1d1d1d" if light_bg else "#ffffff",
        "icon": icon, "title": e(p["title"]), "tagline": e(p["tagline"] or "A new project from the studio."),
    }
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        tab = browser.new_page(viewport={"width": 1440, "height": 900})
        tab.set_content(page)
        tab.wait_for_timeout(300)
        png = tab.screenshot()
        browser.close()
    im = Image.open(io.BytesIO(png)).convert("RGB").resize((1200, 750), Image.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    im.save(dest, quality=86, method=6)


# ---------------------------------------------------------------- projects

def project_site(owner, info):
    """The project's public address: its website field, else its GitHub Pages site."""
    if info.get("homepage"):
        return info["homepage"]
    if info.get("has_pages"):
        return f"https://{owner.lower()}.github.io/{info['name']}/"
    return ""


def tidy_title(title):
    title = re.split(r"\s+[·|—–-]\s+|:\s", title or "")[0].strip()
    return title if 0 < len(title) <= 60 else ""


def pretty_name(repo):
    words = re.sub(r"[-_]+", " ", repo).strip()
    return words[:1].upper() + words[1:]


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def month_label(iso):
    d = dt.date.fromisoformat(iso[:10])
    return f"{d:%b} {d.year}"


def day_label(iso):
    d = dt.date.fromisoformat(iso[:10])
    return f"{d:%b} {d.day}, {d.year}"


def site_is_off(url, repo, info, owner):
    """True when url is the repo's GitHub Pages address but Pages isn't turned on."""
    if not (repo and info and url):
        return False
    pages = f"https://{owner.lower()}.github.io/{repo.lower()}"
    return url.lower().rstrip("/") == pages and not info.get("has_pages") and not info.get("homepage")


def live_url(url, repos, owner):
    """For links anywhere on the page: a project's Pages address, or its
    GitHub page while its site is off."""
    for repo, info in repos.items():
        if site_is_off(url, repo, info, owner):
            return info.get("html_url") or f"https://github.com/{owner}/{repo}"
    return url


def resolve(entry, repos, owner):
    """Everything the gallery needs for one project. Fields set in
    data/projects.json win over what GitHub and the project's site say."""
    repo = entry.get("repo")
    info = repos.get(repo, {}) if repo else {}
    site = info.get("site") or {}
    address = project_site(owner, info) if repo else ""
    title = entry.get("title") or tidy_title(site.get("title")) or pretty_name(repo or "Project")
    about = info.get("description") or site.get("description") or ""
    picture = entry.get("image") or (f"assets/projects/{repo}.webp" if repo and (ASSETS / f"{repo}.webp").exists() else "")
    icon = entry.get("icon") or (f"assets/projects/{repo}-icon.png" if repo and (ASSETS / f"{repo}-icon.png").exists() else "")
    url = entry.get("url") or address or (info.get("html_url") or "")
    link_label = entry.get("link_label") or (f"Visit {title}" if address else "See it on GitHub")
    details = dict(entry.get("details") or {
        "Medium": "Website" if address else "Code",
        "Added": day_label(entry["added"]) if entry.get("added") else "",
    })
    if site_is_off(url, repo, info, owner):
        url = info.get("html_url") or f"https://github.com/{owner}/{repo}"
        link_label = "See it on GitHub"
        details["Status"] = "Site coming soon"
    return {
        "id": entry.get("id") or slug(title),
        "title": title,
        "kind": entry.get("kind") or "New project",
        "started": entry.get("started") or (info.get("created") or entry.get("added") or "")[:10],
        "tagline": entry.get("tagline") or about,
        "summary": entry.get("summary") or about,
        "details": details,
        "url": url,
        "link_label": link_label,
        "github": f"https://github.com/{owner}/{repo}" if repo else "",
        "image": picture,
        "image_alt": entry.get("image_alt") or (f"{title}’s website" if picture else ""),
        "image_position": entry.get("image_position") or "",
        "image_still": entry.get("image_still") or "",
        "icon": icon,
        "featured": bool(entry.get("featured")),
    }


def ordered(projects):
    """Featured projects first, then the newest."""
    featured = [p for p in projects if p["featured"]]
    rest = sorted((p for p in projects if not p["featured"]), key=lambda p: p["started"], reverse=True)
    return featured + rest


def picture_size(path):
    if Image is None:
        return None
    try:
        with Image.open(ROOT / path) as im:
            return im.size
    except Exception:
        return None


# ---------------------------------------------------------------- HTML

def e(text):
    return html.escape(str(text or ""), quote=True)


def link_attrs(url):
    return '' if not re.match(r"https?://", url) else ' target="_blank" rel="noopener"'


def card_html(p, number, total):
    if p["image"]:
        size = picture_size(p["image"])
        wh = f' width="{size[0]}" height="{size[1]}"' if size else ""
        if p["image_position"]:
            wh += f' style="object-position: {e(p["image_position"])}"'
        still = p["image_still"] or p["image"]
        art = f'<img class="g-art" src="{e(p["image"])}"{wh} alt="{e(p["image_alt"])}" loading="lazy" decoding="async">'
        if p["image_still"]:   # moving cover: show the still frame to visitors who prefer less motion
            art = f'<picture><source media="(prefers-reduced-motion: reduce)" srcset="{e(still)}">{art}</picture>'
        media = (
            f'<div class="g-media"><img class="g-blur" src="{e(still)}" alt="" loading="lazy" decoding="async">{art}</div>'
        )
    else:
        media = f'<div class="g-media g-blank"><span aria-hidden="true">{e(p["title"])}</span></div>'
    details = "".join(f"<div><dt>{e(k)}</dt><dd>{e(v)}</dd></div>" for k, v in p["details"].items() if v)
    links = ""
    if p["url"]:
        arrow = " ↗" if link_attrs(p["url"]) else " →"
        links += f'<a class="g-visit" href="{e(p["url"])}"{link_attrs(p["url"])}>{e(p["link_label"])}{arrow}</a>'
    if p["github"] and p["github"].rstrip("/").lower() != p["url"].rstrip("/").lower():
        links += f'<a class="g-code" href="{e(p["github"])}" target="_blank" rel="noopener">Code on GitHub ↗</a>'
    tagline = p["tagline"].strip()
    quote = f'<p class="g-tagline">“{e(tagline)}”</p>' if tagline else ""
    summary = f'<p class="g-summary">{e(p["summary"])}</p>' if p["summary"] and p["summary"] != tagline else ""
    date = f'<time datetime="{e(p["started"])}">{e(month_label(p["started"]))}</time>' if p["started"] else ""
    return (
        f'      <li class="g-card" id="project-{e(p["id"])}" data-kind="{e(p["kind"])}" data-icon="{e(p["icon"] or p["image"])}"'
        f' data-number="{number:02d} / {total:02d}">\n'
        f'        <article class="g-inner">{media}<div class="g-info">'
        f'<div class="g-head"><h3 class="g-title">{e(p["title"])}</h3>{date}</div>'
        f'{quote}{summary}<dl class="g-details">{details}</dl><p class="g-links">{links}</p></div></article>\n'
        f"      </li>"
    )


def log_html(entries, fix=lambda u: u):
    def item(x):
        title = e(x["title"])
        if x.get("url"):
            url = fix(x["url"])
            title = f'<a href="{e(url)}"{link_attrs(url)}>{title}{" ↗" if link_attrs(url) else ""}</a>'
        return (
            f'<li><time datetime="{e(x["date"])}">{e(day_label(x["date"]))}</time>'
            f'<span class="log-tag">{e(x["tag"])}</span><div><b>{title}</b><p>{x.get("text", "")}</p></div></li>'
        )

    entries = sorted(entries, key=lambda x: x["date"], reverse=True)
    recent, earlier = entries[:RECENT_LOG_ENTRIES], entries[RECENT_LOG_ENTRIES:]
    out = '    <ol class="log-list">\n' + "".join(f"      {item(x)}\n" for x in recent) + "    </ol>\n"
    if earlier:
        out += (
            '    <details class="log-earlier">\n      <summary>Earlier entries</summary>\n      <ol class="log-list">\n'
            + "".join(f"        {item(x)}\n" for x in earlier)
            + "      </ol>\n    </details>\n"
        )
    return out


def replace_between(text, name, content):
    start, end = f"<!-- {name}:start -->", f"<!-- {name}:end -->"
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
    if not pattern.search(text):
        sys.exit(f"index.html is missing the {start} … {end} markers")
    return pattern.sub(lambda _: f"{start}\n{content}{end}", text, count=1)


def update_structured_data(text, projects):
    pattern = re.compile(r'(<script type="application/ld\+json">\n)(.*?)(\n</script>)', re.S)
    match = pattern.search(text)
    if not match:
        return text
    data = json.loads(match.group(2))
    brands = [
        {"@type": "Brand", "name": p["title"], "url": p["url"]}
        for p in projects
        if p["github"] and p["url"].startswith("http")
    ]
    for node in data.get("@graph", []):
        if node.get("@type") == "Organization":
            node["brand"] = brands
    body = json.dumps(data, indent=2, ensure_ascii=False)
    return text[: match.start(2)] + body + text[match.end(2):]


def render(cfg, repos, log):
    owner = cfg["owner"]
    projects = ordered([resolve(entry, repos, owner) for entry in cfg["projects"]])
    total = len(projects)
    cards = "\n".join(card_html(p, i + 1, total) for i, p in enumerate(projects)) + "\n"
    page = INDEX.read_text(encoding="utf-8")
    page = replace_between(page, "projects", cards)
    page = replace_between(page, "log", log_html(log, lambda u: live_url(u, repos, owner)))
    page = update_structured_data(page, projects)
    changed = write_if_changed(INDEX, page)
    if changed and SITEMAP.exists():
        today = dt.date.today().isoformat()
        sitemap = re.sub(
            r"(<loc>" + re.escape(STUDIO_URL) + r"</loc>\s*<lastmod>)[^<]*(</lastmod>)",
            lambda m: m.group(1) + today + m.group(2),
            SITEMAP.read_text(encoding="utf-8"),
        )
        write_if_changed(SITEMAP, sitemap)
    return changed, projects


# ---------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fetch", action="store_true", help="look on GitHub for new projects")
    parser.add_argument("--covers", action="store_true", help="draw covers for new projects that have no share image")
    args = parser.parse_args()

    cfg = load_json(PROJECTS_FILE, None)
    if not cfg:
        sys.exit("data/projects.json is missing")
    repos = load_json(REPOS_FILE, {})
    log = load_json(LOG_FILE, [])
    owner = cfg["owner"]
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    added = []

    if args.fetch:
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        listed = github_repos(owner, token)
        fresh = {}
        for r in listed:
            if r.get("private"):
                continue
            fresh[r["name"]] = {
                "name": r["name"],
                "description": (r.get("description") or "").strip(),
                "homepage": (r.get("homepage") or "").strip(),
                "has_pages": bool(r.get("has_pages")),
                "created": (r.get("created_at") or "")[:10],
                "html_url": r.get("html_url", ""),
                "fork": bool(r.get("fork")),
                "archived": bool(r.get("archived")),
                "has_commits": (r.get("size") or 0) > 0,
            }
            if repos.get(r["name"], {}).get("site"):
                fresh[r["name"]]["site"] = repos[r["name"]]["site"]
        print(f"GitHub lists {len(fresh)} public repos for {owner}.")

        known = {p.get("repo") for p in cfg["projects"]} | set(cfg.get("not_shown", [])) | {cfg["studio_repo"]}
        for name, info in sorted(fresh.items(), key=lambda kv: kv[1]["created"]):
            if name in known or info["fork"] or info["archived"] or not info["has_commits"]:
                continue
            if name.lower() in (owner.lower(), f"{owner.lower()}.github.io"):
                continue
            address = project_site(owner, info)
            site = site_info(address) if address else None
            if not (info["description"] or site):
                print(f"  {name}: waiting for a description or a live site")
                continue
            if site:
                info["site"] = site
            cfg["projects"].append({"repo": name, "auto": True, "added": today})
            p = resolve(cfg["projects"][-1], fresh, owner)
            log.insert(0, {
                "date": today,
                "tag": p["title"],
                "title": f"New project: {p['title']}",
                "url": p["url"],
                "text": e(p["summary"] or p["tagline"] or "A new amaris ct project."),
            })
            added.append(p["title"])
            print(f"  added {name} as “{p['title']}”")

        # Keep auto-added projects' details current, and collect pictures for them.
        for entry in cfg["projects"]:
            if not entry.get("auto") or entry["repo"] not in fresh:
                continue
            info = fresh[entry["repo"]]
            address = project_site(owner, info)
            site = site_info(address) if address else None
            if site:
                info["site"] = site
            site = info.get("site") or {}
            picture, icon = ASSETS / f"{entry['repo']}.webp", ASSETS / f"{entry['repo']}-icon.png"
            if not entry.get("image") and not picture.exists() and site.get("image"):
                save_picture(site["image"], picture, 1200)
            if not entry.get("icon") and not icon.exists() and site.get("icon"):
                save_picture(site["icon"], icon, 192)

        repos = fresh
        save_json(REPOS_FILE, repos)
        save_json(PROJECTS_FILE, cfg)
        save_json(LOG_FILE, log)

    # New projects without a share image get a drawn cover.
    missing = [entry for entry in cfg["projects"]
               if entry.get("auto") and not entry.get("image") and not (ASSETS / f"{entry['repo']}.webp").exists()]
    if args.covers:
        for entry in missing:
            p = resolve(entry, repos, owner)
            theme = (repos.get(entry["repo"], {}).get("site") or {}).get("theme", "")
            try:
                make_cover(p, theme, ASSETS / f"{entry['repo']}.webp")
                print(f"  cover drawn for {entry['repo']}")
            except Exception as exc:
                print(f"  could not draw a cover for {entry['repo']}: {exc}")
        missing = [m for m in missing if not (ASSETS / f"{m['repo']}.webp").exists()]

    changed, projects = render(cfg, repos, log)
    print(f"Gallery has {len(projects)} projects; page {'updated' if changed else 'unchanged'}.")

    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
            out.write(f"needs_covers={'true' if missing and not args.covers else 'false'}\n")
    if os.environ.get("RUNNER_TEMP"):
        message = f"Add {', '.join(added)} to the studio gallery" if added else "Update studio projects"
        notes = Path(os.environ["RUNNER_TEMP"]) / "commit-message.txt"
        if added or not notes.exists():
            notes.write_text(message + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
