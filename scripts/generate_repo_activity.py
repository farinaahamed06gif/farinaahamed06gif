#!/usr/bin/env python3
"""Build a combined commits-by-hour dashboard from the user's public, non-fork repositories."""
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

USERNAME = os.environ.get("GITHUB_USERNAME", "farinaahamed06gif")
API = "https://api.github.com"
TZ = ZoneInfo("Asia/Kolkata")
HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "profile-repository-activity-dashboard",
}

def api_get(path, params=None):
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers=HEADERS)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code == 409:
                return []
            if error.code in (403, 429) and attempt < 4:
                time.sleep(2 ** (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == 4:
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
        yield from items
        if len(items) < 100:
            break
        page += 1

def main():
    # The workflow's built-in GITHUB_TOKEN can read public repositories.
    # Private repositories require a separately configured PAT with repo read access.
    repositories = []
    for repo in paged(f"/users/{USERNAME}/repos", {"type": "owner", "sort": "updated"}):
        if not repo.get("fork", False):
            repositories.append(repo)

    hour_counts = Counter()
    repo_counts = []
    total_commits = 0
    scanned_branches = 0
    errors = []

    for repo in repositories:
        full_name = repo["full_name"]
        repo_shas = set()
        branches = list(paged(f"/repos/{full_name}/branches"))
        if not branches and repo.get("default_branch"):
            branches = [{"name": repo["default_branch"]}]

        for branch in branches:
            branch_name = branch["name"]
            scanned_branches += 1
            try:
                for commit in paged(
                    f"/repos/{full_name}/commits",
                    {"author": USERNAME, "sha": branch_name},
                ):
                    sha = commit.get("sha")
                    if not sha or sha in repo_shas:
                        continue
                    date_text = ((commit.get("commit") or {}).get("author") or {}).get("date")
                    if not date_text:
                        continue
                    authored_at = datetime.fromisoformat(date_text.replace("Z", "+00:00"))
                    repo_shas.add(sha)
                    hour_counts[authored_at.astimezone(TZ).hour] += 1
            except urllib.error.HTTPError as error:
                errors.append(f"{full_name}/{branch_name}: HTTP {error.code}")

        count = len(repo_shas)
        total_commits += count
        repo_counts.append((repo.get("name", full_name), count))

    repo_counts.sort(key=lambda item: (-item[1], item[0].lower()))
    active_repos = sum(1 for _, count in repo_counts if count > 0)
    updated = datetime.now(timezone.utc).astimezone(TZ).strftime("%d %b %Y · %I:%M %p IST")

    width, height = 1120, 690
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<defs><linearGradient id="bar" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#b58aff"/><stop offset="100%" stop-color="#7650c8"/></linearGradient></defs>',
        '<rect width="100%" height="100%" rx="18" fill="#151421"/>',
        '<text x="42" y="52" fill="#ff2e88" font-family="Arial,sans-serif" font-size="27" font-weight="700">All-Repositories Commit Activity</text>',
        f'<text x="42" y="80" fill="#a9a6bd" font-family="Arial,sans-serif" font-size="14">Your public, non-fork repositories · Commit author time converted to IST · Updated {xml.escape(updated)}</text>',
    ]

    metrics = [
        ("TOTAL COMMITS", f"{total_commits:,}"),
        ("REPOSITORIES", f"{len(repositories):,}"),
        ("WITH COMMITS", f"{active_repos:,}"),
    ]
    for (label, value), x in zip(metrics, [42, 405, 768]):
        svg.extend([
            f'<rect x="{x}" y="105" width="330" height="92" rx="12" fill="#201d30" stroke="#343047"/>',
            f'<text x="{x+22}" y="138" fill="#00e5ff" font-family="Arial,sans-serif" font-size="13" font-weight="700">{label}</text>',
            f'<text x="{x+22}" y="178" fill="#ffffff" font-family="Arial,sans-serif" font-size="30" font-weight="700">{value}</text>',
        ])

    svg.extend([
        '<text x="42" y="245" fill="#ffffff" font-family="Arial,sans-serif" font-size="19" font-weight="700">Commits by Hour · IST (UTC+05:30)</text>',
        '<text x="42" y="267" fill="#a9a6bd" font-family="Arial,sans-serif" font-size="12">All scanned repositories combined · 24-hour clock</text>',
    ])

    plot_x, plot_y, plot_w, plot_h = 66, 302, 1000, 205
    max_count = max(hour_counts.values(), default=0)
    scale = max(1, max_count)
    for tick in range(5):
        y = plot_y + plot_h - plot_h * tick / 4
        value = round(scale * tick / 4)
        svg.append(f'<line x1="{plot_x}" y1="{y:.1f}" x2="{plot_x+plot_w}" y2="{y:.1f}" stroke="#393449"/>')
        svg.append(f'<text x="{plot_x-13}" y="{y+4:.1f}" text-anchor="end" fill="#b8b5c9" font-family="Arial,sans-serif" font-size="11">{value}</text>')

    gap = 8
    bar_w = (plot_w - gap * 23) / 24
    for hour in range(24):
        count = hour_counts[hour]
        bar_h = (count / scale) * (plot_h - 8) if count else 0
        x = plot_x + hour * (bar_w + gap)
        y = plot_y + plot_h - bar_h
        if count:
            svg.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" rx="4" fill="url(#bar)"/>')
            if count == max_count:
                svg.append(f'<text x="{x+bar_w/2:.1f}" y="{y-8:.1f}" text-anchor="middle" fill="#ffffff" font-family="Arial,sans-serif" font-size="11">{count}</text>')
        svg.append(f'<text x="{x+bar_w/2:.1f}" y="{plot_y+plot_h+22}" text-anchor="middle" fill="#b8b5c9" font-family="Arial,sans-serif" font-size="11">{hour:02d}</text>')
    svg.append(f'<text x="{plot_x+plot_w/2}" y="553" text-anchor="middle" fill="#00e5ff" font-family="Arial,sans-serif" font-size="12">Hour of day (IST)</text>')

    svg.append('<text x="42" y="595" fill="#ffffff" font-family="Arial,sans-serif" font-size="18" font-weight="700">Repository activity · Top 8</text>')
    for index, (name, count) in enumerate(repo_counts[:8]):
        col = index % 4
        row = index // 4
        x = 42 + col * 270
        y = 625 + row * 30
        label = name if len(name) <= 22 else name[:20] + "…"
        svg.append(f'<text x="{x}" y="{y}" fill="#c9c6d8" font-family="Arial,sans-serif" font-size="12">{xml.escape(label)}  ·  {count:,}</text>')

    if not repositories:
        svg.append('<text x="42" y="625" fill="#c9c6d8" font-family="Arial,sans-serif" font-size="12">No public, non-fork repositories were found.</text>')
    if errors:
        svg.append(f'<text x="42" y="677" fill="#e9b45c" font-family="Arial,sans-serif" font-size="10">Some branches could not be read: {len(errors)} (see workflow logs)</text>')
    svg.append('</svg>')

    os.makedirs("assets", exist_ok=True)
    with open("assets/all-repositories-activity.svg", "w", encoding="utf-8") as file:
        file.write("\n".join(svg))
    print(f"Generated combined dashboard: {len(repositories)} public repositories, {total_commits} commits, {scanned_branches} branches.")
    if errors:
        print("\n".join(errors))

if __name__ == "__main__":
    main()
