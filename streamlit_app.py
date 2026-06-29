import streamlit as st
import requests
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="Screwfix Stock Checker", layout="wide")
st.title("Screwfix Stock Checker")

PRODUCT_CODES = ["931AX", "835XG", "730XG"]
STORE_CODES = ["IC4", "MT8", "SB6"]
LAT = 51.0824977
LONG = -4.0593129

BASE_URL = "https://www.screwfix.com/prod/ffx-browse-bff/v1/SFXUK/stock/search"
AUTH_TOKEN = "eyJvcmciOiI2MGFlMTA0ZGVjM2M1ZjAwMDFkMjYxYTkiLCJpZCI6IjU3OTZiYWJkMmUwMDQ0Zjc4ODJjZDgwYWM3YWY5ZmMxIiwiaCI6Im11cm11cjEyOCJ9"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}


@st.cache_resource(ttl=1800)
def get_session():
    """Create a session with cookies by loading the checkstock page first."""
    session = requests.Session()
    session.headers.update(HEADERS)
    session.get(
        "https://www.screwfix.com/checkstock?product_id=931AX&quantity=1",
        timeout=10,
    )
    return session


def fetch_stock(session, product_code):
    headers = {
        "accept": "*/*",
        "authorization": AUTH_TOKEN,
        "content-type": "application/json",
        "referer": f"https://www.screwfix.com/checkstock?product_id={product_code}&quantity=1",
    }
    params = {
        "productId": product_code,
        "lat": LAT,
        "long": LONG,
        "quantity": 1,
    }
    r = session.get(BASE_URL, headers=headers, params=params, timeout=10)
    r.raise_for_status()
    return r.json()


with st.sidebar:
    st.header("Products")
    products_input = st.text_area("Product codes (one per line)", value="\n".join(PRODUCT_CODES))
    st.header("Stores")
    stores_input = st.text_area("Store codes (one per line)", value="\n".join(STORE_CODES))
    run = st.button("Check stock", type="primary", use_container_width=True)
    if st.button("Clear session", use_container_width=True):
        st.cache_resource.clear()
        st.success("Session cleared — will re-authenticate on next check.")

product_codes = [p.strip().upper() for p in products_input.splitlines() if p.strip()]
store_codes = [s.strip().upper() for s in stores_input.splitlines() if s.strip()]

if run:
    rows = []
    progress = st.progress(0, text="Starting session...")

    try:
        session = get_session()
    except Exception as e:
        st.error(f"Failed to initialise session: {e}")
        st.stop()

    for i, product in enumerate(product_codes):
        progress.progress(i / len(product_codes), text=f"Checking {product}...")
        try:
            data = fetch_stock(session, product)
            for store_entry in data.get("nearestStores", []):
                branch = store_entry["storeInfo"]["store"]["basic"]
                store_name = f"{branch['name']} ({branch['branchCode']})"
                for p in store_entry.get("products", []):
                    if p["skuId"] != product:
                        continue
                    rows.append({
                        "Product": product,
                        "Store": store_name,
                        "BranchCode": branch["branchCode"],
                        "Stock": p["branchStock"],
                        "Status": p["productAvailabilityStatus"],
                    })
        except Exception as e:
            st.warning(f"{product}: {e}")

    progress.empty()

    if rows:
        df = pd.DataFrame(rows)

        # Filter to requested stores if specified
        if store_codes:
            df = df[df["BranchCode"].isin(store_codes)]

        if df.empty:
            st.warning("No results for the specified store codes. Check codes are within range of the search coordinates.")
        else:
            pivot = df.pivot_table(index="Product", columns="Store", values="Stock", aggfunc="first")
            pivot.columns.name = None

            st.subheader(f"Stock levels — {datetime.now().strftime('%H:%M:%S')}")
            st.dataframe(pivot, use_container_width=True)

            with st.expander("All stores returned by API"):
                all_pivot = pd.DataFrame(rows).pivot_table(
                    index="Product", columns="Store", values="Stock", aggfunc="first"
                )
                all_pivot.columns.name = None
                st.dataframe(all_pivot, use_container_width=True)
    else:
        st.warning("No data returned.")
else:
    st.info("Configure products and stores in the sidebar, then click **Check stock**.")
