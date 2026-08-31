"""Build the published page from the CSV.

The result is one self-contained ``docs/index.html`` with the data embedded as
JSON, so GitHub Pages can serve it as a plain static file with no build step,
no fetch and no CORS surprises.
"""

from __future__ import annotations

import html
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .config import SITES
from .store import ListingStore

log = logging.getLogger(__name__)

SITE_NAMES: Dict[str, str] = {site.key: site.name for site in SITES}


def _number(value) -> Optional[float]:
    """Rows come from the CSV as strings and from a fresh scrape as numbers."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _prepare(rows: List[dict]) -> List[dict]:
    """Normalise store rows into the shapes the page expects."""
    prepared = []
    for row in rows:
        site = _text(row.get("site"))
        prepared.append(
            {
                "date": _text(row.get("scraped_date")),
                "name": _text(row.get("name")) or "(uden navn)",
                "url": _text(row.get("url")),
                "price": _number(row.get("price")),
                "rooms": _number(row.get("rooms")),
                "area": _number(row.get("area_m2")),
                "address": _text(row.get("address")),
                "postal": _text(row.get("postal_code")),
                "city": _text(row.get("city")),
                "site": SITE_NAMES.get(site, site),
                "delevenlig": _text(row.get("delevenlig")) or "ukendt",
            }
        )
    # Newest first; the page keeps this order until the reader sorts.
    prepared.sort(key=lambda item: (item["date"], item["name"]), reverse=True)
    return prepared


def build(store: ListingStore, output: Path) -> Path:
    listings = _prepare(store.rows)
    latest = listings[0]["date"] if listings else ""
    generated = datetime.now().strftime("%d-%m-%Y %H:%M")

    # The JSON sits inside a <script> block, so any "</script>" in a listing
    # title would end the block early.
    data = json.dumps(listings, ensure_ascii=False).replace("</", "<\\/")

    page = (
        _TEMPLATE.replace("__DATA__", data)
        .replace("__GENERATED__", html.escape(generated))
        .replace("__LATEST__", html.escape(latest or "–"))
        .replace("__TOTAL__", str(len(listings)))
        .replace("__NEW__", str(sum(1 for item in listings if item["date"] == latest)))
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding="utf-8")
    log.info("wrote %s (%d listings)", output, len(listings))
    return output


_TEMPLATE = """<!doctype html>
<html lang="da">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lejeboliger i København</title>
<style>
  :root {
    --bg: #f6f7f9;
    --panel: #ffffff;
    --text: #14171f;
    --muted: #666e7d;
    --line: #e3e6ec;
    --accent: #1f5eff;
    --new: #0b7a4b;
    --new-bg: #e4f6ec;
    --shadow: 0 1px 3px rgba(20, 23, 31, .08);
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #14161b;
      --panel: #1b1e25;
      --text: #e9ecf2;
      --muted: #99a1b0;
      --line: #2b2f38;
      --accent: #6f9bff;
      --new: #6ee7a8;
      --new-bg: #12352a;
      --shadow: none;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 28px 20px 60px;
    background: var(--bg); color: var(--text);
    font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }
  .wrap { max-width: 1180px; margin: 0 auto; }
  h1 { margin: 0 0 6px; font-size: 26px; letter-spacing: -.02em; }
  .sub { color: var(--muted); margin: 0 0 22px; font-size: 14px; }
  .stats { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 22px; }
  .stat {
    background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
    padding: 12px 16px; min-width: 130px; box-shadow: var(--shadow);
  }
  .stat b { display: block; font-size: 22px; letter-spacing: -.02em; }
  .stat span { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .05em; }
  .controls { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 16px; }
  input, select {
    font: inherit; padding: 9px 12px; border-radius: 8px;
    border: 1px solid var(--line); background: var(--panel); color: var(--text);
  }
  input { flex: 1 1 260px; }
  .tablewrap {
    background: var(--panel); border: 1px solid var(--line); border-radius: 12px;
    overflow-x: auto; box-shadow: var(--shadow);
  }
  table { border-collapse: collapse; width: 100%; min-width: 860px; }
  th, td { padding: 11px 14px; text-align: left; border-bottom: 1px solid var(--line); }
  th {
    position: sticky; top: 0; background: var(--panel); z-index: 1;
    font-size: 12px; text-transform: uppercase; letter-spacing: .05em;
    color: var(--muted); cursor: pointer; white-space: nowrap; user-select: none;
  }
  th:hover { color: var(--text); }
  th .arrow { opacity: .45; font-size: 10px; }
  tbody tr:last-child td { border-bottom: none; }
  tbody tr:hover { background: color-mix(in srgb, var(--accent) 6%, transparent); }
  td.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
  a { color: var(--accent); text-decoration: none; }
  a:hover { text-decoration: underline; }
  .addr { color: var(--muted); font-size: 13px; }
  .tag {
    display: inline-block; padding: 2px 7px; border-radius: 999px;
    font-size: 11px; font-weight: 600; background: var(--new-bg); color: var(--new);
  }
  .tag.plain { background: transparent; color: var(--muted); font-weight: 400; }
  .empty { padding: 40px; text-align: center; color: var(--muted); }
  footer { margin-top: 18px; color: var(--muted); font-size: 13px; }
</style>
</head>
<body>
<div class="wrap">
  <h1>Lejeboliger i København</h1>
  <p class="sub">5+ værelser · opdateret automatisk hver dag kl. 18:00 · senest genereret __GENERATED__</p>

  <div class="stats">
    <div class="stat"><b>__TOTAL__</b><span>Boliger i alt</span></div>
    <div class="stat"><b>__NEW__</b><span>Nye __LATEST__</span></div>
    <div class="stat"><b id="shown">0</b><span>Vist nu</span></div>
  </div>

  <div class="controls">
    <input id="q" type="search" placeholder="Søg i adresse, navn eller bydel…" autocomplete="off">
    <select id="site"><option value="">Alle udlejere</option></select>
    <select id="dele">
      <option value="">Delevenlig: alle</option>
      <option value="ja">Kun bekræftet delevenlig</option>
      <option value="ukendt">Ikke oplyst</option>
    </select>
  </div>

  <div class="tablewrap">
    <table>
      <thead><tr>
        <th data-key="date">Fundet <span class="arrow">▼</span></th>
        <th data-key="name">Bolig <span class="arrow"></span></th>
        <th data-key="site">Udlejer <span class="arrow"></span></th>
        <th data-key="rooms" class="num">Vær. <span class="arrow"></span></th>
        <th data-key="area" class="num">m² <span class="arrow"></span></th>
        <th data-key="price" class="num">Husleje <span class="arrow"></span></th>
        <th data-key="delevenlig">Delevenlig <span class="arrow"></span></th>
      </tr></thead>
      <tbody id="rows"></tbody>
    </table>
    <div class="empty" id="empty" hidden>Ingen boliger matcher filtrene.</div>
  </div>

  <footer>Kilde: <a href="listings.csv">listings.csv</a> · «Delevenlig» vises kun når udlejeren selv oplyser det.</footer>
</div>

<script>
const DATA = __DATA__;
const LATEST = "__LATEST__";
let sortKey = "date", sortDir = -1;

const daFmt = new Intl.NumberFormat("da-DK");
const fmt = (value, suffix) => value === null ? "–" : daFmt.format(value) + (suffix || "");

const siteSelect = document.getElementById("site");
[...new Set(DATA.map(item => item.site))].sort().forEach(site => {
  siteSelect.add(new Option(site, site));
});

function visible() {
  const query = document.getElementById("q").value.trim().toLowerCase();
  const site = siteSelect.value;
  const dele = document.getElementById("dele").value;
  return DATA.filter(item => {
    if (site && item.site !== site) return false;
    if (dele && item.delevenlig !== dele) return false;
    if (!query) return true;
    return [item.name, item.address, item.city, item.site, item.postal]
      .join(" ").toLowerCase().includes(query);
  });
}

function compare(a, b) {
  const x = a[sortKey], y = b[sortKey];
  if (x === null && y === null) return 0;
  if (x === null) return 1;          // unknowns sink regardless of direction
  if (y === null) return -1;
  if (typeof x === "number" && typeof y === "number") return (x - y) * sortDir;
  return String(x).localeCompare(String(y), "da") * sortDir;
}

function render() {
  const rows = visible().sort(compare);
  document.getElementById("shown").textContent = rows.length;
  document.getElementById("empty").hidden = rows.length > 0;
  document.getElementById("rows").innerHTML = rows.map(item => `
    <tr>
      <td>${item.date}${item.date === LATEST ? ' <span class="tag">ny</span>' : ""}</td>
      <td>
        <a href="${item.url}" target="_blank" rel="noopener">${escapeHtml(item.name)}</a>
        ${item.address && item.address !== item.name ? `<div class="addr">${escapeHtml(item.address)}</div>` : ""}
      </td>
      <td>${escapeHtml(item.site)}</td>
      <td class="num">${item.rooms === null ? "–" : daFmt.format(item.rooms)}</td>
      <td class="num">${fmt(item.area)}</td>
      <td class="num">${item.price === null ? "–" : daFmt.format(item.price) + " kr."}</td>
      <td>${item.delevenlig === "ja"
            ? '<span class="tag">ja</span>'
            : `<span class="tag plain">${escapeHtml(item.delevenlig)}</span>`}</td>
    </tr>`).join("");
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, character => (
    {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[character]
  ));
}

document.querySelectorAll("th[data-key]").forEach(header => {
  header.addEventListener("click", () => {
    const key = header.dataset.key;
    sortDir = key === sortKey ? -sortDir : (key === "date" ? -1 : 1);
    sortKey = key;
    document.querySelectorAll("th .arrow").forEach(arrow => arrow.textContent = "");
    header.querySelector(".arrow").textContent = sortDir === 1 ? "▲" : "▼";
    render();
  });
});
["q", "site", "dele"].forEach(id =>
  document.getElementById(id).addEventListener("input", render));

render();
</script>
</body>
</html>
"""
