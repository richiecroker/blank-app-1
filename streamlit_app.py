import streamlit as st
import requests
import pandas as pd

st.set_page_config(page_title="Screwfix Stock Checker", layout="wide")
st.title("Screwfix Stock Checker")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://www.screwfix.com/",
}

DEFAULT_PRODUCTS = ["931AX", "835XG", "730XG"]
DEFAULT_STORES = ["IC4", "MT8", "SB6"]

with st.sidebar:
    st.header("Configuration")
    products_input = st.text_area(
        "Product codes (one per line)",
        value="\n".join(DEFAULT_PRODUCTS),
    )
    stores_input = st.text_area(
        "Store codes (one per line)",
        value="\n".join(DEFAULT_STORES),
    )
    run = st.button("Check stock", type="primary", use_container_width=True)

product_codes = [p.strip().upper() for p in products_input.splitlines() if p.strip()]
store_codes = [s.strip().upper() for s in stores_input.splitlines() if s.strip()]

def check_stock(product_code, store_id):
    url = f"https://www.screwfix.com/checkstock?productCode={product_code}&storeId={store_id}"
    r = requests.get(url, headers=HEADERS, timeout=10)
    r.raise_for_status()
    return r.json()

if run:
    results = []
    total = len(product_codes) * len(store_codes)
    progress = st.progress(0, text="Checking stock...")
    i = 0

    for store in store_codes:
        for product in product_codes:
            try:
                data = check_stock(product, store)
                # Try to extract quantity/availability from response
                # Common patterns in retail APIs
                if isinstance(data, dict):
                    qty = (
                        data.get("quantity")
                        or data.get("stock")
                        or data.get("stockLevel")
                        or data.get("availableQuantity")
                        or data.get("qty")
                    )
                    in_stock = (
                        data.get("inStock")
                        or data.get("available")
                        or data.get("isAvailable")
                    )
                    if qty is None and in_stock is None:
                        status = str(data)
                    elif qty is not None:
                        status = int(qty)
                    else:
                        status = "✅ In stock" if in_stock else "❌ Out of stock"
                else:
                    status = str(data)
                results.append({"Store": store, "Product": product, "Stock": status, "Error": None})
            except requests.HTTPError as e:
                results.append({"Store": store, "Product": product, "Stock": None, "Error": str(e)})
            except Exception as e:
                results.append({"Store": store, "Product": product, "Stock": None, "Error": str(e)})
            i += 1
            progress.progress(i / total, text=f"Checked {product} @ {store}")

    progress.empty()

    df = pd.DataFrame(results)
    errors = df[df["Error"].notna()]
    ok = df[df["Error"].isna()].drop(columns="Error")

    if not ok.empty:
        # Pivot: stores as rows, products as columns
        pivot = ok.pivot(index="Store", columns="Product", values="Stock")
        pivot.columns.name = None
        pivot.index.name = "Store"
        st.subheader("Results")
        st.dataframe(pivot, use_container_width=True)

        # Also show raw JSON for first result so we can verify field names
        with st.expander("Raw response debug (first item)"):
            try:
                first = ok.iloc[0]
                raw = check_stock(first["Product"], first["Store"])
                st.json(raw)
            except Exception as e:
                st.write(str(e))

    if not errors.empty:
        st.subheader("Errors")
        st.dataframe(errors[["Store", "Product", "Error"]], use_container_width=True)
else:
    st.info("Configure products and stores in the sidebar, then click **Check stock**.")
