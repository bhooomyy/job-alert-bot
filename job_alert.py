#ADZUNA_APP_ID = os.environ.get("45180c64")
#ADZUNA_APP_KEY = os.environ.get("71010bbac2ccfa26888d8694cad6f8ba")
#TELEGRAM_TOKEN = os.environ.get("8942371467:AAEqxNeJARACHSERiCr9vxVMQFHetROgvZU")
import requests, json, os, re
import ssl
import urllib3
from datetime import datetime, timezone, timedelta
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from html import unescape
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

# Fixes SSL issues some systems hit against Eluta (corporate/antivirus TLS interception)
class TLSAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)

def get_session():
    s = requests.Session()
    s.mount("https://", TLSAdapter())
    return s

# ============ CONFIG ============
ADZUNA_APP_ID = os.environ.get("ADZUNA_APP_ID")
ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")

CHAT_ID = "8828838638"
SEEN_FILE = "seen_jobs.json"
DEBUG = True  # set False once tuned

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# ---- Title tiers ----
TIER1_TITLES = [
    "data analyst", "data consultant", "data engineer", "data developer",
    "analytics engineer", "bi analyst", "bi developer",
    "business intelligence analyst", "business intelligence developer",
    "data pipeline engineer", "etl developer", "cloud data engineer",
    "azure data engineer", "data quality analyst"
]

TIER2_TITLES = [
    "reporting analyst", "hr analyst", "people analyst",
    "pricing analyst", "financial analyst", "finance analyst",
    "business analyst", "insights analyst", "risk analyst",
    "risk data analyst", "product analyst", "operations analyst"
]

EXCLUDE_TITLE = [
    "senior", "sr.", "sr ", "staff", "principal", "director", "manager",
    "lead ", "head of", "vp ", "vice president", "chief"
]

EXCLUDE_LOCATION = [
    "new brunswick", "fredericton", "moncton", "saint john",
    "newfoundland", "nova scotia", "halifax", "prince edward island",
    "yukon", "northwest territories", "nunavut", "saskatchewan"
]

PRIORITY_LOCATIONS = [
    "toronto", "montreal", "montréal", "calgary", "vancouver",
    "british columbia", "ontario", "quebec", "québec", "alberta"
]

AGENCY_KEYWORDS = [
    "staffing", "recruit", "talent solutions", "consulting group",
    "workforce solutions", "outsourcing", "manpower"
]

AGENCY_WHITELIST = [
    "tcs", "tata consultancy", "cgi", "randstad", "robert half",
    "hays", "adecco", "kelly services", "s&p data", "procom",
    "eagle", "raise", "insight global", "collabera", "aston carter",
    "modis", "vaco", "harvey nash", "lhh", "manpowergroup"
]

MY_TOOLS = [
    "sql", "python", "pandas", "pyspark", "numpy",
    "power bi", "tableau", "dax", "power query", "excel",
    "azure", "databricks", "adf", "data factory", "delta lake",
    "adls", "data lake", "unity catalog", "key vault", "blob storage",
    "mysql", "postgresql", "sql server", "azure sql",
    "etl", "elt", "medallion", "data quality", "data validation",
    "reconciliation", "uat", "user acceptance testing", "git", "github",
    "data pipeline", "dashboard", "star schema", "data modeling",
    "row-level security", "rls", "ci/cd", "version control"
]

SEARCH_KEYWORDS = ["data analyst", "data engineer", "analytics engineer", "business intelligence"]
MAX_JOB_AGE_HOURS = 24  # only alert on jobs posted within this window (now applies to TD too via postedOn parsing)


# ============ FILTER LOGIC ============
def parse_workday_posted_text(posted_text):
    """
    Handles human-readable relative time strings from various sources:
    Workday ('Posted Today', 'Posted 2 Days Ago'), SerpAPI/Google Jobs
    ('3 hours ago', 'Just posted', '2 weeks ago'), etc. Converts to an
    approximate ISO timestamp reusable with is_fresh_job().
    """
    if not posted_text:
        return None
    posted_text = posted_text.lower()
    now = datetime.now(timezone.utc)
    try:
        if "just posted" in posted_text or "just now" in posted_text:
            return now.isoformat()
        if "today" in posted_text:
            return now.isoformat()
        if "yesterday" in posted_text:
            return (now - timedelta(days=1)).isoformat()

        m = re.search(r"(\d+)\s*minute", posted_text)
        if m:
            return (now - timedelta(minutes=int(m.group(1)))).isoformat()

        m = re.search(r"(\d+)\s*hour", posted_text)
        if m:
            return (now - timedelta(hours=int(m.group(1)))).isoformat()

        m = re.search(r"(\d+)\+?\s*day", posted_text)
        if m:
            return (now - timedelta(days=int(m.group(1)))).isoformat()

        m = re.search(r"(\d+)\+?\s*week", posted_text)
        if m:
            return (now - timedelta(weeks=int(m.group(1)))).isoformat()

        m = re.search(r"(\d+)\+?\s*month", posted_text)
        if m:
            return (now - timedelta(days=int(m.group(1)) * 30)).isoformat()
    except Exception:
        pass
    return None  # unrecognized format — treated as unknown, won't be blocked


def is_fresh_job(created_str):
    """
    Returns True only if we can confirm the job was posted within MAX_JOB_AGE_HOURS.
    Unknown dates are now treated as NOT fresh (blocked) rather than passed through —
    since showing an old job is worse than missing one we can't verify.
    """
    if not created_str:
        return False  # unknown date — block rather than risk showing something stale
    try:
        posted = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
        age = datetime.now(timezone.utc) - posted
        return age <= timedelta(hours=MAX_JOB_AGE_HOURS)
    except Exception:
        return False  # if parsing fails, block rather than risk it


def is_blocked_agency(company_name):
    name = company_name.lower()
    if any(w in name for w in AGENCY_WHITELIST):
        return False
    return any(k in name for k in AGENCY_KEYWORDS)


def passes_filters(title, description, location, company, title_only_source=False):
    t = title.lower()
    d = description.lower()
    loc = location.lower()

    is_tier1 = any(k in t for k in TIER1_TITLES)
    is_tier2 = any(k in t for k in TIER2_TITLES)

    if not (is_tier1 or is_tier2):
        return False, 0
    if any(x in t for x in EXCLUDE_TITLE):
        return False, 0
    if any(x in loc for x in EXCLUDE_LOCATION):
        return False, 0
    if is_blocked_agency(company):
        return False, 0

    # Bank/company career-page sources often only give us the title, not a full
    # description — so we can't score on tool mentions. If it's tier1 (title is
    # already a strong signal) from a title-only source, let it straight through.
    if title_only_source:
        if is_tier1:
            return True, 1
        return False, 0

    tool_score = sum(1 for tool in MY_TOOLS if tool in d)
    location_bonus = 1 if any(p in loc for p in PRIORITY_LOCATIONS) else 0
    total_score = tool_score + location_bonus

    min_score = 1 if is_tier1 else 3
    return total_score >= min_score, total_score


# ============ SOURCE 1: ADZUNA ============
def fetch_adzuna_jobs(page=1):
    if not (ADZUNA_APP_ID and ADZUNA_APP_KEY):
        print("Adzuna keys not set, skipping")
        return []
    jobs = []
    try:
        url = f"https://api.adzuna.com/v1/api/jobs/ca/search/{page}"
        params = {
            "app_id": ADZUNA_APP_ID,
            "app_key": ADZUNA_APP_KEY,
            "results_per_page": 50,
            "what_or": " ".join(SEARCH_KEYWORDS),
            "sort_by": "date",
            "content-type": "application/json"
        }
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        for j in r.json().get("results", []):
            jobs.append({
                "id": "adzuna_" + str(j["id"]),
                "title": j["title"],
                "company": {"display_name": j.get("company", {}).get("display_name", "Unknown")},
                "location": {"display_name": j.get("location", {}).get("display_name", "")},
                "description": j.get("description", ""),
                "redirect_url": j["redirect_url"],
                "created": j.get("created")  # e.g. "2026-07-15T14:48:16Z"
            })
    except Exception as e:
        print(f"Adzuna fetch failed: {e}")
    return jobs


# ============ SOURCE 2: ELUTA (scrape) ============
def fetch_eluta_jobs(keyword="data analyst"):
    jobs = []
    try:
        url = "https://www.eluta.ca/search"
        params = {"q": keyword, "l": "Canada"}
        session = get_session()
        r = session.get(url, params=params, headers=HEADERS, timeout=15)
        r.raise_for_status()
        html = r.text
        pattern = re.compile(
            r'<a[^>]+href="(?P<link>[^"]+)"[^>]+class="[^"]*lk-jtl[^"]*"[^>]*>(?P<title>[^<]+)</a>.*?'
            r'<span[^>]*class="[^"]*organization[^"]*"[^>]*>(?P<company>[^<]+)</span>',
            re.DOTALL
        )
        for m in pattern.finditer(html):
            title = unescape(m.group("title")).strip()
            company = unescape(m.group("company")).strip()
            link = m.group("link")
            if not link.startswith("http"):
                link = "https://www.eluta.ca" + link
            jobs.append({
                "id": "eluta_" + str(abs(hash(link))),
                "title": title,
                "company": {"display_name": company},
                "location": {"display_name": "Canada"},
                "description": title,
                "redirect_url": link
            })
    except Exception as e:
        print(f"Eluta fetch failed ({keyword}): {e}")
    return jobs


# ============ SOURCE 3: BANK & COMPANY CAREER PAGES ============
def fetch_bank_jobs():
    """
    Best-effort JSON endpoints for each company's career site.
    These are unverified until tested live — some may 404 or need adjustment
    once we see real output (common with Workday/SuccessFactors-based career sites).
    Each is wrapped in its own try/except so one failure doesn't block the others.
    """
    jobs = []

    # --- RBC ---
    try:
        r = requests.get(
            "https://jobs.rbc.com/api/jobs",
            params={"keywords": "data analyst", "country": "Canada"},
            headers=HEADERS, timeout=15
        )
        if r.status_code == 200:
            for j in r.json().get("jobs", [])[:20]:
                jobs.append({
                    "id": "rbc_" + str(j.get("jobId", j.get("id", ""))),
                    "title": j.get("title", ""),
                    "company": {"display_name": "RBC"},
                    "location": {"display_name": j.get("location", "Canada")},
                    "description": j.get("title", ""),
                    "redirect_url": j.get("applyUrl", "https://jobs.rbc.com"),
                    "title_only": True
                })
        else:
            print(f"RBC endpoint returned {r.status_code}")
    except Exception as e:
        print(f"RBC fetch failed: {e}")

    # --- TD (Workday-based career site) ---
    try:
        r = requests.post(
            "https://td.wd3.myworkdayjobs.com/wday/cxs/td/TD_Bank_Careers/jobs",
            json={"limit": 20, "offset": 0, "searchText": "data analyst"},
            headers={**HEADERS, "Content-Type": "application/json"}, timeout=15
        )
        if r.status_code == 200:
            for j in r.json().get("jobPostings", []):
                jobs.append({
                    "id": "td_" + str(j.get("bulletFields", [""])[0] or j.get("title", "")),
                    "title": j.get("title", ""),
                    "company": {"display_name": "TD"},
                    "location": {"display_name": j.get("locationsText", "Canada")},
                    "description": j.get("title", ""),
                    "redirect_url": "https://td.wd3.myworkdayjobs.com/TD_Bank_Careers" + j.get("externalPath", ""),
                    "title_only": True,
                    "created": parse_workday_posted_text(j.get("postedOn", ""))
                })
        else:
            print(f"TD endpoint returned {r.status_code}")
    except Exception as e:
        print(f"TD fetch failed: {e}")

    # --- BMO (Workday-based career site) ---
    try:
        r = requests.post(
            "https://bmo.wd3.myworkdayjobs.com/wday/cxs/bmo/BMO_Careers/jobs",
            json={"limit": 20, "offset": 0, "searchText": "data analyst"},
            headers={**HEADERS, "Content-Type": "application/json"}, timeout=15
        )
        if r.status_code == 200:
            for j in r.json().get("jobPostings", []):
                jobs.append({
                    "id": "bmo_" + str(j.get("title", "") + j.get("externalPath", "")),
                    "title": j.get("title", ""),
                    "company": {"display_name": "BMO"},
                    "location": {"display_name": j.get("locationsText", "Canada")},
                    "description": j.get("title", ""),
                    "redirect_url": "https://bmo.wd3.myworkdayjobs.com/BMO_Careers" + j.get("externalPath", ""),
                    "title_only": True
                })
        else:
            print(f"BMO endpoint returned {r.status_code}")
    except Exception as e:
        print(f"BMO fetch failed: {e}")

    # --- Scotiabank (Workday-based career site) ---
    try:
        r = requests.post(
            "https://scotiabank.wd3.myworkdayjobs.com/wday/cxs/scotiabank/Scotiabank_Careers/jobs",
            json={"limit": 20, "offset": 0, "searchText": "data analyst"},
            headers={**HEADERS, "Content-Type": "application/json"}, timeout=15
        )
        if r.status_code == 200:
            for j in r.json().get("jobPostings", []):
                jobs.append({
                    "id": "scotia_" + str(j.get("title", "") + j.get("externalPath", "")),
                    "title": j.get("title", ""),
                    "company": {"display_name": "Scotiabank"},
                    "location": {"display_name": j.get("locationsText", "Canada")},
                    "description": j.get("title", ""),
                    "redirect_url": "https://scotiabank.wd3.myworkdayjobs.com/Scotiabank_Careers" + j.get("externalPath", ""),
                    "title_only": True
                })
        else:
            print(f"Scotiabank endpoint returned {r.status_code}")
    except Exception as e:
        print(f"Scotiabank fetch failed: {e}")

    # --- National Bank of Canada ---
    try:
        r = requests.get(
            "https://www.bnc.ca/en/careers/job-search.html",
            params={"keywords": "data analyst"},
            headers=HEADERS, timeout=15
        )
        # National Bank's career site structure needs manual inspection to confirm
        # a stable JSON endpoint — flagging as reachability check only for now.
        if r.status_code != 200:
            print(f"National Bank careers page returned {r.status_code}")
    except Exception as e:
        print(f"National Bank fetch failed: {e}")

    # Air Canada now handled via fetch_air_canada_jobs() (Selenium, real dates)

    return jobs


# ============ SOURCE 3B: SELENIUM-BASED BANK/COMPANY SCRAPER ============
# Works across different ATS platforms (Workday, Phenom, SuccessFactors) since it
# renders the page fully (including JS-loaded content) instead of guessing JSON APIs.

def get_selenium_driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36")

    # Point to Brave's binary since it's Chromium-based and works with ChromeDriver.
    # Override via BROWSER_BINARY_PATH env var if Brave is installed somewhere non-standard.
    brave_path = os.environ.get(
        "BROWSER_BINARY_PATH",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
    )
    if os.path.exists(brave_path):
        options.binary_location = brave_path
    else:
        print(f"Warning: browser binary not found at {brave_path} — set BROWSER_BINARY_PATH env var if needed")

    service = Service(ChromeDriverManager(driver_version=os.environ.get("CHROMEDRIVER_VERSION")).install())
    driver = webdriver.Chrome(service=service, options=options)
    return driver


def fetch_selenium_jobs(company_name, search_url, job_card_selector, title_selector=None, link_selector=None):
    """
    Generic Selenium-based scraper. Loads the page, waits for JS to render,
    then extracts job cards using CSS selectors.

    If title_selector/link_selector are None, treats job_card_selector itself
    as the element containing both the title text and the href (self-contained
    card, like BMO's <a data-ph-at-id="job-link">Title</a> structure).
    """
    jobs = []
    driver = None
    try:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        driver = get_selenium_driver()
        driver.get(search_url)

        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, job_card_selector))
        )

        cards = driver.find_elements(By.CSS_SELECTOR, job_card_selector)
        for card in cards[:20]:
            try:
                if title_selector is None and link_selector is None:
                    title = card.text.strip()
                    link = card.get_attribute("href")
                    # Phenom-based sites (BMO, RBC) expose a real post-date attribute
                    posted_attr = card.get_attribute("data-ph-at-job-post-date-text")
                else:
                    title_el = card.find_element(By.CSS_SELECTOR, title_selector)
                    link_el = card.find_element(By.CSS_SELECTOR, link_selector)
                    title = title_el.text.strip()
                    link = link_el.get_attribute("href")
                    posted_attr = None

                if not title or not link:
                    continue
                jobs.append({
                    "id": company_name.lower() + "_" + str(abs(hash(link))),
                    "title": title,
                    "company": {"display_name": company_name},
                    "location": {"display_name": "Canada"},
                    "description": title,
                    "redirect_url": link,
                    "title_only": True,
                    "created": posted_attr  # real date if Phenom exposed it, else None
                })
            except Exception:
                continue

    except Exception as e:
        print(f"{company_name} Selenium fetch failed: {e}")
    finally:
        if driver:
            driver.quit()

    return jobs


def fetch_scotiabank_jobs(keyword="data analyst"):
    """
    Scotiabank's SuccessFactors career site renders results as server-side HTML
    tables — no Selenium needed, just requests + regex (like our Eluta scraper).
    """
    jobs = []
    try:
        url = "https://jobs.scotiabank.com/search/"
        params = {"q": keyword, "locationsearch": ""}
        r = requests.get(url, params=params, headers=HEADERS, timeout=15)
        r.raise_for_status()
        html = r.text

        row_pattern = re.compile(r'<tr class="data-row">(.*?)</tr>', re.DOTALL)
        title_pattern = re.compile(
            r'<a href="([^"]+)" class="jobTitle-link">([^<]+)</a>'
        )
        date_pattern = re.compile(r'<span class="jobDate">\s*([^<]+?)\s*</span>')
        location_pattern = re.compile(
            r'<span class="jobLocation">\s*([^<]+?)\s*</span>'
        )

        for row_match in row_pattern.finditer(html):
            row_html = row_match.group(1)

            title_match = title_pattern.search(row_html)
            if not title_match:
                continue
            link_path, title = title_match.groups()
            title = unescape(title).strip()
            link = "https://jobs.scotiabank.com" + link_path

            date_match = date_pattern.search(row_html)
            posted_text = date_match.group(1).strip() if date_match else None

            loc_match = location_pattern.search(row_html)
            location = unescape(loc_match.group(1)).strip() if loc_match else "Canada"

            # Convert "Jul 16, 2026" style date to ISO for our freshness check
            created_iso = None
            if posted_text:
                try:
                    parsed = datetime.strptime(posted_text, "%b %d, %Y")
                    created_iso = parsed.replace(tzinfo=timezone.utc).isoformat()
                except Exception:
                    pass

            jobs.append({
                "id": "scotia_" + str(abs(hash(link))),
                "title": title,
                "company": {"display_name": "Scotiabank"},
                "location": {"display_name": location},
                "description": title,
                "redirect_url": link,
                "title_only": True,
                "created": created_iso
            })
    except Exception as e:
        print(f"Scotiabank fetch failed ({keyword}): {e}")
    return jobs


def parse_phenom_date_text(date_text):
    """
    Converts 'July 10th 2026' style text to ISO format. Handles cases where
    the element's full text also includes a hidden label like 'Posted Date: '
    by extracting just the date pattern via regex rather than requiring an
    exact string match.
    """
    if not date_text:
        return None
    try:
        match = re.search(
            r"([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?\s+(\d{4})", date_text
        )
        if not match:
            return None
        month, day, year = match.groups()
        cleaned = f"{month} {day} {year}"
        parsed = datetime.strptime(cleaned, "%B %d %Y")
        return parsed.replace(tzinfo=timezone.utc).isoformat()
    except Exception:
        return None


def fetch_serpapi_jobs(query="data analyst"):
    """
    Google Jobs via SerpAPI — aggregates LinkedIn, Indeed, Glassdoor postings
    legally since Google indexes all of them. Free tier: 100 searches/month,
    so this is meant to run on a SEPARATE, less-frequent schedule (e.g. once
    daily = ~30 calls/month) rather than every 3h alongside everything else.
    """
    jobs = []
    SERPAPI_KEY = os.environ.get("SERPAPI_KEY")
    if not SERPAPI_KEY:
        print("SERPAPI_KEY not set, skipping SerpAPI source")
        return jobs

    try:
        r = requests.get(
            "https://serpapi.com/search.json",
            params={
                "engine": "google_jobs",
                "q": f"{query} canada",
                "api_key": SERPAPI_KEY
            },
            timeout=20
        )
        r.raise_for_status()
        data = r.json()
        for j in data.get("jobs_results", []):
            job_id = "serp_" + str(j.get("job_id", abs(hash(j.get("title", "") + j.get("company_name", "")))))
            link = j.get("share_link") or (j.get("apply_options", [{}])[0].get("link", "") if j.get("apply_options") else "")
            posted_iso = None
            extensions = j.get("detected_extensions", {})
            posted_text = extensions.get("posted_at", "")
            if not posted_text:
                # Fallback: SerpAPI sometimes puts relative dates in a plain
                # "extensions" list of strings instead (e.g. ["3 days ago", "Full-time"])
                for ext in j.get("extensions", []):
                    if re.search(r"(today|yesterday|\d+\s*(minute|hour|day|week|month))", ext.lower()):
                        posted_text = ext
                        break
            if posted_text:
                posted_iso = parse_workday_posted_text(posted_text)  # handles "N days ago" style text
            jobs.append({
                "id": job_id,
                "title": j.get("title", ""),
                "company": {"display_name": j.get("company_name", "Unknown")},
                "location": {"display_name": j.get("location", "Canada")},
                "description": j.get("description", ""),
                "redirect_url": link,
                "created": posted_iso  # None if unparseable — will be blocked, same as other sources
            })
    except Exception as e:
        print(f"SerpAPI fetch failed ({query}): {e}")

    return jobs


def fetch_phenom_jobs_with_date(company_name, search_url):
    """
    Reliable Phenom scraper: finds title links directly, then walks up ancestor
    levels via XPath to get the card wrapper (matches the a > h3 > div > div
    nesting confirmed in both Air Canada's and Manulife's real HTML). Replaces
    the earlier :has()-based approach which was unreliably matching cards.
    """
    jobs = []
    driver = None
    try:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        driver = get_selenium_driver()
        driver.get(search_url)
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[data-ph-at-id='job-link']"))
        )
        title_links = driver.find_elements(By.CSS_SELECTOR, "a[data-ph-at-id='job-link']")
        for title_el in title_links[:20]:
            try:
                title = title_el.text.strip()
                link = title_el.get_attribute("href")
                if not title or not link:
                    continue

                created_iso = None
                try:
                    card = title_el.find_element(By.XPATH, "./ancestor::div[2]")
                    date_el = card.find_element(By.CSS_SELECTOR, "[data-ph-at-id='job-postedDate']")
                    raw_date_text = date_el.text
                    created_iso = parse_phenom_date_text(raw_date_text)
                    if DEBUG and not created_iso:
                        print(f"  [debug] {company_name} date parse failed on raw text: {raw_date_text!r}")
                except Exception:
                    pass  # no date found — will be treated as stale/blocked

                jobs.append({
                    "id": company_name.lower().replace(" ", "") + "_" + str(abs(hash(link))),
                    "title": title,
                    "company": {"display_name": company_name},
                    "location": {"display_name": "Canada"},
                    "description": title,
                    "redirect_url": link,
                    "title_only": True,
                    "created": created_iso
                })
            except Exception:
                continue
    except Exception as e:
        print(f"{company_name} Selenium fetch failed: {e}")
    finally:
        if driver:
            driver.quit()
    return jobs


def fetch_air_canada_jobs():
    return fetch_phenom_jobs_with_date(
        "Air Canada",
        "https://careers.aircanada.com/ca/en/search-results?keywords=data%20analyst"
    )


def fetch_manulife_jobs():
    return fetch_phenom_jobs_with_date(
        "Manulife",
        "https://careers.manulife.com/global/en/search-results?keywords=data%20analyst"
    )


def parse_workday_dl_posted_text(posted_text):
    """
    Handles Workday's newer 'Posted Today', 'Posted Yesterday', 'Posted N Days Ago'
    format (used by CIBC/Sun Life/Intact/Canadian Tire) — same logic as
    parse_workday_posted_text, kept separate in case format drifts differently.
    """
    return parse_workday_posted_text(posted_text)


def fetch_workday_dl_jobs(company_name, search_url):
    """
    Generic scraper for Workday sites using the '<li class=\"css-...\">' card
    pattern with data-automation-id='jobTitle' and data-automation-id='postedOn'
    (CIBC, Sun Life, Intact, Canadian Tire all confirmed to use this exact structure).

    NOTE: search_url tenant/site slugs are best-effort guesses — unverified until
    you run this and report back what happens, same as our other sources.
    """
    jobs = []
    driver = None
    try:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        driver = get_selenium_driver()
        driver.get(search_url)
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[data-automation-id='jobTitle']"))
        )
        cards = driver.find_elements(By.CSS_SELECTOR, "li.css-1q2dra3")
        for card in cards[:20]:
            try:
                title_el = card.find_element(By.CSS_SELECTOR, "a[data-automation-id='jobTitle']")
                title = title_el.text.strip()
                link = title_el.get_attribute("href")
                if not title or not link:
                    continue
                created_iso = None
                try:
                    date_el = card.find_element(By.CSS_SELECTOR, "[data-automation-id='postedOn'] dd")
                    created_iso = parse_workday_dl_posted_text(date_el.text)
                except Exception:
                    pass
                jobs.append({
                    "id": company_name.lower().replace(" ", "") + "_" + str(abs(hash(link))),
                    "title": title,
                    "company": {"display_name": company_name},
                    "location": {"display_name": "Canada"},
                    "description": title,
                    "redirect_url": link,
                    "title_only": True,
                    "created": created_iso
                })
            except Exception:
                continue
    except Exception as e:
        print(f"{company_name} Selenium fetch failed: {e}")
    finally:
        if driver:
            driver.quit()
    return jobs


def fetch_rogers_jobs(keyword="data analyst"):
    """Rogers uses the same SuccessFactors HTML table pattern as Scotiabank."""
    jobs = []
    try:
        url = "https://jobs.rogers.com/search/"
        params = {"q": keyword, "locationsearch": ""}
        r = requests.get(url, params=params, headers=HEADERS, timeout=15)
        r.raise_for_status()
        html = r.text

        row_pattern = re.compile(r'<tr class="data-row">(.*?)</tr>', re.DOTALL)
        title_pattern = re.compile(r'<a href="([^"]+)" class="jobTitle-link">([^<]+)</a>')
        date_pattern = re.compile(r'<span class="jobDate">\s*([^<]+?)\s*</span>')
        location_pattern = re.compile(r'<span class="jobLocation">\s*([^<]+?)\s*</span>')

        for row_match in row_pattern.finditer(html):
            row_html = row_match.group(1)
            title_match = title_pattern.search(row_html)
            if not title_match:
                continue
            link_path, title = title_match.groups()
            title = unescape(title).strip()
            link = "https://jobs.rogers.com" + link_path

            date_match = date_pattern.search(row_html)
            posted_text = date_match.group(1).strip() if date_match else None
            loc_match = location_pattern.search(row_html)
            location = unescape(loc_match.group(1)).strip() if loc_match else "Canada"

            created_iso = None
            if posted_text:
                try:
                    parsed = datetime.strptime(posted_text, "%b %d, %Y")
                    created_iso = parsed.replace(tzinfo=timezone.utc).isoformat()
                except Exception:
                    pass

            jobs.append({
                "id": "rogers_" + str(abs(hash(link))),
                "title": title,
                "company": {"display_name": "Rogers"},
                "location": {"display_name": location},
                "description": title,
                "redirect_url": link,
                "title_only": True,
                "created": created_iso
            })
    except Exception as e:
        print(f"Rogers fetch failed ({keyword}): {e}")
    return jobs


def fetch_ontario_public_service_jobs(keyword="data analyst"):
    """
    Ontario Public Service — server-rendered HTML, no Selenium needed.
    NOTE: no post-date field available, only a 'Closing Date' (deadline, not
    posting date) — so these will always be blocked as [stale] under our
    freshness rule. Included for completeness; won't produce alerts unless
    we find another way to verify posting date later.
    """
    jobs = []
    try:
        url = "https://www.gojobs.gov.on.ca/Search.aspx"
        params = {"searchtext": keyword}
        r = requests.get(url, params=params, headers=HEADERS, timeout=15)
        r.raise_for_status()
        html = r.text
        pattern = re.compile(
            r'<a[^>]+class="job-link"[^>]+href="([^"]+)"[^>]*>([^<]+)</a>'
        )
        for link_path, title in pattern.findall(html):
            title = unescape(title).strip()
            link = "https://www.gojobs.gov.on.ca" + link_path
            jobs.append({
                "id": "ops_" + str(abs(hash(link))),
                "title": title,
                "company": {"display_name": "Ontario Public Service"},
                "location": {"display_name": "Ontario"},
                "description": title,
                "redirect_url": link,
                "title_only": True,
                "created": None  # no reliable post-date available — will be blocked
            })
    except Exception as e:
        print(f"Ontario Public Service fetch failed ({keyword}): {e}")
    return jobs


def fetch_all_selenium_banks():
    """
    NOTE: CSS selectors below are best-effort guesses based on common patterns
    for each ATS platform. They WILL likely need adjustment once we see real
    output — that's expected on the first run, same as our other sources.
    """
    jobs = []

    # BMO — Phenom People platform (verified selector from real DOM inspection)
    jobs += fetch_selenium_jobs(
        "BMO",
        "https://jobs.bmo.com/ca/en/search-results?keywords=data%20analyst",
        job_card_selector="a[data-ph-at-id='job-link']"
    )

    # Scotiabank now handled via fetch_scotiabank_jobs() (server-rendered HTML,
    # no Selenium needed — more reliable than fighting their bot detection)

    # RBC — trying same Phenom pattern as BMO since it's a common platform choice for banks
    jobs += fetch_selenium_jobs(
        "RBC",
        "https://jobs.rbc.com/ca/en/search-results?keywords=data%20analyst",
        job_card_selector="a[data-ph-at-id='job-link']"
    )

    return jobs


# ============ TELEGRAM ============
def send_telegram(msg):
    if not TELEGRAM_TOKEN:
        print("TELEGRAM_TOKEN not set, cannot send alert")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={
        "chat_id": CHAT_ID,
        "text": msg,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    })


# ============ SEEN TRACKING ============
def load_seen():
    if os.path.exists(SEEN_FILE):
        return set(json.load(open(SEEN_FILE)))
    return set()


def save_seen(seen):
    json.dump(list(seen), open(SEEN_FILE, "w"))


# ============ MAIN ============
def main():
    seen = load_seen()
    new_alerts = 0
    checked = 0
    all_jobs = []

    # Adzuna — 1 page/run, stays under 250/month at 8 runs/day
    all_jobs.extend(fetch_adzuna_jobs(page=1))

    # Eluta — re-enabled to test on GitHub Actions' Linux runner (the SSL issue
    # was likely local Mac antivirus/network interference, may not occur here)
    for kw in SEARCH_KEYWORDS:
        all_jobs.extend(fetch_eluta_jobs(keyword=kw))

    # Bank & company career pages — free, no limit
    all_jobs.extend(fetch_bank_jobs())

    # Scotiabank — server-rendered HTML, no Selenium needed
    for kw in ["data analyst", "data engineer"]:
        all_jobs.extend(fetch_scotiabank_jobs(keyword=kw))

    # Selenium-based bank scraping (BMO, RBC) — slower but works
    # across different ATS platforms without needing exact JSON API endpoints
    all_jobs.extend(fetch_all_selenium_banks())

    # Air Canada — Selenium, with real posted-date parsing
    all_jobs.extend(fetch_air_canada_jobs())

    # Manulife — Phenom pattern (same as Air Canada/BMO/RBC)
    all_jobs.extend(fetch_manulife_jobs())

    # CIBC, Sun Life, Intact, Canadian Tire — Workday pattern, searched across
    # all SEARCH_KEYWORDS (not just "data analyst") so analytics engineer,
    # BI analyst, etc. roles are caught too. Experience-level filtering (avoiding
    # senior/manager/director/lead roles) already happens via EXCLUDE_TITLE.
    workday_companies = {
        "CIBC": "https://cibc.wd3.myworkdayjobs.com/search",
        "Sun Life": "https://sunlife.wd3.myworkdayjobs.com/Experienced-Jobs",
        "Intact": "https://intactfc.wd3.myworkdayjobs.com/intactfc",
        "Canadian Tire": "https://canadiantirecorporation.wd3.myworkdayjobs.com/Enterprise_External_Careers_Site",
    }
    for company_name, base_url in workday_companies.items():
        for kw in SEARCH_KEYWORDS:
            query = kw.replace(" ", "+")
            all_jobs.extend(fetch_workday_dl_jobs(company_name, f"{base_url}?q={query}"))

    # Rogers — SuccessFactors table pattern (same as Scotiabank)
    for kw in ["data analyst", "data engineer"]:
        all_jobs.extend(fetch_rogers_jobs(keyword=kw))

    # Ontario Public Service — will always be blocked (no post-date available)
    all_jobs.extend(fetch_ontario_public_service_jobs())

    print(f"Fetched {len(all_jobs)} total job listings across all sources.")

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

        ok, score = passes_filters(title, desc, location, company, title_only_source=job.get("title_only", False))

        if DEBUG:
            status = "PASS" if ok else "reject"
            print(f"[{status}] score={score} | {title} @ {company} | {location}")

        seen.add(job_id)

        if ok:
            posted_text = ""
            if created:
                try:
                    posted = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    hours_ago = int((datetime.now(timezone.utc) - posted).total_seconds() // 3600)
                    posted_text = f"🕐 Posted {hours_ago}h ago\n" if hours_ago >= 1 else "🕐 Posted <1h ago\n"
                except Exception:
                    pass

            msg = (
                f"🎯 <b>New job matching your skills!</b>\n\n"
                f"📌 <b>{title}</b>\n"
                f"🏢 {company}\n"
                f"📍 {location}\n"
                f"{posted_text}"
                f"⭐ Match score: {score}\n\n"
                f"{link}"
            )
            send_telegram(msg)
            new_alerts += 1

    save_seen(seen)
    print(f"Done. Checked {checked} new jobs, {new_alerts} alerts sent.")


if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()
