#!/usr/bin/env python3
"""Generate assets/telemetry.svg — the profile README's stats panel.

Run by .github/workflows/telemetry.yml on a daily schedule so the numbers
stay fresh without depending on any third-party card service.

Live mode (default):   python3 scripts/telemetry.py
    Fetches public data from the GitHub API (set GITHUB_TOKEN to avoid
    rate limits — the Actions workflow passes it automatically).

Offline mode:          python3 scripts/telemetry.py --from-json repos.json [followers]
    Renders from a saved repo list instead of the API (used for the very
    first render; language shares fall back to primary-language counts).
"""
import json
import os
import re
import sys
import urllib.request
from datetime import date, datetime, timezone

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Madrid")
except Exception:
    TZ = timezone.utc

USER = "EstudiosVizcaino"
OUT = os.path.join(os.path.dirname(__file__), "..", "assets", "telemetry.svg")

CYAN, BLUE, AMBER, TEXT, MUTED = "#38e1ff", "#4a9eff", "#ffb648", "#cfe8ff", "#6f8aa8"

# Fixed colors keep the established languages stable between renders;
# any language not listed here is assigned automatically from PALETTE,
# so new repos in new languages always get a distinct color.
LANG_COLOR = {
    "C": CYAN, "C++": BLUE, "Shell": AMBER, "HTML": BLUE, "CSS": BLUE,
    "Python": "#9bd0ff", "JavaScript": "#ffd88a", "Makefile": MUTED,
}
PALETTE = [CYAN, AMBER, BLUE, "#9bd0ff", "#ffd88a", "#7ee8c7", "#c9a6ff", "#ff9d9d"]
MAX_LANGS = 4   # top languages shown individually; the rest fold into OTHER


def lang_colors(langs_ranked):
    """Assign each language a distinct palette color, honouring LANG_COLOR."""
    used = set()
    out = {}
    for lang in langs_ranked:
        c = LANG_COLOR.get(lang)
        if c is None or c in used:
            c = next((p for p in PALETTE if p not in used), MUTED)
        out[lang] = c
        used.add(c)
    return out


def gh(url, raw=False, data=None):
    req = urllib.request.Request(url, data=data, headers={
        "Accept": "application/vnd.github+json", "User-Agent": USER})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode() if raw else json.load(r)


# ---------------------------------------------------------------- repo stats
def collect_live():
    repos = [r for r in gh(f"https://api.github.com/users/{USER}/repos?per_page=100&type=owner")
             if not r["fork"]]
    langs = {}
    for r in repos:
        try:
            for lang, size in gh(r["languages_url"]).items():
                langs[lang] = langs.get(lang, 0) + size
        except Exception:
            if r.get("language"):
                langs[r["language"]] = langs.get(r["language"], 0) + 1
    user = gh(f"https://api.github.com/users/{USER}")
    return {
        "repos": len(repos),
        "stars": sum(r["stargazers_count"] for r in repos),
        "followers": user["followers"],
        "langs": langs,
    }


def collect_offline(path, followers):
    repos = [r for r in json.load(open(path)) if not r.get("fork")]
    langs = {}
    for r in repos:
        if r.get("language"):
            langs[r["language"]] = langs.get(r["language"], 0) + 1
    return {
        "repos": len(repos),
        "stars": sum(r.get("stargazers_count", 0) for r in repos),
        "followers": followers,
        "langs": langs,
    }


# ---------------------------------------------------------------- rendering
def tile(x, y, num, label):
    return (f'<text x="{x}" y="{y}" font-size="34" font-weight="700" fill="{AMBER}" '
            f'filter="url(#ga)" letter-spacing="2">{num}</text>'
            f'<text x="{x}" y="{y + 20}" font-size="10" letter-spacing="4" fill="{MUTED}">{label}</text>')


def render(d):
    total = sum(d["langs"].values()) or 1
    ranked = sorted(d["langs"].items(), key=lambda kv: -kv[1])
    top = ranked[:MAX_LANGS]
    other = total - sum(v for _, v in top)
    colors = lang_colors([lang for lang, _ in top])
    segs = [(lang, v / total, colors[lang]) for lang, v in top]
    if other > 0:
        segs.append(("OTHER", other / total, MUTED))

    primary = top[0][0] if top else "—"
    sync = datetime.now(TZ).date().isoformat()

    tiles = []
    for i, (num, label) in enumerate([
            (str(d["repos"]), "PUBLIC REPOS"),
            (primary.upper(), "TOP LANGUAGE"),
            (str(d["stars"]), "STARS"),
            (str(d["followers"]), "FOLLOWERS")]):
        tiles.append(tile(40 + i * 195, 112, num, label))

    # language allocation bar + single-line legend
    y = 156
    bar_w, x = 750, 40.0
    bar, items = [], []
    for lang, share, color in segs:
        w = share * bar_w
        bar.append(f'<rect x="{x:.1f}" y="{y + 8}" width="{max(w - 2, 1):.1f}" height="12" fill="{color}"/>')
        items.append(f'<tspan fill="{color}">▰</tspan> <tspan fill="{TEXT}">{lang.upper()}'
                     f'</tspan> <tspan fill="{MUTED}">{share * 100:.1f}%</tspan>')
        x += w
    legend = f'<text x="40" y="{y + 44}" font-size="12" letter-spacing="1">{"   ".join(items)}</text>'
    height = 220

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 830 {height}" font-family="'Segoe UI', system-ui, sans-serif" role="img" aria-label="GitHub activity for {USER}">
  <defs>
    <filter id="gc" x="-50%" y="-50%" width="200%" height="200%">
      <feGaussianBlur stdDeviation="2.5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="ga" x="-50%" y="-50%" width="200%" height="200%">
      <feGaussianBlur stdDeviation="2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <pattern id="scan" width="4" height="4" patternUnits="userSpaceOnUse">
      <rect width="4" height="4" fill="#05070d"/><rect y="3" width="4" height="1" fill="#0a1220"/>
    </pattern>
  </defs>
  <rect width="830" height="{height}" fill="url(#scan)"/>
  <g stroke="{CYAN}" stroke-opacity=".55" stroke-width="1.5" fill="none">
    <path d="M10 30V10h20"/><path d="M800 10h20v20"/><path d="M10 {height - 30}v20h20"/><path d="M820 {height - 30}v20h-20"/>
  </g>
  <circle cx="46" cy="31" r="4" fill="{AMBER}">
    <animate attributeName="opacity" values="1;.25;1" dur="2.4s" repeatCount="indefinite"/>
  </circle>
  <text x="60" y="36" font-size="13" letter-spacing="6" fill="{CYAN}" filter="url(#gc)">GITHUB ACTIVITY <tspan fill="{AMBER}">// UPDATED DAILY</tspan></text>
  <text x="790" y="36" text-anchor="end" font-size="11" letter-spacing="3" fill="{MUTED}">{sync}</text>
  <line x1="40" y1="52" x2="790" y2="52" stroke="{CYAN}" stroke-opacity=".22"/>
  {''.join(tiles)}
  <text x="40" y="{y}" font-size="10" letter-spacing="4" fill="{MUTED}">LANGUAGE BREAKDOWN</text>
  {''.join(bar)}
  {legend}
</svg>
'''


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--from-json":
        data = collect_offline(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 0)
    else:
        data = collect_live()
    svg = render(data)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        f.write(svg)
    print(f"wrote {os.path.normpath(OUT)} — {data['repos']} repos, "
          f"{len(data['langs'])} languages, synced {datetime.now(timezone.utc).isoformat()}")


if __name__ == "__main__":
    main()
