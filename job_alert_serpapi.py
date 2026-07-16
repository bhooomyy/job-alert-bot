"""
Separate daily-run script for SerpAPI (Google Jobs aggregator covering
LinkedIn, Indeed, Glassdoor). Kept isolated from job_alert.py (which runs
every 3h) since SerpAPI's free tier only allows 100 searches/month —
running this once/day keeps us at ~30/month, safely under the limit.

Reuses the same filtering logic (title tiers, freshness, agency blocking)
by importing from job_alert.py, so results are scored identically.
"""

import os
import sys

# Import everything from the main script so filtering logic stays identical
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from job_alert import (
    fetch_serpapi_jobs, passes_filters, is_fresh_job, send_telegram,
    load_seen, save_seen, SEARCH_KEYWORDS, DEBUG
)


def main():
    seen = load_seen()
    new_alerts = 0
    checked = 0

    all_jobs = []
    # Only 1 combined query per run to respect SerpAPI's free tier
    # (100 searches/month ÷ 30 days = ~3/day safe budget, using 1 to be conservative)
    all_jobs.extend(fetch_serpapi_jobs(query="data analyst OR data engineer OR analytics engineer"))

    print(f"SerpAPI fetched {len(all_jobs)} total job listings.")

    for job in all_jobs:
        job_id = job["id"]
        if job_id in seen:
            continue

        checked += 1
        title = job["title"]
        desc = job.get("description", "")
        location = job.get("location", {}).get("display_name", "")
        company = job.get("company", {}).get("display_name", "Unknown")
        link = job["redirect_url"]
        created = job.get("created")

        if not is_fresh_job(created):
            seen.add(job_id)
            if DEBUG:
                print(f"[stale] posted {created} | {title} @ {company}")
            continue

        ok, score = passes_filters(title, desc, location, company, title_only_source=False)

        if DEBUG:
            status = "PASS" if ok else "reject"
            print(f"[{status}] score={score} | {title} @ {company} | {location}")

        seen.add(job_id)

        if ok:
            msg = (
                f"🎯 <b>New job matching your skills!</b> (via LinkedIn/Indeed/Glassdoor)\n\n"
                f"📌 <b>{title}</b>\n"
                f"🏢 {company}\n"
                f"📍 {location}\n"
                f"⭐ Match score: {score}\n\n"
                f"{link}"
            )
            send_telegram(msg)
            new_alerts += 1

    save_seen(seen)
    print(f"Done. Checked {checked} new jobs, {new_alerts} alerts sent.")


if __name__ == "__main__":
    main()
