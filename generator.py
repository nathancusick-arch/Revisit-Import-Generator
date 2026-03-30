import streamlit as st
import pandas as pd
import io
import zipfile

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
        "Could not find required column headers in the first 5 rows. "
        "Ensure the file includes: Site Internal ID, Pass Email, Fail Email, Abort Email."
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

store_file = st.file_uploader(
    "Store Database",
    type=["csv", "xlsx", "xlsm"]
)

st.info(
    """
**Store DB requirements:**

- Must include a column header named **Site Internal ID**
- Must include column headers named **Pass Email**, **Fail Email**, and **Abort Email**
- These headers can appear anywhere within the first 5 rows of the file
"""
)

revisit_file = st.file_uploader("Existing Revisits (Optional)", type=["csv"])

# =========================
# Settings
# =========================

st.header("2. Settings")

split_option = st.selectbox(
    "Split Imports By",
    ["item_to_order", "order_internal_id"]
)

result_filter = st.selectbox(
    "Revisits For",
    ["Fails Only", "Aborts Only", "Fails and Aborts"]
)

# ---- Visit Info ----

visit_info_toggle = st.toggle(
    "Take Visit Info from Store DB",
    key="visit_info_toggle"
)

if not visit_info_toggle:
    st.session_state.visit_info_text = st.text_area(
        "Visit Info (Optional)",
        value=st.session_state.visit_info_text
    )
else:
    st.info(
        """
**Store DB requirement for Visit Info:**

- Must include a column header named **Visit Info**
"""
    )

st.markdown("")
st.toggle(
    "Take Visit Info from Store DB",
    key="visit_info_toggle"
)

# =========================
# Generate Section
# =========================

st.header("3. Generate")

download_zip = st.toggle("Download all files as a ZIP", value=False)

if st.button("Generate Imports"):

    st.session_state.generated_files = None

    if not audit_file or not store_file:
        st.error("Please upload both Audit Export and Store Database.")
        st.stop()

    try:
        audit_df = load_audit_file(audit_file)
        store_df = load_store_file(store_file)
        revisit_df = load_revisit_file(revisit_file) if revisit_file else None
    except Exception as e:
        st.error(f"Error loading files: {e}")
        st.stop()

    required_audit_cols = ["site_internal_id", "primary_result", split_option, "client_name"]

    for col in required_audit_cols:
        if col not in audit_df.columns:
            st.error(f"Missing column in audit export: {col}")
            st.stop()

    # Filter
    audit_df = audit_df[normalise_result(audit_df["primary_result"], result_filter)]

    if audit_df.empty:
        st.warning("No matching audits found based on selected filter.")
        st.stop()

    # Exclusions
    if revisit_df is not None:
        required_revisit_cols = ["site_internal_id", "item_to_order"]

        for col in required_revisit_cols:
            if col not in revisit_df.columns:
                st.error(f"Missing column in revisits file: {col}")
                st.stop()

        revisit_keys = set(zip(
            revisit_df["site_internal_id"],
            revisit_df["item_to_order"]
        ))

        audit_df = audit_df[
            ~audit_df.apply(
                lambda row: (row["site_internal_id"], row["item_to_order"]) in revisit_keys,
                axis=1
            )
        ]

    if audit_df.empty:
        st.warning("No audits remaining after exclusions.")
        st.stop()

    # Merge
    merged_df = audit_df.merge(
        store_df,
        left_on="site_internal_id",
        right_on="Site Internal ID",
        how="left"
    )

    # Validation
    missing_sites = merged_df[merged_df["Site Internal ID"].isna()]["site_internal_id"].unique()

    if len(missing_sites) > 0:
        st.error("The following site IDs are missing from the Store DB:")
        st.write(list(missing_sites))
        st.stop()

    if visit_info_toggle and "Visit Info" not in merged_df.columns:
        st.error("Store DB must include a 'Visit Info' column when toggle is enabled.")
        st.stop()

    client_name = clean_filename(
        audit_df["client_name"].dropna().iloc[0]
    )

    # Generate Files
    files = {}

    for group_value, group_df in merged_df.groupby(split_option):

        output_data = {
            "site_internal_id": group_df["site_internal_id"],
            "report_PASS_full": group_df["Pass Email"],
            "report_FAIL_full": group_df["Fail Email"],
            "report_ABORT_full": group_df["Abort Email"]
        }

        # Visit Info logic
        if visit_info_toggle:
            output_data["visit_info"] = group_df["Visit Info"]
        elif st.session_state.visit_info_text.strip() != "":
            output_data["visit_info"] = st.session_state.visit_info_text

        output_df = pd.DataFrame(output_data)

        if output_df.empty:
            continue

        filename = f"import_{clean_filename(group_value)}_{client_name}.csv"

        csv_buffer = io.StringIO()
        output_df.to_csv(csv_buffer, index=False)

        files[filename] = csv_buffer.getvalue()

    if not files:
        st.warning("No files were generated.")
    else:
        st.session_state.generated_files = files

# =========================
# Output Section
# =========================

if st.session_state.generated_files:

    st.success(f"{len(st.session_state.generated_files)} import file(s) generated.")

    if download_zip:
        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(zip_buffer, "w") as zf:
            for filename, filedata in st.session_state.generated_files.items():
                zf.writestr(filename, filedata)

        st.download_button(
            label="Download All as ZIP",
            data=zip_buffer.getvalue(),
            file_name="revisit_imports.zip",
            mime="application/zip"
        )
    else:
        st.subheader("Downloads")

        for filename, filedata in st.session_state.generated_files.items():
            st.download_button(
                label=f"Download {filename}",
                data=filedata,
                file_name=filename,
                mime="text/csv"
            )
