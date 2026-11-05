# conference-program

The schedule, session pages and accepted papers / posters lists shared by the
[QCrypt](https://github.com/IAQI/qcrypt-website),
[TQC](https://github.com/IAQI/tqc-website) and
[QIP](https://github.com/IAQI/qip-website) websites, together with the scripts
that take a conference from the HotCRP list of accepted papers to a fully
linked schedule.

Everything is keyed by the **HotCRP paper id** (`pid`). Here is what the
websites get from that:

- **Schedule.** Each card shows its papers with their authors, the presenting
  author highlighted, the room, and a ▶ Video link once recordings are up.
  Sessions that start at the same time are shown side by side.
- **Session pages.** Each shows the full paper entries (abstract, arXiv,
  extended abstract, proceedings, slides), the chair, the speakers, and the
  embedded recordings.
- **Accepted papers.** Every paper has the anchor `#paper-<pid>` and links to
  the slot where it is presented and to its recording.

## Contents

| path | what |
|---|---|
| `layouts/schedule/list.html` | the schedule page (`type: schedule`) |
| `layouts/sessions/single.html` | a session page (`type: sessions`) |
| `layouts/partials/schedule-session.html` | one card on the schedule |
| `layouts/partials/paper.html`, `paper-simple.html`, `paper-authors.html`, `location.html` | paper entries |
| `layouts/partials/program/*.html` | helpers: year, video and slides lookup, paper → session index, merged papers |
| `layouts/shortcodes/papers-accepted.html`, `posters-accepted.html`, `papers-upgraded.html` | the lists |
| `assets/style/_program.scss` | styles for the elements above. Each site adds `@use "program";` to its `theme-YEAR.scss` |
| `scripts/` | the pipeline scripts below (Python 3, `pip install -r requirements.txt`) |

Everything else stays in each site's own theme: colours, fonts, the look of the
cards, the home page and so on. A site can override any single file of this
module by putting its own copy in its `layouts/` (or `assets/`) folder.

## Data files (per site, per year)

| file | written by | content |
|---|---|---|
| `data/accepted-papers-YEAR.json` | `sanitize_hotcrp_json.py` | accepted talks: `pid, title, abstract, authors[{first,last,affiliation}], mergedwith?, options{arxiv-id?, talk-type?}` |
| `data/posters-YEAR.json` | `sanitize_hotcrp_json.py` | accepted posters, same format |
| `data/schedule-YEAR.yml` | `generate_schedule.py` | days → slots `{session, time, end?, location?}` |
| `data/locations-YEAR.yml` | `generate_schedule.py`, then by hand | rooms `{key, label, description?}` |
| `content/YEAR/sessions/<key>.md` | `generate_schedule.py`, then by hand | one page per session: `title, format, tags, chair, papers[pids], speakers[keys], note`, plus a free text body |
| `data/presenters-YEAR.yml` | `mark_presenters.py` | `"pid": ["First Last"]`, the presenting author(s) |
| `data/presenters-overrides-YEAR.yml` | by hand | corrections to the above |
| `data/videos-YEAR.yml` | `fetch_videos.py` | `papers: {"pid": {id, presenter?}}`, `sessions: {"key": {id}}` |
| `data/videos-overrides-YEAR.yml` | by hand | corrections to the above |
| `data/proceedings-YEAR.yml` | by hand | `"pid": DOI` |
| `content/YEAR/extended_abstracts/<pid>_ext_abst.pdf` | by hand | extended abstracts |
| `content/YEAR/sessions/slides/<pid>.pdf` | by hand | talk slides (older years: `QCrypt<YEAR>TalkSlides<NNN>…`) |
| `content/YEAR/posters/<pid>.pdf` | by hand | poster PDFs |

Older years may still use `data/youtube-YEAR.json` and `videoId`/`videoIds`
in session pages. Both still work.

## From accepted papers to the schedule

Clone this repository next to the website (`~/Web/conference-program`); the
commands below are run from the website's root folder. Keep raw exports and
registration lists in `private_data/` (git-ignored). They contain e-mail
addresses and decisions about rejected papers, and the repositories are
public.

### 1. Accepted papers and posters (after notification)

Export the accepted submissions from HotCRP as JSON (Search → select all →
Download → JSON) and sanitize them:

```sh
python3 ../conference-program/scripts/sanitize_hotcrp_json.py private_data/hotcrp-talks.json \
    --decision accept -o data/accepted-papers-2027.json
# posters from a separate HotCRP instance: shift their ids first, so that ids never clash
python3 ../conference-program/scripts/adjust_pids.py private_data/hotcrp-posters.json private_data/posters-shifted.json --offset 1000
python3 ../conference-program/scripts/sanitize_hotcrp_json.py private_data/posters-shifted.json --decision accept -o data/posters-2027.json
```

Useful options: `--search-arxiv` looks up the arXiv id of each paper (slow:
3 s per paper), `--talk-type-from-decision` sorts papers into long-plenary /
plenary / talk (QIP), and `--keep KEY` publishes an extra field. Only the fields shown by
`--list-kept-fields` (title, abstract, author names and affiliations, topics)
are published; everything else in the export is dropped. If the export
contains decisions, `--decision` (or `--all`) is required. Merged submissions (HotCRP tag
`merge-108-377`) become `mergedwith`.

The pages `{{< papers-accepted year=2027 >}}{{< /papers-accepted >}}` and
`{{< posters-accepted year=2027 >}}{{< /posters-accepted >}}` show the lists right away.

### 2. The program (once the PC has fixed the schedule)

Keep the program in **one spreadsheet**, one row per slot (e.g. a shared
Google Sheet that the PC chairs fill in), exported as `program/program-2027.csv`:

| day | time | end | session | title | format | tags | location | chair | papers | speakers | note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2027-08-23 | 09:00 | 10:15 | tutorial/Smith | | tutorial | | Room 140 | Jane Doe | | Smith | |
| 2027-08-23 | 10:15 | 10:45 | | Coffee Break | break | break | Lobby | | | | |
| 2027-08-23 | 10:45 | 12:15 | contributed/1a | Contributed talks 1a: QKD | contributed | | Room 140 | Ann Chair | 12 7 31 | | |
| 2027-08-23 | 14:00 | 14:20 | | | contributed | | Room 140 | | 63 | | |

- **session** names the page `content/YEAR/sessions/<session>.md`.
  - If it is empty and the slot has one paper, it becomes `contributed/<pid>`
    and the page takes the paper's title.
  - Otherwise it becomes `stuff/<slug of title>`.
  - A session that happens several times (coffee breaks) is one page used by
    several rows.
- **papers** and **speakers** are separated by spaces. Speaker keys are the
  `key:` of the pages in `content/YEAR/speakers/`.
- **location** is the room as displayed. Rooms get keys in
  `data/locations-YEAR.yml`, where you can add a `description`.
- **Parallel sessions** are simply rows with the same day and time; they are
  shown side by side.

```sh
python3 ../conference-program/scripts/generate_schedule.py --year 2027 --program program/program-2027.csv --check   # report only
python3 ../conference-program/scripts/generate_schedule.py --year 2027 --program program/program-2027.csv
```

The generator writes `data/schedule-2027.yml` and `data/locations-2027.yml`,
and creates or updates the session pages. It reports paper ids that are not
in the accepted list and accepted papers that are not scheduled.

**Re-run it after every change to the spreadsheet; it is safe to repeat.**
- **Session pages:** in pages that already exist, it only updates the keys
  above, and only when the cell is not empty. Abstracts, biographies and other
  text you added by hand stay.
- **Schedule file:** edit the spreadsheet, not `schedule-2027.yml`, which is
  rewritten every time.

### 3. Presenters (once registration closes)

Ask for the registration export with the questions *"Will you be presenting?"*
(talk / poster / both / no) and *"Title of presentation"*, then:

```sh
python3 ../conference-program/scripts/mark_presenters.py --year 2027 \
    --registrations private_data/registrations.xlsx private_data/registrations-late.csv
```

- **Matching:** the script matches each declared title to an accepted paper,
  then uses the person's name to pick the author. It writes
  `data/presenters-2027.yml`.
- **Unresolved rows** are listed for a human. Put decisions in
  `data/presenters-overrides-2027.yml` (`"63": ["Joseph Carolan"]`); they
  always win.
- **Without registrations:** if the presenters are known otherwise, fill only
  the overrides file and run the script without `--registrations`.
- **Display:** presenters are shown in **bold** on paper lists and in
  *italics* on schedule cards.

### 4. After the conference

- **Videos.** Upload the recordings to YouTube in one or more playlists, then
  run:

  ```sh
  python3 ../conference-program/scripts/fetch_videos.py --year 2027 --playlist "https://www.youtube.com/playlist?list=..."
  ```

  - **Requirements and options:** it needs [yt-dlp](https://github.com/yt-dlp/yt-dlp).
    Repeat `--playlist` for every playlist (QIP has one per track).
  - **Matching:** it matches video titles against paper titles and session
    titles. Prefixes like "Invited Talk:", "[QCrypt2025]" or "Speaker Name:"
    are understood.
  - **Corrections:** videos it cannot place are listed. Put corrections in
    `data/videos-overrides-2027.yml`, for example `"26": {id: lZlPoEpRLF0}`,
    or `"70": null` to drop a match.
  - **Re-running:** run it again whenever more videos are uploaded.
- **Slides:** `content/2027/sessions/slides/<pid>.pdf` (per paper) or
  `presentation: /2027/...pdf` in a session page.
- **Poster PDFs:** `content/2027/posters/<pid>.pdf`.
- **Proceedings:** `data/proceedings-2027.yml` with `"pid": DOI`.
- **Extended abstracts:** `content/2027/extended_abstracts/<pid>_ext_abst.pdf`.

The links appear automatically on the schedule, the session pages and the
accepted lists.

## Using the module in a site

In `hugo.toml` (instead of `theme = "devfest-theme-hugo"`):

```toml
[module]
  [[module.imports]]
    path = "github.com/IAQI/conference-program"
  [[module.imports]]
    path = "devfest-theme-hugo"   # the site's own theme in themes/
```

Then, once per site:

```sh
hugo mod init github.com/IAQI/<site>-website
hugo mod get github.com/IAQI/conference-program@main
```

Commit `go.mod` and `go.sum`: they pin the exact version of the module. Hugo
downloads that version at build time, which needs [Go](https://go.dev/dl/):
locally, and on Netlify via `GO_VERSION = "1.23.4"` under `[build.environment]`
in `netlify.toml`. (`hugo mod vendor` would instead copy the module into
`_vendor/`, for build environments without Go; the IAQI sites don't need it.)

- **Updating:** `hugo mod get -u github.com/IAQI/conference-program`, then commit
  `go.mod` and `go.sum`. A site only changes when its pin is updated.
- **Local work on the module:** to preview changes to the module itself in a
  site, run
  `HUGO_MODULE_REPLACEMENTS="github.com/IAQI/conference-program -> $HOME/Web/conference-program" hugo server`.

Optional site parameters (`[params]` in `hugo.toml`):

| parameter | default | effect |
|---|---|---|
| `programFilePrefix` | `"QCrypt"` | prefix of older slide files `<prefix><YEAR>TalkSlides<NNN>…` |
| `programScheduleSpeakers` | `true` | show speaker photos on schedule cards |

## Tests

```sh
python3 -m unittest discover tests
```

The templates are checked by building the three websites before and after a
change and comparing the HTML.
