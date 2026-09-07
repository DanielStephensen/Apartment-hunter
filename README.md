# Apartment hunter

Scrapes eleven Copenhagen rental sites twice a day, in the **morning and
afternoon Europe/Copenhagen** (see [Schedule](#schedule) — GitHub's cron is not
punctual), records every apartment it has not seen before in a CSV, and
publishes a single sortable page of the results on GitHub Pages.

## What it looks for

| Criterion | Rule |
| --- | --- |
| Rooms | 5 or more |
| Area | Copenhagen incl. Østerbro, Nørrebro, Nordvest, Amager / København S, Ørestad, Valby, Sydhavn, Nordhavn, Frederiksberg, Hellerup, Kastrup |
| Delevenlig | Listings the site explicitly marks as **not** suitable for sharing are dropped |

Sites whose URL already applies a filter are trusted for that filter when a card
is too terse to parse (`url_enforced` in `config.py`); everything we *can* read
is checked anyway, so a silently broken site filter cannot let bad results
through. For the sites with no filters in their URL — Kereby and Juli Living —
the room count and the location must be readable, or the listing is skipped.

### About "delevenlig"

Only some sites use the word at all. The rule is therefore:

* explicitly **delevenlig** → kept, recorded as `ja`
* explicitly **not delevenlig** ("ikke delevenlig", "delevenlig: nej") → dropped
* **not mentioned** → kept, recorded as `ukendt`

Treating silence as a "no" would hide most of the market, so the CSV and the
page both carry the distinction and the page can filter on it. The wording is
usually on the detail page rather than the card, which is why each new listing's
own page is opened once.

## How it works

```
config.py     one SiteConfig per site — URL, link pattern, render options
   │
render.py     Playwright: loads the page, accepts the cookie banner, scrolls,
   │          clicks "load more", retries on throttling → HTML
   │
extract.py    finds every link matching the site's pattern, climbs to the
   │          smallest container holding exactly one of them, reads the fields
   │
detail.py     opens each *new* listing's page to fill gaps and settle delevenlig
   │
filters.py    plausibility → rooms → geography → delevenlig, first no wins
   │
store.py      data/listings.csv, keyed on the canonical listing URL,
   │          plus data/rejected.csv so ruled-out flats are not re-fetched
   │
report.py     docs/index.html
```

The extraction is deliberately structural rather than a pile of per-site CSS
selectors. Every one of these sites is built on a different stack (WordPress,
Next.js, Umbraco, custom SPAs) and none exposes a documented API, but all of
them share one property: **an apartment is a link to its own detail page inside
a card**. Anchoring on that link and climbing until a second listing appears
finds the card without knowing anything about the site's markup, so a redesign
usually costs nothing. A site can still override any part of it via
`card_selector` / `selectors`, or register a custom scraper in `sites/`.

Deduplication runs *before* detail pages are fetched, so each run only pays one
extra request per genuinely new apartment — the second run of the day opens
almost nothing, because it already knows everything the first one found.

## Running it locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

python -m apartment_hunter                 # scrape everything, rebuild the page
python -m apartment_hunter --site kereby   # one site
python -m apartment_hunter --dry-run       # scrape without writing anything
python -m apartment_hunter --headed        # watch the browser work
python -m apartment_hunter --report-only   # rebuild the page from the CSV
```

Then open `docs/index.html`.

```bash
python -m unittest discover tests          # 67 tests, no network needed
```

## Publishing on GitHub Pages

1. Push the project:

   ```bash
   git push -u origin main
   ```

   The remote is already `github.com/DanielStephensen/Apartment-hunter`, so the
   page will be served at

   **https://danielstephensen.github.io/Apartment-hunter/**

   To use the bare `https://danielstephensen.github.io` address instead, the
   repository has to be named `DanielStephensen.github.io` — rename it under
   *Settings → General*, or push this project to a repository with that name.
   Nothing in the code depends on either choice.

2. **Settings → Pages → Source: GitHub Actions.**

3. **Settings → Actions → General → Workflow permissions: Read and write**, so
   the run can commit the updated CSV.

4. Trigger the first run by hand from the **Actions** tab
   (*Scrape apartments → Run workflow*).

### Schedule

The two runs are scheduled at 09:00 and 16:00 UTC, which is 11:00 and 18:00 in
Copenhagen in summer and an hour earlier in winter. GitHub dispatches scheduled
workflows on a best-effort basis and in practice starts this one one to six
hours after the cron time, so treat both times as "morning" and "afternoon"
rather than as appointments — the drift from daylight saving is the smallest
source of error by far.

> GitHub disables scheduled workflows in repositories with no commits for 60
> days. This one commits whenever it finds something, so that only becomes a
> risk during a very quiet stretch — the workflow can be re-enabled from the
> Actions tab.

## Adding or fixing a site

`tools/discover.py` renders a site and reports what it actually links to, which
is how every pattern in `config.py` was established:

```bash
python -m tools.discover kereby              # what does this site link to?
python -m tools.discover --all --save-html   # every site, keep the HTML
python -m tools.discover balder --headed     # watch it happen
```

Add the site to `SITES` in `config.py` with the `link_pattern` the tool
suggests. If the results need a moment to arrive over XHR, set
`RenderOptions(wait_for="<selector for a listing link>")`.

## Notes

* Zero results from a site is usually correct rather than a bug — 5+ room
  apartments in Copenhagen are rare, and several of these landlords routinely
  have none. `tools/discover.py` will show you the site's own "0 boliger
  fundet" text when that is the case.
* CEJ throttles repeated automated visits and then answers HTTP 200 with a
  "429 Request limit exceeded" page. The scraper detects that in the page text,
  backs off and retries, and moves on if the site is still refusing — so a run
  from one busy IP can come back empty for CEJ alone. Twice a day from a GitHub
  runner is well inside what it tolerates.
* `data/listings.csv` is the memory of the system. Deleting a row makes that
  apartment count as new again. `data/rejected.csv` remembers apartments that
  were examined and ruled out, so their pages are not re-opened every day;
  delete it to re-examine everything from scratch.
* Sites are scraped politely: one browser, pages in sequence, and a backoff when
  a site signals throttling.
