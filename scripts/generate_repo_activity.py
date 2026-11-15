#!/usr/bin/env python3
"""Generate a combined commit-activity SVG for all owned repositories."""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.sax.saxutils as xml
from collections import Counter
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TOKEN = os.environ["GITHUB_TOKEN"]
USERNAME = os.environ.get("GITHUB_USERNAME", "farinaahamed06gif")
API = "https://api.github.com"
TZ = ZoneInfo("Asia/Kolkata")
HEADERS = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {TOKEN}",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "profile-repository-activity-dashboard",
}

def api_get(path, params=None):
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 409:
                return []
            if exc.code in (403, 429) and attempt < 3:
                time.sleep(2 ** (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    return []

def paged(path, params=None):
    page = 1
    while True:
        query = dict(params or {})
        query.update({"per_page": 100, "page": page})
        items = api_get(path, query)
        if not isinstance(items, list) or not items:
            break
        for item in items:
            yield item
        if len(items) < 100:
            break
        page += 1

def main():
    repositories = []
    for repo in paged("/user/repos", {"affiliation": "owner", "sort": "updated"}):
        owner = (repo.get("owner") or {}).get("login", "").lower()
        if owner == USERNAME.lower() and not repo.get("archived", False):
            repositories.append(repo)

    hour_counts = Counter()
    repo_counts = []
    total_commits = 0
    scanned_branches = 0

    for repo in repositories:
        full_name = repo["full_name"]
        repo_shas = set()
        branches = list(paged(f"/repos/{full_name}/branches"))
        if not branches and repo.get("default_branch"):
            branches = [{"name": repo["default_branch"]}]

        for branch in branches:
            branch_name = branch["name"]
            scanned_branches += 1
            encoded_branch = urllib.parse.quote(branch_name, safe="")
            try:
                commits = paged(
                    f"/repos/{full_name}/commits",
                    {"author": USERNAME, "sha": branch_name},
                )
                for item in commits:
                    sha = item.get("sha")
                    if not sha or sha in repo_shas:
                        continue
                    repo_shas.add(sha)
                    date_text = ((item.get("commit") or {}).get("author") or {}).get("date")
                    if not date_text:
                        continue
                    date = datetime.fromisoformat(date_text.replace("Z", "+00:00"))
                    hour_counts[date.astimezone(TZ).hour] += 1
            except urllib.error.HTTPError as exc:
                print(f"Skipping {full_name} branch {branch_name}: HTTP {exc.code}")

        count = len(repo_shas)
        total_commits += count
        repo_counts.append((repo.get("name", full_name), count))

    repo_counts.sort(key=lambda item: (-item[1], item[0].lower()))
    active_repos = sum(1 for _, count in repo_counts if count > 0)
    updated = datetime.now(timezone.utc).astimezone(TZ).strftime("%d %b %Y · %I:%M %p IST")

    width, height = 1120, 650
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<defs><linearGradient id="bar" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#b58aff"/><stop offset="100%" stop-color="#7650c8"/></linearGradient></defs>',
        '<rect width="100%" height="100%" rx="18" fill="#151421"/>',
        '<text x="42" y="54" fill="#ff2e88" font-family="Arial,sans-serif" font-size="27" font-weight="700">All-Repositories Commit Activity</text>',
        f'<text x="42" y="82" fill="#a9a6bd" font-family="Arial,sans-serif" font-size="14">Combined activity across your owned repositories · Updated {xml.escape(updated)}</text>',
    ]

    # Summary metric cards
    metrics = [
        ("TOTAL COMMITS", f"{total_commits:,}"),
        ("REPOSITORIES SCANNED", f"{len(repositories):,}"),
        ("ACTIVE REPOSITORIES", f"{active_repos:,}"),
    ]
    card_x = [42, 405, 768]
    for (label, value), x in zip(metrics, card_x):
        parts.extend([
            f'<rect x="{x}" y="110" width="330" height="94" rx="12" fill="#201d30" stroke="#343047"/>',
            f'<text x="{x+22}" y="143" fill="#00e5ff" font-family="Arial,sans-serif" font-size="13" font-weight="700">{label}</text>',
            f'<text x="{x+22}" y="184" fill="#ffffff" font-family="Arial,sans-serif" font-size="31" font-weight="700">{value}</text>',
        ])

    # Commits by hour chart
    parts.extend([
        '<text x="42" y="252" fill="#ffffff" font-family="Arial,sans-serif" font-size="19" font-weight="700">Commits by Hour · IST (UTC+05:30)</text>',
        '<text x="42" y="274" fill="#a9a6bd" font-family="Arial,sans-serif" font-size="12">Commit author timestamps converted to India Standard Time</text>',
    ])
    plot_x, plot_y, plot_w, plot_h = 66, 310, 1000, 205
    max_count = max(hour_counts.values(), default=0)
    max_scale = max(1, max_count)
    for tick in range(5):
        y = plot_y + plot_h - (plot_h * tick / 4)
        val = round(max_scale * tick / 4)
        parts.append(f'<line x1="{plot_x}" y1="{y:.1f}" x2="{plot_x+plot_w}" y2="{y:.1f}" stroke="#393449" stroke-width="1"/>')
        parts.append(f'<text x="{plot_x-13}" y="{y+4:.1f}" text-anchor="end" fill="#b8b5c9" font-family="Arial,sans-serif" font-size="11">{val}</text>')

    gap = 8
    bar_w = (plot_w - gap * 23) / 24
    for hour in range(24):
        count = hour_counts[hour]
        bar_h = (count / max_scale) * (plot_h - 8) if count else 0
        x = plot_x + hour * (bar_w + gap)
        y = plot_y + plot_h - bar_h
        if count:
            parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" rx="4" fill="url(#bar)"/>')
            if count == max_count:
                parts.append(f'<text x="{x+bar_w/2:.1f}" y="{y-8:.1f}" text-anchor="middle" fill="#ffffff" font-family="Arial,sans-serif" font-size="11">{count}</text>')
        parts.append(f'<text x="{x+bar_w/2:.1f}" y="{plot_y+plot_h+23}" text-anchor="middle" fill="#b8b5c9" font-family="Arial,sans-serif" font-size="11">{hour:02d}</text>')
    parts.append(f'<text x="{plot_x+plot_w/2}" y="565" text-anchor="middle" fill="#00e5ff" font-family="Arial,sans-serif" font-size="12">Hour of day (IST)</text>')

    # Repository-wise ranking
    parts.append('<text x="42" y="605" fill="#ffffff" font-family="Arial,sans-serif" font-size="17" font-weight="700">Repository activity</text>')
    # Compact top five repository labels along the footer
    top = repo_counts[:5]
    if top:
        max_repo = max(count for _, count in top) or 1
        x_positions = [42, 260, 478, 696, 914]
        for (name, count), x in zip(top, x_positions):
            short_name = name if len(name) <= 19 else name[:17] + "…"
            parts.append(f'<text x="{x}" y="630" fill="#c9c6d8" font-family="Arial,sans-serif" font-size="11">{xml.escape(short_name)} · {count:,}</text>')
    else:
        parts.append('<text x="42" y="630" fill="#c9c6d8" font-family="Arial,sans-serif" font-size="12">No authored commits were found in the accessible owned repositories yet.</text>')

    parts.append('</svg>')
    os.makedirs("assets", exist_ok=True)
    with open("assets/all-repositories-activity.svg", "w", encoding="utf-8") as file:
        file.write("\n".join(parts))
    print(f"Generated dashboard: {len(repositories)} repositories, {total_commits} commits, {scanned_branches} branches.")

if __name__ == "__main__":
    main()
