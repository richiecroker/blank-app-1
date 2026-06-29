import streamlit as st
import requests
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="Screwfix Stock Checker", layout="wide")
st.title("Screwfix Stock Checker")

PRODUCT_CODES = ["931AX", "835XG", "730XG"]

SEARCH_LOCATIONS = [
    {"name": "Barnstaple area", "lat": 51.0824977, "long": -4.0593129},
    {"name": "Bristol area", "lat": 51.45608, "long": -2.586306},
]

BASE_URL = "https://www.screwfix.com/prod/ffx-browse-bff/v1/SFXUK/stock/search"
AUTH_TOKEN = "eyJvcmciOiI2MGFlMTA0ZGVjM2M1ZjAwMDFkMjYxYTkiLCJpZCI6IjU3OTZiYWJkMmUwMDQ0Zjc4ODJjZDgwYWM3YWY5ZmMxIiwiaCI6Im11cm11cjEyOCJ9"

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


with st.sidebar:
    st.header("Products")
    products_input = st.text_area("Product codes (one per line)", value="\n".join(PRODUCT_CODES))
    run = st.button("Check stock", type="primary", use_container_width=True)
    if st.button("Clear session", use_container_width=True):
        st.cache_resource.clear()
        st.success("Session cleared.")

product_codes = [p.strip().upper() for p in products_input.splitlines() if p.strip()]

if run:
    rows = []
    seen_stores = set()  # deduplicate stores that appear in both location searches

    try:
        session = get_session()
    except Exception as e:
        st.error(f"Failed to initialise session: {e}")
        st.stop()

    total = len(SEARCH_LOCATIONS) * len(product_codes)
    progress = st.progress(0, text="Starting...")
    n = 0

    for location in SEARCH_LOCATIONS:
        for product in product_codes:
            progress.progress(n / total, text=f"{location['name']} — {product}")
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
                            "BranchCode": branch_code,
                            "Stock": p["branchStock"],
                        })
            except Exception as e:
                st.warning(f"{location['name']} / {product}: {e}")
            n += 1

    progress.empty()

    if rows:
        df = pd.DataFrame(rows)
        pivot = df.pivot_table(index="Store", columns="Product", values="Stock", aggfunc="first")
        pivot.columns.name = None
        pivot = pivot.sort_index()

        st.subheader(f"Stock levels — {datetime.now().strftime('%H:%M:%S')}")
        st.dataframe(pivot, use_container_width=True)
    else:
        st.warning("No data returned.")
else:
    st.info("Click **Check stock** to fetch current levels.")
