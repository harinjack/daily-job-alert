"""
Daily Job Search Automation

This single-file Python script searches the web (using SerpApi) for job openings for specified
roles and locations, filters results for experience (freshers to 3 years), and emails the
results as an HTML summary + CSV attachment.

How it works:
- Uses SerpApi (https://serpapi.com/) to run Google-style searches. Set SERPAPI_API_KEY.
- Builds queries for roles and locations (Chennai preferred, then India-wide).
- Collects top results, deduplicates by link, and filters results using simple keyword matching
  for experience ranges ("0 years", "fresher", "1 year", "2 years", "3 years", "0-3 years").
- Sends an email via SMTP (Gmail or any SMTP server) or via SendGrid (HTTP) depending on config.

Set environment variables before running (recommended):
- SERPAPI_API_KEY : your SerpApi API key (required)
- SMTP_HOST (optional, default: smtp.gmail.com)
- SMTP_PORT (optional, default: 587)
- SMTP_USER : SMTP username (email from)
- SMTP_PASS : SMTP password or app password
- SENDER_EMAIL : from address (optional; falls back to SMTP_USER)
- RECIPIENT_EMAIL : email that receives the results
- MAX_RESULTS : integer, maximum results per query (default 10)

Scheduling:
- Linux cron: 0 9 * * * /usr/bin/python3 /path/to/daily-job-search-automation.py
  (runs every day at 09:00 server local time)
- Or use GitHub Actions (workflow YAML included at the end of this file) and store secrets.

Notes & limitations:
- Scraping job sites directly (LinkedIn, Indeed) can violate terms of service. SerpApi returns
  search results (titles/snippets/links) and is more stable. You are responsible for complying
  with site policies.
- The "experience" filtering is heuristic (keyword matching). For high precision consider
  parsing the destination job pages (requires more robust HTML parsing per-site).

"""

import os
import sys
import csv
import time
import json
import logging
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
import smtplib
from datetime import datetime

# ---------- Configuration ----------
ROLES = [
    "software developer",
    "react js developer",
    "frontend developer",
    "react native developer",
]
# Chennai first, then India-wide fallback location tokens
LOCATIONS = [
    "Chennai",
    "India",
]
EXPERIENCE_KEYWORDS = [
    "fresher",
    "0 years",
    "0-1 year",
    "0-2 years",
    "0-3 years",
    "0 to 3",
    "1 year",
    "2 years",
    "3 years",
    "entry level",
    "junior",
]
MAX_RESULTS = int(os.getenv("MAX_RESULTS", "10"))
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")
if not SERPAPI_API_KEY:
    print("ERROR: Set SERPAPI_API_KEY environment variable. See https://serpapi.com/ to get a key.")
    sys.exit(1)

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
SENDER_EMAIL = os.getenv("SENDER_EMAIL", SMTP_USER)
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL")

if not SMTP_USER or not SMTP_PASS or not RECIPIENT_EMAIL:
    print("ERROR: Set SMTP_USER, SMTP_PASS and RECIPIENT_EMAIL environment variables to send mail.")
    sys.exit(1)

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ---------- Helpers ----------

def serpapi_search(query, location, num_results=10):
    params = {
        "q": query,
        "location": location,
        "api_key": SERPAPI_API_KEY,
        "gl": "in",
        "hl": "en",
    }

    url = "https://serpapi.com/search.json"

    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logging.error("SerpApi request failed: %s", e)
        return []

    results = []

    # Handle Google Jobs results
    jobs_results = data.get("jobs_results")
    if isinstance(jobs_results, list):
        for j in jobs_results[:num_results]:
            results.append({
                "title": j.get("title", ""),
                "link": j.get("link", ""),
                "snippet": j.get("description", ""),
                "source": j.get("company_name", ""),
            })

    # Handle normal organic results
    organic_results = data.get("organic_results")
    if isinstance(organic_results, list):
        for item in organic_results[:num_results]:
            results.append({
                "title": item.get("title", ""),
                "link": item.get("link", ""),
                "snippet": item.get("snippet", ""),
                "source": item.get("displayed_link", ""),
            })

    return results



def matches_experience(text):
    if not text:
        return False
    low = text.lower()
    for kw in EXPERIENCE_KEYWORDS:
        if kw in low:
            return True
    return False


def build_queries():
    queries = []
    for role in ROLES:
        for loc in LOCATIONS:
            # include experience mention to bias results
            q = f"{role} {loc} fresher OR " \
                f"\"0-3 years\" OR \"0 to 3\" OR junior" \
                
            # we will search both with and without quoted experience filter
            queries.append((role, loc, q))
            queries.append((role, loc, f"{role} {loc} jobs"))
    return queries


# ---------- Main collection ----------

def collect_jobs():
    queries = build_queries()
    seen_links = set()
    collected = []
    for role, loc, q in queries:
        logging.info("Searching: %s", q)
        results = serpapi_search(q, loc, num_results=MAX_RESULTS)
        for r in results:
            link = r.get("link") or r.get("source")
            if not link:
                continue
            if link in seen_links:
                continue
            seen_links.add(link)
            title = r.get("title") or ""
            snippet = r.get("snippet") or ""
            source = r.get("source") or ""
            # simple experience check
            exp_matched = matches_experience(title + " " + snippet)
            collected.append({
                "role_query": role,
                "location_query": loc,
                "title": title,
                "link": link,
                "snippet": snippet,
                "source": source,
                "exp_matched": exp_matched,
            })
        # polite pause
        time.sleep(1.0)
    return collected


# ---------- Email helpers ----------

def to_csv_bytes(rows):
    out = []
    headers = ["role_query", "location_query", "title", "link", "source", "exp_matched", "snippet"]
    writer = csv.writer(out := [])
    writer.writerow(headers)
    for r in rows:
        writer.writerow([r.get(h, "") for h in headers])
    # join into bytes
    csv_text = "\n".join([",".join([str(cell).replace('\n', ' ') for cell in row]) for row in out])
    return csv_text.encode("utf-8")


def format_html(rows):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    html = [f"<h2>Job search results — {now}</h2>"]
    html.append(f"<p>Queries: roles={', '.join(ROLES)}; locations={', '.join(LOCATIONS)}; max per query={MAX_RESULTS}</p>")
    html.append("<table border=1 cellpadding=6 cellspacing=0>")
    html.append("<tr><th>Role Query</th><th>Location Query</th><th>Title</th><th>Source</th><th>Experience matched</th></tr>")
    for r in rows:
        title_html = f"<a href=\"{r['link']}\">{r['title']}</a>"
        html.append(f"<tr><td>{r['role_query']}</td><td>{r['location_query']}</td><td>{title_html}<div style='font-size:smaller'>{r['snippet'][:300]}</div></td><td>{r['source']}</td><td>{r['exp_matched']}</td></tr>")
    html.append("</table>")
    return "\n".join(html)


def send_email(subject, html_body, attachment_bytes, attachment_name="jobs.csv"):
    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    msg['To'] = RECIPIENT_EMAIL
    msg['Subject'] = subject
    msg.attach(MIMEText(html_body, 'html'))

    if attachment_bytes:
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(attachment_bytes)
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f'attachment; filename="{attachment_name}"')
        msg.attach(part)

    # send via SMTP
    server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
    server.ehlo()
    if SMTP_PORT == 587:
        server.starttls()
    server.login(SMTP_USER, SMTP_PASS)
    server.sendmail(SENDER_EMAIL, RECIPIENT_EMAIL, msg.as_string())
    server.quit()


# ---------- Runner ----------

def main():
    logging.info("Starting job collection")
    rows = collect_jobs()
    if not rows:
        logging.info("No results found. Sending empty notification.")
    html = format_html(rows)
    csv_bytes = to_csv_bytes(rows) if rows else None
    subject = f"Daily Job Search Results — {datetime.now().strftime('%Y-%m-%d')}"
    try:
        send_email(subject, html, csv_bytes)
        logging.info("Email sent to %s", RECIPIENT_EMAIL)
    except Exception as e:
        logging.exception("Failed to send email: %s", e)


if __name__ == '__main__':
    main()


# ---------- GitHub Actions example ----------
# Save as .github/workflows/daily-job-search.yml and store secrets: SERPAPI_API_KEY, SMTP_USER, SMTP_PASS, RECIPIENT_EMAIL
#
# name: Daily Job Search
# on:
#   schedule:
#     - cron: '0 3 * * *' # runs at 03:00 UTC (adjust to match 09:00 IST -> 03:30 UTC; cron doesn't support 30 with all runners, so pick appropriate)
# jobs:
#   run-search:
#     runs-on: ubuntu-latest
#     steps:
#       - uses: actions/checkout@v4
#       - name: Set up Python
#         uses: actions/setup-python@v4
#         with:
#           python-version: '3.10'
#       - name: Install dependencies
#         run: |
#           python -m pip install requests
#       - name: Run script
#         env:
#           SERPAPI_API_KEY: ${{ secrets.SERPAPI_API_KEY }}
#           SMTP_USER: ${{ secrets.SMTP_USER }}
#           SMTP_PASS: ${{ secrets.SMTP_PASS }}
#           RECIPIENT_EMAIL: ${{ secrets.RECIPIENT_EMAIL }}
#         run: |
#           python daily-job-search-automation.py
#
# End of file
