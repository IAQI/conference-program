# Working on a conference website (QCrypt, TQC, QIP)

The three websites ([qcrypt-website](https://github.com/IAQI/qcrypt-website),
[tqc-website](https://github.com/IAQI/tqc-website),
[qip-website](https://github.com/IAQI/qip-website)) are built the same way:
[Hugo](https://gohugo.io/) turns Markdown and data files into a static site,
[Netlify](https://www.netlify.com/) builds and publishes it on every push, and
the look and the program pages come from this module, `conference-theme`.
This guide describes what is common to all three; each site's README adds what
is specific to it (domains, people to ask, design notes).

## Working locally

1. Install [Hugo](https://gohugo.io/installation/) (extended), [Dart Sass](https://gohugo.io/functions/css/sass/#dart-sass),
   [Go](https://go.dev/dl/) (Hugo downloads this module with it) and Node.js (`npm ci` installs PostCSS).
2. Clone the website and run `hugo server`; the site is at http://localhost:1313/.
   `--disableFastRender` rebuilds everything on each change, `--ignoreCache` ignores cached files.
3. Edit the Markdown files in `content/<year>/` and the data files in `data/`.
   The running server shows changes immediately.
4. Push to a branch and open a pull request: Netlify builds a deploy preview.
   Merging into `main` publishes the site.

To try changes to this module in a site before publishing them, clone it next
to the site and run
`HUGO_MODULE_REPLACEMENTS="github.com/IAQI/conference-theme -> ../conference-theme" hugo server`.

## How a site is organised

| path | content |
|---|---|
| `content/<year>/` | one folder per conference year: home page `_index.md`, pages like `call.md`, `registration.md`, `charter.md`, `history.md`, `code-of-conduct.md`, and the sections `team/`, `partners/`, `speakers/`, `sessions/`, `schedule/` |
| `data/` | accepted papers, posters, schedule, rooms, presenters, videos (`<kind>-<year>.json/.yml`), the footer (`footer.yml`) and the schedule categories (`categories.yml`) |
| `static/images/<year>/` | logos, banner and background of that year |
| `assets/style/theme-<year>.scss` | that year's colours (see [Colours and styles](#colours-and-styles)) |
| `hugo.toml` | site settings, `[params.<year>]` (city, logos, colour) and the menus per year |
| `netlify.toml` | build settings and redirects (`/` to the current year, older years to the archive) |
| `layouts/`, `assets/`, `i18n/` | only files that replace the module's version for this site |

> [!WARNING]
> The top-level folders of `content/` are years, not topics as Hugo recommends,
> so in templates `.Section` is the conference year.

Every content file starts with a [front matter](https://gohugo.io/content-management/front-matter/)
(YAML between `---` lines). The important keys are `title`, `year`, `type`,
`draft` and `menu`. A page with `draft: true` is not published.

Use sensible file names: lowercase, words separated by `-` or `_`
(`eleni_diamanti.md`, `images/logo.png`).

### Shortcodes

Pages use [Hugo shortcodes](https://gohugo.io/content-management/shortcodes/):
`{{%  %}}` for Markdown content (e.g. `jumbo` on the home page), `{{<  >}}` for
HTML (e.g. `button-link`). Some enclose content and have a closing tag
(`{{% jumbo %}}...{{% /jumbo %}}`), others don't (`button-link`).
The most used ones:

| shortcode | used for |
|---|---|
| `jumbo` | the top of the home page: background, logo, date, call-to-action buttons |
| `home-info`, `home-keydates` | the information box and the key dates / website updates tables of the home page |
| `home-location` | the venue: `address=`, optional `image=`, optional `booking_link=` with `booking_note=` |
| `partners` | the sponsors of the year |
| `speakers`, `teams` | the speakers and the committees |
| `button-link` | a button: `label=`, `url=`, `icon=` |
| `papers-accepted`, `posters-accepted` | the accepted papers and posters (see the README) |
| `code-of-conduct` | a standard code of conduct: `{{< code-of-conduct name="QCrypt" />}}`; a site can also keep its own text |

The original theme's documentation of these blocks is in [theme-reference.md](theme-reference.md).

### Menus

All three sites aim for the same top bar (modelled on the IACR conferences,
e.g. https://eurocrypt.iacr.org/2026/):

| top-level | identifier | weight | dropdown (only what exists) |
|---|---|---|---|
| Home | `home` | 10 | – |
| Program ▾ | `program` | 20 | Schedule (added automatically once published) · Accepted papers (10) · Accepted posters (12) · Speakers (20) · Sessions (25) · Call for papers (30) · Presentation & poster instructions (40) |
| Schedule | – | 25 | set in `schedule/_index.md`; appears once that page is published |
| Attend ▾ | `attend` | 30 | Registration (10) · Venue & travel (20) · Accommodation (25) · Student support (30) · Visas (35) · Activities & excursions (40) · Code of conduct (50) · Photos (60) |
| Sponsors | `sponsors` | 40 | – |
| Committees | `committees` | 50 | – |
| About ▾ | `about` | 60 | About the conference / charter (10) · History (20) · Future editions (30) · About the logo (40) · local pages (50+) |

This is the structure each year grows into, not a rule. Early in a year,
before there is a program, it is fine (and common) to show the call for
papers and the registration as top-level items, as QIP 2027 does; once the
papers are accepted, they move into Program ▾ and Attend ▾. `new_year.py`
starts each new year from the previous year's menus.

The parents (Program, Attend, About, and the plain items Home, Sponsors,
Committees) are defined in `hugo.toml` under `[[menu.<year>]]`; a parent with
a dropdown is not a link itself. Pages add themselves under a parent in their
front matter:

```yaml
menu:
    2027:
        parent: program
        weight: 10
```

Mind that `parent: #program` is a YAML comment, not a parent. The schedule
page puts itself at the top level (no parent, weight 25); the header also lists
it first under Program.

### Footer

`data/footer.yml` defines the footer. Its links (charter, history, code of
conduct) point to the current year's pages, so every year needs `charter.md`,
`history.md` and `code-of-conduct.md`. Links starting with `https://` are used
as they are. The names shown for charter and history come from the site's
`i18n/en.toml`. The Netlify open-source plan requires a link to a code of conduct.

### Home page

`content/<year>/_index.md` has `type: home` and `layout: home`. It starts with
the `jumbo` block, followed by `home-info`, `home-keydates` (key dates and a
"website updates" table, so that visitors see what changed), `home-location`
and `partners`.

### Team, partners, speakers

- **Team:** one subfolder per committee in `content/<year>/team/`, portraits in
  `team/images/`; `photoURL` points to the picture.
- **Partners (sponsors):** one subfolder per category in `partners/`, logos in
  `logos/`; the `logo` front matter points to the file.
- **Speakers:** one page per invited, tutorial or industry speaker in
  `speakers/<kind>/`, with a unique `key:`. Each talk is a session page
  (`type: sessions`, `format: invited`, ...) in `sessions/` that lists the
  speaker under `speakers: [<key>]`; the speaker's page then shows the talk title.

### Sessions and schedule

Session pages are in `content/<year>/sessions/` (`type: sessions`, `year`,
`format`, optional `chair`, `papers` (paper ids), `speakers`, `tags`). The
schedule page lists them by day and time from `data/schedule-<year>.yml`.
Both are best produced from the program spreadsheet with `generate_schedule.py`;
the [README](../README.md) describes the whole pipeline from the accepted papers
to presenters and videos.

On the schedule, each card is coloured by the session's tag (one per session):

| tag | for | colour variable |
|---|---|---|
| `logistics` | registration, check-in, announcements | `--sched-logistics` |
| `break` | coffee breaks | `--sched-break` |
| `meal` | lunch, dinner, banquet | `--sched-meal` |
| `social` | reception, excursion | `--sched-social` |
| `poster` | poster sessions | `--sched-poster` |
| `plenary` | opening, closing, business meeting, awards | `--sched-plenary` |
| `invited`, `tutorial` | invited and tutorial talks | `--sched-invited`, `--sched-tutorial` |
| `contributed` | contributed talks (`track` works too) | `--sched-contributed` |
| `sponsor` | sponsored talks, exhibition | `--sched-sponsor` |
| `notice` | something to stand out (e.g. check-out) | `--sched-notice` |

A site sets its own colours in `theme-<year>.scss`, e.g.
`:root { --sched-meal: #9BC2E6; }`. A card is a link to its session page only
when that page has something to show (papers, speakers, text, slides or a
video); sessions in parallel are shown side by side with centred titles.

## A new year

1. **Design:** a logo, a background image for the home page, a banner for the
   other pages (put them in `static/images/<year>/`) and a main colour.
2. **Start the year from the previous one:**
   ```sh
   python3 ../conference-theme/scripts/new_year.py --year 2028
   ```
   It copies the previous year's general pages (home, call, registration,
   charter, history, code of conduct and the section pages, but no talks,
   speakers, committee members or sponsors), sets them to `draft: true`, copies
   `[params.<year>]`, the menus and `theme-<year>.scss`, and prints a checklist.
3. **Fill in** `[params.<year>]` in `hugo.toml`: `city`, `timeanddate_cityid`
   (from https://www.timeanddate.com/worldclock/personal.html, "Share This
   Personal World Clock"), `themeColor` (same as `--primary`) and the logos.
4. **Colours** in `assets/style/theme-<year>.scss`.
5. **Pages:** update each page in `content/<year>/` and set `draft: false`
   when it is ready. Leave `currentYear` in `hugo.toml` unchanged until then.
6. **Promote the year** once the new site is ready: in `hugo.toml` change
   `params.currentYear`, `params.date` and the `/` redirect under
   `[server]`; in `netlify.toml` change the `/` redirect.
7. **Archive the old year** when it is no longer needed on the live site: move
   it to the archive site (`qcrypt.iaqi.org`, `tqc.iaqi.org`, `qip.iaqi.org`),
   delete `content/<year>/`, its data files, its `theme-<year>.scss` and its
   `[params.<year>]` / `[[menu.<year>]]` blocks, and add a redirect
   `/<year>/*` to the archive in `netlify.toml`.

During the year: update the call, registration and venue pages as news comes
in, and add a line to the "website updates" table on the home page each time.

## Colours and styles

Each year has `assets/style/theme-<year>.scss`:

```scss
@use "theme";               // the whole shared theme

:root {
    --primary: #ac191c;     // main colour: top bar, buttons, links
    --primary-txt: #ffffff; // text on the main colour
}
// ... any extra rules for this year
```

Optional variables, when buttons or boxes should not use the main colour (as
on QIP 2027, where the top bar is white): `--header-txt`, `--button-bg`,
`--button-txt`, `--box-bg`, `--box-txt`, `--toc-link`.

A site can replace any single style, layout or translation file of the module
by putting its own copy at the same path, e.g. `assets/style/partials/_tags.scss`
(the colours of the schedule categories) or `layouts/partners/list.html`.
Keep such copies few: a fix in the module does not reach a site that has
replaced the file.

## Updating the module in a site

```sh
hugo mod get -u github.com/IAQI/conference-theme
```

then commit `go.mod` and `go.sum`. Netlify needs Go for this
(`GO_VERSION` in `netlify.toml`). A site only changes when its pin is updated.
