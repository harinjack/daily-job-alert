"""
Daily Job Search Automation (STABLE VERSION)
----------------------------------------
Searches daily for entry-level (0–3 yrs / fresher) job openings and emails results.

ROLES:
- Software Developer
- React JS Developer
- Frontend Developer
- React Native Developer

LOCATION PRIORITY:
1. Chennai
2. India

Runs perfectly on GitHub Actions.
"""

import os
import time
import csv
import logging
import requests
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import smtplib
from io import StringIO

# ---------------- CONFIG ----------------
ROLES = [
    "software developer",
    "react js developer",
    "frontend developer",
    "react native developer",
]

LOCATIONS = ["Chennai", "India"]

EXPERIENCE_KEYWORDS = [
    "fresher",
    "entry level",
    "junior",
    "0-1",
    "0-2",
    "0-3",
    "1 year",
    "2 years",
    "3 years",
]

MAX_RESULTS = 10
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL")
SENDER_EMAIL = SMTP_USER

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ---------------- SEARCH ----------------

def serpapi_search(query, location):
    url = "https://serpapi.com/search.json"
    params = {
        "q": query,
        "location": location,
        "api_key": SERPAPI_API_KEY,
        "gl": "in",
        "hl": "en",
    }

    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        logging.error("SerpApi error: %s", e)
        return []

    results = []

    if isinstance(data.get("organic_results"), list):
        for item in data["organic_results"][:MAX_RESULTS]:
            results.append({
                "title": item.get("title", ""),
                "link": item.get("link", ""),
                "snippet": item.get("snippet", ""),
                "source": item.get("displayed_link", ""),
            })

    return results


def experience_match(text):
    text = text.lower()
    return any(k in text for k in EXPERIENCE_KEYWORDS)


def collect_jobs():
    jobs = []
    seen = set()

    for role in ROLES:
        for location in LOCATIONS:
            queries = [
                f"{role} {location} fresher",
                f"{role} {location} junior",
                f"{role} {location} 0-3 years",
            ]

            for q in queries:
                logging.info("Searching: %s", q)
                results = serpapi_search(q, location)
                for r in results:
                    if r["link"] and r["link"] not in seen:
                        seen.add(r["link"])
                        text = f"{r['title']} {r['snippet']}"
                        jobs.append({
                            "role": role,
                            "location": location,
                            "title": r["title"],
                            "link": r["link"],
                            "source": r["source"],
                            "exp_match": experience_match(text),
                            "snippet": r["snippet"],
                        })
                time.sleep(1)

    return jobs

# ---------------- EMAIL ----------------

def to_csv_bytes(rows):
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "role",
        "location",
        "title",
        "link",
        "source",
        "experience_match",
        "snippet",
    ])

    for r in rows:
        writer.writerow([
            r["role"],
            r["location"],
            r["title"],
            r["link"],
            r["source"],
            r["exp_match"],
            r["snippet"],
        ])

    return output.getvalue().encode("utf-8")


def send_email(jobs):
    msg = MIMEMultipart()
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECIPIENT_EMAIL
    msg["Subject"] = f"Daily Job Alerts – {datetime.now().strftime('%d %b %Y')}"

    html = "<h2>Daily Job Openings (0–3 yrs)</h2><ul>"
    for j in jobs:
        html += f"<li><a href='{j['link']}'>{j['title']}</a> – {j['location']}</li>"
    html += "</ul>"

    msg.attach(MIMEText(html, "html"))

    part = MIMEBase("application", "octet-stream")
    part.set_payload(to_csv_bytes(jobs))
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment; filename=jobs.csv")
    msg.attach(part)

    server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
    server.starttls()
    server.login(SMTP_USER, SMTP_PASS)
    server.send_message(msg)
    server.quit()

# ---------------- MAIN ----------------

def main():
    logging.info("Starting job collection")
    jobs = collect_jobs()
    logging.info("Found %s jobs", len(jobs))
    send_email(jobs)
    logging.info("Email sent successfully")


if __name__ == "__main__":
    main()
