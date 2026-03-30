import streamlit as st
import pandas as pd
import io
import zipfile
import re

st.set_page_config(page_title="Revisit Import Generator")

st.title("Revisit Import Generator")

# =========================
# Session State Init
# =========================

if "generated_files" not in st.session_state:
    st.session_state.generated_files = None

if "visit_info_text" not in st.session_state:
    st.session_state.visit_info_text = ""

# =========================
# Helpers
# =========================

eircode_pattern = re.compile(r"^[A-Z]\d{2}\s?[A-Z0-9]{4}$")
gb_postcode_pattern = re.compile(r"^(?!BT)[A-Z]{1,2}\d{1,2}[A-Z]?\s?\d[A-Z]{2}$")

def classify_country(postcode: str) -> str:
    if not postcode or str(postcode).strip() == "":
        return "IE"
    pc = str(postcode).strip().upper().replace("  ", " ")
    if pc.startswith("BT"):
        return "IE"
    if eircode_pattern.match(pc):
        return "IE"
    if gb_postcode_pattern.match(pc):
        return "GB"
    return "IE"

def load_audit_file(file):
    return pd.read_csv(file)

def load_store_file(file):
    if file.name.endswith(".csv"):
        raw_df = pd.read_csv(file, header=None)
    else:
        raw_df = pd.read_excel(file, header=None)

    required_headers = ["Site Internal ID", "Pass Email", "Fail Email", "Abort Email"]

    for i in range(5):
        row_values = raw_df.iloc[i].astype(str).tolist()

        if all(header in row_values for header in required_headers):
            df = raw_df.iloc[i+1:].copy()
            df.columns = raw_df.iloc[i]
            df = df.reset_index(drop=True)
            return df

    raise ValueError(
        "Could not find required column headers in the first 5 rows."
    )

def load_revisit_file(file):
    return pd.read_csv(file)

def normalise_result(series, mode):
    s = series.astype(str).str.lower()

    if mode == "Fails Only":
        return s.str.contains("fail", na=False)
    elif mode == "Aborts Only":
        return s.str.contains("abort", na=False)
    elif mode == "Fails and Aborts":
        return s.str.contains("fail", na=False) | s.str.contains("abort", na=False)

def clean_filename(value):
    return str(value).replace(" ", "_").replace("/", "_")

# =========================
# Upload Section
# =========================

st.header("1. Upload Files")

audit_file = st.file_uploader("Audit Export", type=["csv"])
store_file = st.file_uploader("Store Database", type=["csv", "xlsx", "xlsm"])

st.info("""
**Store DB requirements:**

- Must include **Site Internal ID**
- Must include **Pass Email, Fail Email, Abort Email**
- Headers must be within first 5 rows
""")

revisit_file = st.file_uploader("Existing Revisits (Optional)", type=["csv"])

# =========================
# Settings
# =========================

st.header("2. Settings")

split_option = st.selectbox("Split Imports By", ["item_to_order", "order_internal_id"])

result_filter = st.selectbox(
    "Revisits For",
    ["Fails Only", "Aborts Only", "Fails and Aborts"]
)

# Visit Info
if not st.session_state.get("visit_info_toggle", False):
    st.session_state.visit_info_text = st.text_area(
        "Visit Info (Optional)",
        value=st.session_state.visit_info_text
    )
else:
    st.info("Store DB must include a **Visit Info** column")

visit_info_toggle = st.toggle(
    "Take Visit Info from Store DB",
    value=st.session_state.get("visit_info_toggle", False),
    key="visit_info_toggle"
)

# =========================
# Generate
# =========================

st.header("3. Generate")

download_zip = st.toggle("Download all files as a ZIP", value=False)

if st.button("Generate Imports"):

    st.session_state.generated_files = None

    if not audit_file or not store_file:
        st.error("Upload required files.")
        st.stop()

    audit_df = load_audit_file(audit_file)
    store_df = load_store_file(store_file)
    revisit_df = load_revisit_file(revisit_file) if revisit_file else None

    required_cols = ["site_internal_id", "primary_result", split_option, "client_name", "site_post_code"]

    for col in required_cols:
        if col not in audit_df.columns:
            st.error(f"Missing column: {col}")
            st.stop()

    # Filter
    audit_df = audit_df[normalise_result(audit_df["primary_result"], result_filter)]

    # Classify country
    audit_df["country"] = audit_df["site_post_code"].apply(classify_country)

    # Merge
    merged_df = audit_df.merge(
        store_df,
        left_on="site_internal_id",
        right_on="Site Internal ID",
        how="left"
    )

    client_name = clean_filename(audit_df["client_name"].dropna().iloc[0])

    files = {}

    for group_value, group_df in merged_df.groupby(split_option):

        # Split by country inside group
        for country, sub_df in group_df.groupby("country"):

            output_data = {
                "site_internal_id": sub_df["site_internal_id"],
                "report_PASS_full": sub_df["Pass Email"],
                "report_FAIL_full": sub_df["Fail Email"],
                "report_ABORT_full": sub_df["Abort Email"]
            }

            if visit_info_toggle:
                output_data["visit_info"] = sub_df["Visit Info"]
            elif st.session_state.visit_info_text.strip():
                output_data["visit_info"] = st.session_state.visit_info_text

            output_df = pd.DataFrame(output_data)

            if output_df.empty:
                continue

            # Only add suffix if multiple countries exist in group
            countries_in_group = group_df["country"].nunique()

            suffix = f"_{'UK' if country == 'GB' else 'IE'}" if countries_in_group > 1 else ""

            filename = f"import_{clean_filename(group_value)}{suffix}_{client_name}.csv"

            csv_buffer = io.StringIO()
            output_df.to_csv(csv_buffer, index=False)

            files[filename] = csv_buffer.getvalue()

    st.session_state.generated_files = files

# =========================
# Output
# =========================

if st.session_state.generated_files:

    if download_zip:
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            for f, d in st.session_state.generated_files.items():
                zf.writestr(f, d)

        st.download_button("Download ZIP", zip_buffer.getvalue(), "imports.zip")
    else:
        for f, d in st.session_state.generated_files.items():
            st.download_button(f, d, f)
