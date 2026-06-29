import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import time
import smtplib
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

st.set_page_config(page_title="Screwfix Stock Checker", layout="wide")
st.title("Screwfix Stock Checker")

PRODUCT_CODES = ["931AX", "835XG", "730XG"]

SEARCH_LOCATIONS = [
    {"name": "Barnstaple area", "lat": 51.0824977, "long": -4.0593129},
    {"name": "Bristol area", "lat": 51.45608, "long": -2.586306},
]

BASE_URL = "https://www.screwfix.com/prod/ffx-browse-bff/v1/SFXUK/stock/search"
AUTH_TOKEN = "eyJvcmciOiI2MGFlMTA0ZGVjM2M1ZjAwMDFkMjYxYTkiLCJpZCI6IjU3OTZiYWJkMmUwMDQ0Zjc4ODJjZDgwYWM3YWY5ZmMxIiwiaCI6Im11cm11cjEyOCJ9"
POLL_INTERVAL = 15 * 60

#EMAIL_FROM = "screwfix.checker@gmail.com"
#EMAIL_TO = "richard@example.com"
#EMAIL_APP_PASSWORD = st.secrets["email_app_password"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}


@st.cache_resource(ttl=1800)
def get_session():
    session = requests.Session()
    session.headers.update(HEADERS)
    session.get(
        "https://www.screwfix.com/checkstock?product_id=931AX&quantity=1",
        timeout=10,
    )
    return session


@st.cache_data(ttl=86400)
def get_product_descriptions(product_codes):
    """Fetch product longDescription from Screwfix page JSON, cached for 24hrs."""
    descriptions = {}
    for code in product_codes:
        try:
            r = requests.get(
                f"https://www.screwfix.com/p/{code.lower()}",
                headers=HEADERS,
                timeout=10,
                allow_redirects=True,
            )
            match = re.search(r'"longDescription"\s*:\s*"([^"]+)"', r.text)
            if match:
                descriptions[code] = match.group(1).strip()
            else:
                descriptions[code] = code
        except Exception:
            descriptions[code] = code
    return descriptions


def fetch_stock(session, product_code, lat, long):
    headers = {
        "accept": "*/*",
        "authorization": AUTH_TOKEN,
        "content-type": "application/json",
        "referer": f"https://www.screwfix.com/checkstock?product_id={product_code}&quantity=1",
    }
    params = {
        "productId": product_code,
        "lat": lat,
        "long": long,
        "quantity": 1,
    }
    r = session.get(BASE_URL, headers=headers, params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def send_alert(changes, descriptions):
    lines = []
    for product, store, stock in changes:
        desc = descriptions.get(product, product)
        lines.append(f"  {product} — {desc}\n  {store}: {stock} in stock")

    body = "The following items are now in stock at Screwfix:\n\n" + "\n\n".join(lines)

    msg = MIMEMultipart()
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    msg["Subject"] = f"Screwfix stock alert — {len(changes)} item(s) available"
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_FROM, EMAIL_APP_PASSWORD)
            server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        return True
    except Exception as e:
        st.warning(f"Email failed: {e}")
        return False


def run_check():
    rows = []
    seen_stores = set()

    try:
        session = get_session()
    except Exception as e:
        st.error(f"Failed to initialise session: {e}")
        return None

    for location in SEARCH_LOCATIONS:
        for product in PRODUCT_CODES:
            try:
                data = fetch_stock(session, product, location["lat"], location["long"])
                for store_entry in data.get("nearestStores", []):
                    branch = store_entry["storeInfo"]["store"]["basic"]
                    branch_code = branch["branchCode"]
                    store_name = f"{branch['name']} ({branch_code})"
                    key = (branch_code, product)
                    if key in seen_stores:
                        continue
                    seen_stores.add(key)
                    for p in store_entry.get("products", []):
                        if p["skuId"] != product:
                            continue
                        rows.append({
                            "Product": product,
                            "Store": store_name,
                            "Stock": p["branchStock"],
                        })
            except Exception as e:
                st.warning(f"{location['name']} / {product}: {e}")

    if not rows:
        return None

    df = pd.DataFrame(rows)
    pivot = df.pivot_table(index="Store", columns="Product", values="Stock", aggfunc="first")
    pivot.columns.name = None
    return pivot


# --- init state ---
if "last_check" not in st.session_state:
    st.session_state.last_check = None
if "last_df" not in st.session_state:
    st.session_state.last_df = None
if "prev_stock" not in st.session_state:
    st.session_state.prev_stock = {}
if "alerts_sent" not in st.session_state:
    st.session_state.alerts_sent = []

# --- sidebar ---
with st.sidebar:
    if st.button("Clear session", use_container_width=True):
        st.cache_resource.clear()
        st.cache_data.clear()
        st.success("Session cleared.")
    st.caption("Auto-refreshes every 15 minutes.")
    if st.session_state.alerts_sent:
        st.divider()
        st.subheader("Alerts sent")
        for a in st.session_state.alerts_sent:
            st.caption(a)

# --- fetch descriptions ---
descriptions = get_product_descriptions(tuple(PRODUCT_CODES))

# --- show descriptions ---
for code, desc in descriptions.items():
    st.caption(f"**{code}** — {desc}")

st.divider()

# --- check if due ---
now = time.time()
due = (
    st.session_state.last_check is None
    or (now - st.session_state.last_check) >= POLL_INTERVAL
)

if due:
    with st.spinner("Fetching stock..."):
        df = run_check()

    if df is not None:
        changes = []
        for store in df.index:
            for product in df.columns:
                stock = df.loc[store, product]
                prev = st.session_state.prev_stock.get((store, product), 0)
                if prev == 0 and stock > 0:
                    changes.append((product, store, stock))
                st.session_state.prev_stock[(store, product)] = stock

        if changes:
            sent = send_alert(changes, descriptions)
            if sent:
                alert_time = datetime.now().strftime("%H:%M:%S")
                st.session_state.alerts_sent.append(
                    f"{alert_time}: {', '.join(f'{p} @ {s}' for p, s, _ in changes)}"
                )

    st.session_state.last_check = time.time()
    st.session_state.last_df = df

# --- display ---
if st.session_state.last_df is not None:
    checked_at = datetime.fromtimestamp(st.session_state.last_check).strftime("%H:%M:%S")
    next_check = datetime.fromtimestamp(st.session_state.last_check + POLL_INTERVAL).strftime("%H:%M:%S")
    st.caption(f"Last checked: {checked_at} · Next check: {next_check}")

    df = st.session_state.last_df.copy()

    # Rename columns to include description
    df.columns = [f"{c} — {descriptions.get(c, c)}" for c in df.columns]

    # Sort: stores with any stock > 0 first, then alphabetical
    df["_total"] = df.sum(axis=1)
    df = df.sort_values("_total", ascending=False).drop(columns="_total")

    # Display without scrolling — height based on row count
    row_height = 35
    header_height = 38
    height = header_height + row_height * len(df)

    st.dataframe(df, use_container_width=True, height=height)
else:
    st.warning("No data returned.")

# --- schedule next refresh ---
if st.session_state.last_check is not None:
    seconds_until_next = int((st.session_state.last_check + POLL_INTERVAL) - time.time())
    if seconds_until_next > 0:
        time.sleep(seconds_until_next)
    st.rerun()
