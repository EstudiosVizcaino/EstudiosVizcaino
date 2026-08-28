#!/usr/bin/env python3
"""Generate assets/rhythm.svg — when I actually write code.

Buckets every commit I have authored, across all of my public repos, by
weekday and hour in Madrid local time, and draws the result as a punch card.
Run by .github/workflows/telemetry.yml alongside the stats panel.

All repos (default):  python3 scripts/rhythm.py
    Discovers my non-fork repos from the GitHub API. With a personal access
    token that carries repo scope this includes my private repos; with the
    default Actions token, or none, it is public repos only. Either way the
    panel shows nothing but aggregate counts per weekday and hour — no repo
    name, message or diff from a private repo is read or drawn.

Specific repos:       python3 scripts/rhythm.py --repos Minishell,philo
    Useful for a quick local render without walking every repo.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Madrid")
except Exception:
    TZ = timezone.utc

USER = "EstudiosVizcaino"
OUT = os.path.join(os.path.dirname(__file__), "..", "assets", "rhythm.svg")

CYAN, AMBER, TEXT, MUTED = "#38e1ff", "#ffb648", "#cfe8ff", "#6f8aa8"
GRID = "#16243a"          # colour of an hour with no commits in it
DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
MAX_PAGES = 10            # up to 1000 commits per repo

# night is the block a day job would not cover — used for the AFTER DARK tile
NIGHT = set(range(21, 24)) | set(range(0, 6))


def gh(url):
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json", "User-Agent": USER})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


# ------------------------------------------------------------------ collect
def paged(url):
    """Walk a paginated collection endpoint to the end."""
    out = []
    for page in range(1, 11):
        batch = gh(f"{url}&page={page}")
        out += batch
        if len(batch) < 100:
            break
    return out


def repo_names():
    """My non-fork repos, and whether private ones are in the list.

    /user/repos answers for the authenticated user and can include private
    repos, but only for a personal access token with repo scope. The default
    Actions token is scoped to this one repository and is rejected, so fall
    back to the public listing and say so on the panel rather than silently
    reporting a smaller number.
    """
    if os.environ.get("GITHUB_TOKEN"):
        try:
            repos = paged("https://api.github.com/user/repos"
                          "?per_page=100&affiliation=owner&visibility=all")
            return [r["name"] for r in repos if not r["fork"]], True
        except urllib.error.HTTPError as e:
            if e.code not in (401, 403):
                raise
    repos = paged(f"https://api.github.com/users/{USER}/repos?per_page=100&type=owner")
    return [r["name"] for r in repos if not r["fork"]], False


def branch_names(repo):
    """Every branch in one repo."""
    out = []
    for page in range(1, 6):
        try:
            batch = gh(f"https://api.github.com/repos/{USER}/{repo}/branches"
                       f"?per_page=100&page={page}")
        except urllib.error.HTTPError as e:
            if e.code in (404, 409):     # gone, or empty repo with no branches
                return out
            raise
        out += [b["name"] for b in batch]
        if len(batch) < 100:
            break
    return out


def commit_times(repo):
    """Every commit I authored in one repo, as Madrid-local datetimes.

    /commits walks a single branch and defaults to the default branch, so
    anything worked on and never merged would be invisible. Walk every
    branch instead and key by SHA: branches overlap almost entirely, and
    without the dedupe a commit reachable from ten branches counts ten times.
    """
    seen = {}
    for branch in branch_names(repo):
        for page in range(1, MAX_PAGES + 1):
            url = (f"https://api.github.com/repos/{USER}/{repo}/commits"
                   f"?author={USER}&sha={branch}&per_page=100&page={page}")
            try:
                batch = gh(url)
            except urllib.error.HTTPError as e:
                if e.code in (404, 409):
                    break
                raise
            for c in batch:
                stamp = c["commit"]["author"]["date"]
                # Commits made on github.com come back as "...Z"; commits
                # pushed from a git client keep the offset they were authored
                # with ("...+02:00"). Both are the same instant, so normalise
                # and let zoneinfo apply the right DST offset per commit,
                # not a flat +1/+2.
                when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                seen[c["sha"]] = when.astimezone(TZ)
            if len(batch) < 100:
                break
    return list(seen.values())


def collect(repos):
    grid = {(d, h): 0 for d in range(7) for h in range(24)}
    total = 0
    for repo in repos:
        for when in commit_times(repo):
            grid[(when.weekday(), when.hour)] += 1
            total += 1
    return grid, total


# ----------------------------------------------------------------- rendering
def blend(ratio):
    """Cyan for an ordinary hour, amber for a peak one.

    Two flat colours rather than a gradient between them: interpolating
    cyan to amber in RGB passes through a muddy green that is off-palette
    and reads as a third category. Size and opacity carry the magnitude.
    """
    return AMBER if ratio > 0.7 else CYAN


def tile(x, y, num, label):
    return (f'<text x="{x}" y="{y}" font-size="30" font-weight="700" fill="{AMBER}" '
            f'filter="url(#rg)" letter-spacing="2">{num}</text>'
            f'<text x="{x}" y="{y + 20}" font-size="10" letter-spacing="4" fill="{MUTED}">{label}</text>')


def render(grid, total, private=False):
    peak = max(grid.values()) or 1

    by_hour = {h: sum(grid[(d, h)] for d in range(7)) for h in range(24)}
    by_day = {d: sum(grid[(d, h)] for h in range(24)) for d in range(7)}
    peak_hour = max(by_hour, key=by_hour.get) if total else 0
    peak_day = max(by_day, key=by_day.get) if total else 0
    after_dark = sum(v for h, v in by_hour.items() if h in NIGHT)

    tiles = "".join(tile(40 + i * 195, 96, num, label) for i, (num, label) in enumerate([
        (f"{peak_hour:02d}:00", "PEAK HOUR"),
        (DAYS[peak_day], "BUSIEST DAY"),
        (f"{round(100 * after_dark / total) if total else 0}%", "AFTER DARK"),
        (str(total), "COMMITS"),
    ]))

    x0, top, pitch_x, pitch_y = 80, 176, 29.6, 22
    cells, hours, days = [], [], []

    for h in range(24):
        cx = x0 + h * pitch_x
        hours.append(f'<text x="{cx:.1f}" y="160" text-anchor="middle" font-size="9" '
                     f'letter-spacing=".5" fill="{MUTED}">{h:02d}</text>')
        for d in range(7):
            cy = top + d * pitch_y
            n = grid[(d, h)]
            if n == 0:
                cells.append(f'<circle cx="{cx:.1f}" cy="{cy}" r="1.6" fill="{GRID}"/>')
                continue
            ratio = n / peak
            r = 2.4 + 7.6 * ratio ** 0.55
            cells.append(f'<circle cx="{cx:.1f}" cy="{cy}" r="{r:.1f}" fill="{blend(ratio)}" '
                         f'opacity="{0.45 + 0.55 * ratio:.2f}" filter="url(#rd)"/>')

    for d in range(7):
        days.append(f'<text x="60" y="{top + d * pitch_y + 3.5}" text-anchor="end" font-size="9" '
                    f'letter-spacing="2" fill="{MUTED}">{DAYS[d]}</text>')

    height = 372
    sync = datetime.now(TZ).date().isoformat()
    scope = " IN PUBLIC AND PRIVATE REPOS" if private else " IN PUBLIC REPOS"

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 830 {height}" font-family="'Segoe UI', system-ui, sans-serif" role="img" aria-label="Commit rhythm for {USER} — {total} commits bucketed by weekday and hour, Madrid local time">
  <defs>
    <filter id="rg" x="-50%" y="-50%" width="200%" height="200%">
      <feGaussianBlur stdDeviation="2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="rd" x="-120%" y="-120%" width="340%" height="340%">
      <feGaussianBlur stdDeviation="1.6" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <pattern id="rscan" width="4" height="4" patternUnits="userSpaceOnUse">
      <rect width="4" height="4" fill="#05070d"/><rect y="3" width="4" height="1" fill="#0a1220"/>
    </pattern>
  </defs>
  <rect width="830" height="{height}" fill="url(#rscan)"/>
  <g stroke="{CYAN}" stroke-opacity=".55" stroke-width="1.5" fill="none">
    <path d="M10 30V10h20"/><path d="M800 10h20v20"/><path d="M10 {height - 30}v20h20"/><path d="M820 {height - 30}v20h-20"/>
  </g>
  <circle cx="46" cy="31" r="4" fill="{AMBER}">
    <animate attributeName="opacity" values="1;.25;1" dur="2.4s" repeatCount="indefinite"/>
  </circle>
  <text x="60" y="36" font-size="13" letter-spacing="6" fill="{CYAN}" filter="url(#rg)">COMMIT RHYTHM <tspan fill="{AMBER}">// WHEN I WRITE CODE</tspan></text>
  <text x="790" y="36" text-anchor="end" font-size="11" letter-spacing="3" fill="{MUTED}">{sync}</text>
  <line x1="40" y1="52" x2="790" y2="52" stroke="{CYAN}" stroke-opacity=".22"/>
  {tiles}
  <text x="40" y="140" font-size="10" letter-spacing="4" fill="{MUTED}">HOUR OF DAY <tspan fill="{CYAN}" letter-spacing="2">· EUROPE/MADRID</tspan></text>
  {''.join(hours)}
  {''.join(days)}
  {''.join(cells)}
  <text x="40" y="{height - 26}" font-size="9.5" letter-spacing="1.5" fill="{MUTED}">EVERY COMMIT I HAVE AUTHORED{scope}, BUCKETED BY WEEKDAY AND HOUR <tspan fill="{CYAN}">▰</tspan> BIGGER AND WARMER = BUSIER</text>
  <rect x="0" y="0" width="830" height="2" fill="{CYAN}" opacity=".1">
    <animate attributeName="y" values="0;{height - 2};0" dur="16s" repeatCount="indefinite"/>
  </rect>
</svg>
'''


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--repos":
        repos, private = [r.strip() for r in sys.argv[2].split(",") if r.strip()], False
    else:
        repos, private = repo_names()
        # A fine-grained token expires (366 days at most). Without this check
        # the run would quietly fall back to public repos and publish a panel
        # showing a much smaller number, which is worse than failing: nobody
        # reads a green build's logs. Stop before overwriting the good panel.
        if os.environ.get("EXPECT_PRIVATE") == "1" and not private:
            sys.exit("STATS_TOKEN is set but private repos were unreachable — the "
                     "token has most likely expired, or lost Contents: Read-only. "
                     "Refusing to publish a panel that would undercount.")
    grid, total = collect(repos)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        f.write(render(grid, total, private))
    scope = "public + private" if private else "public only"
    print(f"wrote {os.path.normpath(OUT)} — {total} commits across "
          f"{len(repos)} repos ({scope})")


if __name__ == "__main__":
    main()
