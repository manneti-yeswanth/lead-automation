# ============================================================
# Lead Generation Automation Script - FINAL VERSION
# Scrapes NGO data from Wikipedia's public list page
# Tools: requests, BeautifulSoup, pandas, openpyxl, schedule
# ============================================================

import requests
from bs4 import BeautifulSoup
import pandas as pd
import schedule
import time
import re
from datetime import datetime


# ─────────────────────────────────────────
# STEP 1: Scrape NGO list from Wikipedia
# ─────────────────────────────────────────

def scrape_ngo_list():
    url = "https://en.wikipedia.org/wiki/List_of_human_rights_organisations"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    print(f"  Scraping: {url}\n")
    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    orgs = []

    content = soup.find("div", {"class": "mw-parser-output"})
    for li in content.find_all("li"):
        a = li.find("a", href=True)
        if not a:
            continue
        name = a.get_text(strip=True)
        href = a["href"]
        if not href.startswith("/wiki/"):
            continue
        if ":" in href or len(name) < 4:
            continue

        orgs.append({
            "Name":          name,
            "Wikipedia_URL": "https://en.wikipedia.org" + href
        })

        if len(orgs) >= 35:
            break

    print(f"  Found {len(orgs)} organisations on the list page.")
    return orgs


# ─────────────────────────────────────────
# STEP 2: Clean messy location strings
# Removes dates, "X years ago", addresses
# Keeps only the actual city/country name
# ─────────────────────────────────────────

def clean_location(raw):
    if not raw or raw.strip() in ("N/A", ""):
        return "International"

    text = raw

    # Remove citation brackets like [1], [edit]
    text = re.sub(r'\[.*?\]', '', text)

    # Remove bracketed dates like (2011-11) or (1982-04-06)
    text = re.sub(r'\(\s*[\d\s,\-]+\)', '', text)

    # Remove "X years ago"
    text = re.sub(r'\b\d+\s+years?\s+ago\b', '', text, flags=re.I)

    # Remove month names (they signal a founding date, not a place)
    months = (r'January|February|March|April|May|June|July|'
              r'August|September|October|November|December')
    text = re.sub(months, '', text, flags=re.I)

    # Remove 4-digit years
    text = re.sub(r'\b\d{4}\b', '', text)

    # Remove "by PersonName" and everything after — e.g. "by Helen Bamber, in the"
    text = re.sub(r'\bby\b.*', '', text, flags=re.I)

    # Remove street-level address noise
    text = re.sub(r'\d+\s+[A-Z]\s+Street\b.*', '', text, flags=re.I)
    text = re.sub(r'\bSuite\s+\d+.*', '', text, flags=re.I)

    # Collapse whitespace and stray commas
    text = re.sub(r'[\s,]+', ' ', text).strip().strip(',').strip()

    # If nothing meaningful is left, return fallback
    if not text or len(text) < 3 or re.fullmatch(r'[\d\s,.\-()]+', text):
        return "International"

    # Split by comma, keep parts that look like real place names
    parts = [p.strip() for p in text.split(',') if p.strip() and len(p.strip()) > 1
             and re.search(r'[a-zA-Z]{2,}', p)]

    if not parts:
        return "International"

    # Return at most 2 parts (e.g. "New York City, USA")
    return ', '.join(parts[:2])


# ─────────────────────────────────────────
# STEP 3: Scrape each org's Wikipedia page
# ─────────────────────────────────────────

def scrape_org_details(org):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    website  = "N/A"
    location = "N/A"

    try:
        resp = requests.get(org["Wikipedia_URL"], headers=headers, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        infobox = soup.find("table", class_=re.compile(r"infobox"))
        if infobox:
            for row in infobox.find_all("tr"):
                th = row.find("th")
                td = row.find("td")
                if not th or not td:
                    continue
                label = th.get_text(strip=True).lower()

                # Official website
                if "website" in label and website == "N/A":
                    a_tag = td.find("a", href=True)
                    if a_tag:
                        href = a_tag["href"]
                        website = ("https:" + href) if href.startswith("//") else href

                # Headquarters / location
                if any(w in label for w in ["headquarter", "location", "country"]):
                    if location == "N/A":
                        raw = td.get_text(separator=", ", strip=True)
                        location = clean_location(raw)

    except Exception as e:
        print(f"    Warning: {org['Name']} — {e}")

    return {
        "Name":     org["Name"],
        "Website":  website,
        "Location": location if location != "N/A" else "International",
    }


# ─────────────────────────────────────────
# BONUS: Generate email from website domain
# ─────────────────────────────────────────

def generate_email(website):
    if not website or website == "N/A":
        return "N/A"
    m = re.search(r"https?://(?:www\.)?([^/]+)", website)
    return f"info@{m.group(1).lower()}" if m else "N/A"


# ─────────────────────────────────────────
# BONUS: Build LinkedIn URL from org name
# ─────────────────────────────────────────

def generate_linkedin(name):
    slug = re.sub(r"[^a-zA-Z0-9\s]", "", name).strip().lower()
    slug = re.sub(r"\s+", "-", slug)
    return f"https://www.linkedin.com/company/{slug}"


# ─────────────────────────────────────────
# STEP 4: Collect all lead data
# ─────────────────────────────────────────

def collect_leads():
    print("\n" + "=" * 55)
    print("  Lead Generation Automation — Starting...")
    print("=" * 55 + "\n")

    orgs  = scrape_ngo_list()
    leads = []

    for i, org in enumerate(orgs, 1):
        print(f"  [{i}/{len(orgs)}] {org['Name']}")
        details = scrape_org_details(org)
        leads.append(details)
        time.sleep(0.5)

    print(f"\n  Total collected: {len(leads)} entries.")
    return leads


# ─────────────────────────────────────────
# STEP 5: Clean the data
# ─────────────────────────────────────────

def clean_data(leads):
    df = pd.DataFrame(leads)
    before = len(df)
    print(f"\n  Before cleaning : {before} rows")

    # Remove duplicates by Name
    df.drop_duplicates(subset=["Name"], inplace=True)

    # Fill missing values
    df["Website"]  = df["Website"].fillna("N/A")
    df["Location"] = df["Location"].fillna("International")

    # Re-apply location cleaner on every row
    df["Location"] = df["Location"].apply(clean_location)

    # Add generated columns (Bonus features)
    df["Email"]    = df["Website"].apply(generate_email)
    df["LinkedIn"] = df["Name"].apply(generate_linkedin)
    df["Date_Collected"] = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Keep first 30 entries
    df = df.head(30)

    # Final column order
    df = df[["Name", "Email", "Website", "LinkedIn", "Location", "Date_Collected"]]

    print(f"  After cleaning  : {len(df)} rows")
    print(f"  Duplicates removed: {before - len(df)}")
    return df


# ─────────────────────────────────────────
# STEP 6: Save to Excel with formatting
# ─────────────────────────────────────────

def save_to_excel(df, filename="ngo_leads.xlsx"):
    with pd.ExcelWriter(filename, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="NGO Leads")

        ws = writer.sheets["NGO Leads"]
        for col in ws.columns:
            max_len = max(
                (len(str(cell.value)) for cell in col if cell.value),
                default=10
            )
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 60)

    print(f"\n  Saved  : {filename}")
    print(f"  Leads  : {len(df)}")
    print("=" * 55)


# ─────────────────────────────────────────
# Main pipeline
# ─────────────────────────────────────────

def run_pipeline():
    leads    = collect_leads()
    clean_df = clean_data(leads)
    save_to_excel(clean_df)
    return clean_df


# ─────────────────────────────────────────
# BONUS: Scheduled run every 24 hours
# ─────────────────────────────────────────

def run_with_schedule():
    print("Scheduler started — runs now, then every 24 hours. Ctrl+C to stop.\n")
    run_pipeline()
    schedule.every(24).hours.do(run_pipeline)
    while True:
        schedule.run_pending()
        time.sleep(60)


# ─────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────

if __name__ == "__main__":
    # Option A: Run once (default)
    run_pipeline()

    # Option B: Scheduled run — comment Option A, uncomment below
    # run_with_schedule()
