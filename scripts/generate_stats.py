#!/usr/bin/env python3
"""Generate self-hosted HUD-style stats SVGs for the GitHub profile README.

Uses only the GitHub REST API + GITHUB_TOKEN (or unauthenticated public data).
Writes:
  assets/stats.svg  - overview metrics
  assets/langs.svg  - top languages
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

USERNAME = os.environ.get("GH_USERNAME", "inajaf")
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"

# Language colors (subset of GitHub linguist palette)
LANG_COLORS = {
    "Go": "#00ADD8",
    "JavaScript": "#f1e05a",
    "TypeScript": "#3178c6",
    "Rust": "#dea584",
    "Python": "#3572A5",
    "Ruby": "#701516",
    "HTML": "#e34c26",
    "CSS": "#563d7c",
    "Shell": "#89e051",
    "Dockerfile": "#384d54",
    "Makefile": "#427819",
    "Svelte": "#ff3e00",
    "Vue": "#41b883",
    "Java": "#b07219",
    "C": "#555555",
    "C++": "#f34b7d",
    "Swift": "#F05138",
}


def api_get(path: str, accept: str = "application/vnd.github+json") -> object:
    url = path if path.startswith("http") else f"https://api.github.com{path}"
    headers = {
        "Accept": accept,
        "User-Agent": f"{USERNAME}-profile-stats",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def api_get_all(path: str) -> list:
    """Paginate list endpoints (max 10 pages safety)."""
    items: list = []
    url = f"https://api.github.com{path}"
    sep = "&" if "?" in path else "?"
    if "per_page=" not in path:
        url = f"https://api.github.com{path}{sep}per_page=100"
    for _ in range(10):
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{USERNAME}-profile-stats",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if TOKEN:
            headers["Authorization"] = f"Bearer {TOKEN}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as resp:
            chunk = json.loads(resp.read().decode())
            if not isinstance(chunk, list):
                return chunk  # type: ignore[return-value]
            items.extend(chunk)
            link = resp.headers.get("Link", "")
        next_url = None
        for part in link.split(","):
            if 'rel="next"' in part:
                next_url = part[part.find("<") + 1 : part.find(">")]
                break
        if not next_url:
            break
        url = next_url
    return items


def esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def fetch_data() -> dict:
    user = api_get(f"/users/{USERNAME}")
    repos = api_get_all(f"/users/{USERNAME}/repos?type=owner&sort=updated")
    # exclude forks for language/stars rollup of "own" work
    own = [r for r in repos if not r.get("fork")]

    stars = sum(r.get("stargazers_count", 0) for r in own)
    forks = sum(r.get("forks_count", 0) for r in own)

    lang_bytes: dict[str, int] = defaultdict(int)
    for r in own:
        if r.get("size", 0) == 0 and not r.get("language"):
            continue
        try:
            langs = api_get(f"/repos/{USERNAME}/{r['name']}/languages")
            if isinstance(langs, dict):
                for name, n in langs.items():
                    lang_bytes[name] += int(n)
        except urllib.error.HTTPError:
            if r.get("language"):
                lang_bytes[r["language"]] += max(r.get("size", 1), 1) * 1024

    # approximate public events for a light activity signal
    try:
        events = api_get_all(f"/users/{USERNAME}/events/public")
    except urllib.error.HTTPError:
        events = []
    push_events = [e for e in events if e.get("type") == "PushEvent"]
    recent_commits = 0
    for e in push_events:
        recent_commits += len(e.get("payload", {}).get("commits") or [])

    total_lang = sum(lang_bytes.values()) or 1
    top_langs = sorted(lang_bytes.items(), key=lambda x: x[1], reverse=True)[:6]
    top_langs_pct = [(n, round(100 * b / total_lang, 1), b) for n, b in top_langs]

    return {
        "name": user.get("name") or USERNAME,
        "login": user.get("login", USERNAME),
        "public_repos": user.get("public_repos", 0),
        "followers": user.get("followers", 0),
        "following": user.get("following", 0),
        "stars": stars,
        "forks": forks,
        "own_repos": len(own),
        "recent_commits": recent_commits,
        "top_langs": top_langs_pct,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }


def render_stats(data: dict) -> str:
    metrics = [
        ("REPOS", str(data["public_repos"])),
        ("STARS", str(data["stars"])),
        ("FOLLOWERS", str(data["followers"])),
        ("FORKS", str(data["forks"])),
        ("RECENT PUSH", str(data["recent_commits"])),
        ("OWN REPOS", str(data["own_repos"])),
    ]
    cards = []
    # 2x3 grid
    positions = [
        (24, 70),
        (172, 70),
        (320, 70),
        (24, 155),
        (172, 155),
        (320, 155),
    ]
    for (label, value), (x, y) in zip(metrics, positions):
        cards.append(
            f"""
  <g transform="translate({x},{y})">
    <rect width="136" height="72" rx="10" fill="rgba(13,19,33,0.72)" stroke="rgba(0,173,216,0.18)"/>
    <text x="14" y="28" font-family="ui-monospace, Menlo, Monaco, monospace" font-size="10" fill="#8b96ad" letter-spacing="1.2">{esc(label)}</text>
    <text x="14" y="54" font-family="ui-sans-serif, system-ui, sans-serif" font-size="26" font-weight="700" fill="#e6edf3">{esc(value)}</text>
  </g>"""
        )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="480" height="250" viewBox="0 0 480 250" role="img" aria-label="GitHub stats for {esc(data['login'])}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#0b1220"/>
      <stop offset="100%" stop-color="#0f1724"/>
    </linearGradient>
  </defs>
  <rect width="480" height="250" rx="14" fill="url(#bg)" stroke="rgba(148,163,184,0.16)"/>
  <circle cx="22" cy="24" r="4" fill="#00ADD8"/>
  <text x="36" y="28" font-family="ui-monospace, Menlo, Monaco, monospace" font-size="12" fill="#8b96ad" letter-spacing="1.5">GITHUB STATS</text>
  <text x="456" y="28" text-anchor="end" font-family="ui-monospace, Menlo, Monaco, monospace" font-size="11" fill="#00ADD8">@{esc(data['login'])}</text>
  <line x1="16" y1="44" x2="464" y2="44" stroke="rgba(0,173,216,0.25)" stroke-width="1"/>
  {''.join(cards)}
  <text x="24" y="242" font-family="ui-monospace, Menlo, Monaco, monospace" font-size="9" fill="#5b6478">updated {esc(data['generated_at'])} · self-hosted</text>
</svg>
"""


def render_langs(data: dict) -> str:
    langs = data["top_langs"]
    if not langs:
        langs = [("Unknown", 100.0, 1)]

    bars = []
    y = 68
    max_bar = 320
    for name, pct, _bytes in langs:
        color = LANG_COLORS.get(name, "#00ADD8")
        w = max(8, int(max_bar * (pct / 100)))
        bars.append(
            f"""
  <text x="24" y="{y}" font-family="ui-sans-serif, system-ui, sans-serif" font-size="13" fill="#e6edf3">{esc(name)}</text>
  <text x="456" y="{y}" text-anchor="end" font-family="ui-monospace, Menlo, Monaco, monospace" font-size="12" fill="#8b96ad">{pct}%</text>
  <rect x="24" y="{y + 8}" width="{max_bar}" height="8" rx="4" fill="rgba(148,163,184,0.10)"/>
  <rect x="24" y="{y + 8}" width="{w}" height="8" rx="4" fill="{color}"/>
"""
        )
        y += 36

    height = max(200, 60 + len(langs) * 36 + 30)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="480" height="{height}" viewBox="0 0 480 {height}" role="img" aria-label="Top languages for {esc(data['login'])}">
  <defs>
    <linearGradient id="bg2" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#0b1220"/>
      <stop offset="100%" stop-color="#0f1724"/>
    </linearGradient>
  </defs>
  <rect width="480" height="{height}" rx="14" fill="url(#bg2)" stroke="rgba(148,163,184,0.16)"/>
  <circle cx="22" cy="24" r="4" fill="#5dc9e2"/>
  <text x="36" y="28" font-family="ui-monospace, Menlo, Monaco, monospace" font-size="12" fill="#8b96ad" letter-spacing="1.5">TOP LANGUAGES</text>
  <text x="456" y="28" text-anchor="end" font-family="ui-monospace, Menlo, Monaco, monospace" font-size="11" fill="#5dc9e2">by bytes</text>
  <line x1="16" y1="44" x2="464" y2="44" stroke="rgba(93,201,226,0.25)" stroke-width="1"/>
  {''.join(bars)}
  <text x="24" y="{height - 12}" font-family="ui-monospace, Menlo, Monaco, monospace" font-size="9" fill="#5b6478">updated {esc(data['generated_at'])} · self-hosted</text>
</svg>
"""


def main() -> int:
    ASSETS.mkdir(parents=True, exist_ok=True)
    try:
        data = fetch_data()
    except Exception as e:
        print(f"error fetching GitHub data: {e}", file=sys.stderr)
        return 1

    stats_path = ASSETS / "stats.svg"
    langs_path = ASSETS / "langs.svg"
    stats_path.write_text(render_stats(data), encoding="utf-8")
    langs_path.write_text(render_langs(data), encoding="utf-8")

    print(f"wrote {stats_path.relative_to(ROOT)}")
    print(f"wrote {langs_path.relative_to(ROOT)}")
    print(
        f"repos={data['public_repos']} stars={data['stars']} "
        f"langs={[n for n, _, _ in data['top_langs']]}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
