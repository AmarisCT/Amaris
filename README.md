# amaris ct

**amaris creative tech** · Exploring Human × Machine

The studio website for amaris ct and the parent home of its projects:

- [Artificially Intelligent](https://amarisct.github.io/Artificially-Intelligent/), a research archive
- [The Weekly Planner](https://amarisct.github.io/Weekly-Planner/), a digital planning space (in development)

The name is always written in lowercase: amaris ct, short for amaris creative tech.

Static site. GitHub Pages publishes from `main`, root folder. `privacy.html` and `terms.html` cover every amaris ct project.

## Pages

- `index.html` — the studio homepage
- `worlds.html` — Creative Worlds gallery
- `privacy.html`, `terms.html` — shared policies (update privacy first whenever a site starts handling information in a new way)
- `404.html` — not-found page; uses `/Amaris/` absolute paths because it is served for any missing URL
- `data/`, `scripts/build_projects.py`, `assets/projects/` — the gallery and studio log (see below)

## The gallery (Selected work)

The project cards in `index.html` sit between `<!-- projects:start -->` and `<!-- projects:end -->` and are **generated**. Don't edit them by hand. Edit `data/projects.json`, then run:

```
python3 scripts/build_projects.py
```

- Featured projects come first, then the rest, newest first.
- Each entry can set `title`, `kind`, `started`, `tagline` (shown in quotes), `summary`, `details`, `url`, `link_label`, `image`, `image_alt`, `image_position` and `icon`. Fields you set always win over what GitHub or the project's site says.
- `not_shown` lists repos that stay off the site. To hide a project, move its repo name there. To show an older repo, add an entry for it to `projects`.
- On the page, a script turns the cards into the 3D gallery. Without scripts, they show as a grid.

## New projects are added automatically

`.github/workflows/add-new-projects.yml` runs every 30 minutes and on any change to `data/` or the script. It adds a repo to the gallery and the studio log when it is:

- public, not a fork, not archived, and not empty,
- not already listed in `data/projects.json` (`projects` or `not_shown`),
- and has a **description** or a **live site** (its GitHub "Website" field, or GitHub Pages).

The card uses the site's own title, description and share image (`og:image`), or a screenshot if the site has no share image. With no site, the card links to GitHub. Pictures go in `assets/projects/<repo>.webp`. Delete one to have it taken again.

`data/repos.json` is what GitHub last reported. The job writes it, so don't edit it.

GitHub pauses scheduled jobs in a repo that has had no activity for 60 days. If that happens, open the repo's **Actions** tab and turn the workflow back on, or push any change.

## Studio log

The log in `index.html` is generated from `data/log.json` (between `<!-- log:start -->` and `<!-- log:end -->`). Add entries there, newest first. `text` may contain links. The six newest show; the rest go under "Earlier entries".

## Things that update in the browser

- **From the archive** shows the newest essays from Artificially Intelligent's `research/published/manifest.json`. The two current essays are also written into the page so it works without scripts; refresh them occasionally.

## Studio soundtrack

The music button in the gallery plays a Spotify **Chill Mix** playlist (`spotify:playlist:37i9dQZF1EVHGWrwldPRtj`, `PLAYLIST` in the gallery script in `index.html`). Spotify refreshes the mix on its own, so the songs rotate. Nothing loads from Spotify until a visitor presses the button. Visitors who aren't signed in to Spotify may hear 30-second previews. To change it, replace the playlist ID, and keep the Spotify note in `privacy.html` accurate.

## The look

- `studio.css` is shared by every page: the silver room behind the site (`.env`), glass windows (`.window`), glass panels (`.glass`, `.smoke`), rounded list groups (`.inset-list`), glass buttons (`.pill`), the floating tab bar (`.tabbar`: on the left at 1100px and wider, at the bottom on smaller screens) and the glass footer.
- `legal.css` adds the page title and reading styles for Privacy, Terms, Creative Worlds and the 404 page.
- Each page starts its body with `<div class="env">` and the same tab bar markup. The 404 page uses `/Amaris/` paths because it can be served at any address.
- Visitors who ask for reduced transparency get solid panels, and reduced motion turns the animations off.

## Contact and brand

- Enquiries go to LinkedIn: https://www.linkedin.com/in/jojomojojo222/
- Favicons (`favicon.ico`, `favicon-32.png`, `apple-touch-icon.png`, `icon-192.png`, `icon-512.png`) use the silver "a" from the wordmark. `og-card.jpg` is the 1200×630 link preview.
- `sitemap.xml` lists the indexable pages; update `lastmod` when a page changes.
