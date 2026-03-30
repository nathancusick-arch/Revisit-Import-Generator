import streamlit as st
import pandas as pd
import io

st.set_page_config(page_title="Revisit Import Generator", layout="wide")

st.title("Revisit Import Generator")

# =========================
# Helpers
# =========================

def load_file(file):
    if file.name.endswith(".csv"):
        return pd.read_csv(file)
    elif file.name.endswith(".xlsx") or file.name.endswith(".xlsm"):
        return pd.read_excel(file)
    else:
        raise ValueError("Unsupported file type")

def normalise_fail(series):
    return series.astype(str).str.lower().str.contains("fail", na=False)

# =========================
# Upload Section
# =========================

st.header("1. Upload Files")

audit_file = st.file_uploader("Upload Audit Export (.csv)", type=["csv"])
store_file = st.file_uploader("Upload Store Database (.csv, .xlsx, .xlsm)", type=["csv", "xlsx", "xlsm"])
revisit_file = st.file_uploader("Upload Existing Revisits (Optional)", type=["csv"])

# =========================
# Settings
# =========================

st.header("2. Settings")

split_option = st.selectbox(
    "Split Imports By",
    ["item_to_order", "order_internal_id"]
)

visit_info = st.text_area("Visit Info (Optional)")

# =========================
# Generate
# =========================

st.header("3. Generate")

if st.button("Generate Imports"):

    if not audit_file or not store_file:
        st.error("Please upload both Audit Export and Store Database.")
        st.stop()

    try:
        audit_df = load_file(audit_file)
        store_df = load_file(store_file)

        revisit_df = None
        if revisit_file:
            revisit_df = load_file(revisit_file)

    except Exception as e:
        st.error(f"Error loading files: {e}")
        st.stop()

    # =========================
    # Validate Required Columns
    # =========================

    required_audit_cols = ["site_internal_id", "primary_result", split_option, "client_name"]
    required_store_cols = ["Site Internal ID", "Pass Email", "Fail Email", "Abort Email"]

    for col in required_audit_cols:
        if col not in audit_df.columns:
            st.error(f"Missing column in audit export: {col}")
            st.stop()

    for col in required_store_cols:
        if col not in store_df.columns:
            st.error(f"Missing column in store DB: {col}")
            st.stop()

    # =========================
    # Filter Fails
    # =========================

    audit_df = audit_df[normalise_fail(audit_df["primary_result"])]

    if audit_df.empty:
        st.warning("No failed audits found.")
        st.stop()

    # =========================
    # Exclude Existing Revisits
    # =========================

    if revisit_df is not None:
        required_revisit_cols = ["site_internal_id", "item_to_order"]

        for col in required_revisit_cols:
            if col not in revisit_df.columns:
                st.error(f"Missing column in revisits file: {col}")
                st.stop()

        revisit_keys = set(
            zip(revisit_df["site_internal_id"], revisit_df["item_to_order"])
        )

        audit_df = audit_df[
            ~audit_df.apply(
                lambda row: (row["site_internal_id"], row["item_to_order"]) in revisit_keys,
                axis=1
            )
        ]

    if audit_df.empty:
        st.warning("No audits remaining after exclusions.")
        st.stop()

    # =========================
    # Join Store DB
    # =========================

    merged_df = audit_df.merge(
        store_df,
        left_on="site_internal_id",
        right_on="Site Internal ID",
        how="left"
    )

    # =========================
    # Validation - Missing Sites
    # =========================

    missing_sites = merged_df[merged_df["Site Internal ID"].isna()]["site_internal_id"].unique()

    if len(missing_sites) > 0:
        st.error("The following site IDs are missing from the Store DB:")
        st.write(list(missing_sites))
        st.stop()

    # =========================
    # Build Output Columns
    # =========================

    merged_df["visit_info"] = visit_info

    output_df = pd.DataFrame({
        "site_internal_id": merged_df["site_internal_id"],
        "visit_info": merged_df["visit_info"],
        "report_PASS_full": merged_df["Pass Email"],
        "report_FAIL_full": merged_df["Fail Email"],
        "report_ABORT_full": merged_df["Abort Email"]
    })

    # =========================
    # Get Client Name
    # =========================

    client_name = str(audit_df["client_name"].dropna().iloc[0]).replace(" ", "_")

    # =========================
    # Split and Generate Files
    # =========================

    files = {}

    for group_value, group_df in merged_df.groupby(split_option):

        group_output = pd.DataFrame({
            "site_internal_id": group_df["site_internal_id"],
            "visit_info": visit_info,
            "report_PASS_full": group_df["Pass Email"],
            "report_FAIL_full": group_df["Fail Email"],
            "report_ABORT_full": group_df["Abort Email"]
        })

        if group_output.empty:
            continue

        filename = f"import_{str(group_value).replace(' ', '_')}_{client_name}.csv"

        csv_buffer = io.StringIO()
        group_output.to_csv(csv_buffer, index=False)

        files[filename] = csv_buffer.getvalue()

    # =========================
    # Output Downloads
    # =========================

    if not files:
        st.warning("No files were generated.")
        st.stop()

    st.success(f"{len(files)} import file(s) generated.")

    for filename, filedata in files.items():
        st.download_button(
            label=f"Download {filename}",
            data=filedata,
            file_name=filename,
            mime="text/csv"
        )
