import streamlit as st
import pandas as pd
import io
import zipfile
import re

st.set_page_config(page_title="Revisit Import Generator")
st.title("Revisit Import Generator")

# =========================
# Session State
# =========================

if "generated_files" not in st.session_state:
    st.session_state.generated_files = None

if "visit_info_text" not in st.session_state:
    st.session_state.visit_info_text = ""

if "tokens_text" not in st.session_state:
    st.session_state.tokens_text = ""

# =========================
# Regex
# =========================

eircode_pattern = re.compile(r"^[A-Z]\d(?:\d|[A-Z])\s?[A-Z0-9]{4}$")
gb_postcode_pattern = re.compile(r"^[A-Z]{1,2}\d{1,2}[A-Z]?\s?\d[A-Z]{2}$")

# =========================
# Helpers
# =========================

def classify_country(postcode: str) -> str:
    if not postcode or str(postcode).strip() == "":
        return "GB"
    pc = str(postcode).strip().upper().replace("  ", " ")
    if eircode_pattern.match(pc):
        return "IE"
    if gb_postcode_pattern.match(pc):
        return "GB"
    return "GB"

def get_pc_prefix(pc):
    return str(pc).strip().upper().replace(" ", "")[:2]

def load_audit_file(file):
    return pd.read_csv(file)

def make_unique_columns(columns):
    seen = {}
    new_cols = []

    for col in columns:
        col_str = str(col)

        if col_str not in seen:
            seen[col_str] = 0
            new_cols.append(col_str)
        else:
            seen[col_str] += 1
            new_cols.append(f"{col_str}_{seen[col_str]}")

    return new_cols

def load_store_file(file, visit_info_required=False, email_type="Full", tokens_required=False):

    if email_type == "Full and Mini":
        email_headers = [
            "Pass Email Full", "Fail Email Full", "Abort Email Full",
            "Pass Email Mini", "Fail Email Mini", "Abort Email Mini"
        ]
    else:
        email_headers = ["Pass Email", "Fail Email", "Abort Email"]

    required_headers = ["Site Internal ID"] + email_headers + (
        ["Visit Info"] if visit_info_required else []
    ) + (
        ["Tokens"] if tokens_required else []
    )

    def extract_valid_sheet(raw_df):
        for i in range(5):
            row_values = raw_df.iloc[i].astype(str).tolist()
            if all(header in row_values for header in required_headers):
                df = raw_df.iloc[i+1:].copy()
                df.columns = raw_df.iloc[i]
                df.columns = make_unique_columns(df.columns)
                df = df.reset_index(drop=True)
                return df
        return None

    if file.name.endswith(".csv"):
        raw_df = pd.read_csv(file, header=None)
        df = extract_valid_sheet(raw_df)
        if df is None:
            raise ValueError(f"Missing required headers: {required_headers}")
        return df
    else:
        excel_file = pd.ExcelFile(file)
        valid_dfs = []

        for sheet in excel_file.sheet_names:
            raw_df = pd.read_excel(excel_file, sheet_name=sheet, header=None)
            df = extract_valid_sheet(raw_df)
            if df is not None:
                valid_dfs.append(df)

        if not valid_dfs:
            raise ValueError(f"Missing required headers in all sheets: {required_headers}")

        return pd.concat(valid_dfs, ignore_index=True)

def load_revisit_file(file):
    return pd.read_csv(file)

def load_tokens_file(file):
    return pd.read_excel(file, sheet_name="Overall")

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

email_type_for_help = st.session_state.get("email_type", "Full")

if email_type_for_help == "Full and Mini":
    st.info(
        """
**Store DB requirements:**

- Must include a column header named **Site Internal ID**
- Must include column headers named:
  - **Pass Email Full**, **Fail Email Full**, **Abort Email Full**
  - **Pass Email Mini**, **Fail Email Mini**, **Abort Email Mini**
- These headers can appear anywhere within the first 5 rows of the file (all sheets)
"""
    )
else:
    st.info(
        """
**Store DB requirements:**

- Must include a column header named **Site Internal ID**
- Must include column headers named **Pass Email**, **Fail Email**, and **Abort Email**
- These headers can appear anywhere within the first 5 rows of the file (all sheets)
"""
    )

revisit_file = st.file_uploader("Existing Revisits (Optional)", type=["csv"])

audit_type = st.session_state.get("audit_type", "SSL")

tokens_file = None
if audit_type in ["NARV", "Media Compliance"]:
    tokens_file = st.file_uploader("Upload 'NARV and MC Patches.xlsx'", type=["xlsx"])
elif audit_type == "Deliveries (WIP)":
    tokens_file = st.file_uploader("Upload 'Rapid Delivery Tokens August 25.xlsx'", type=["xlsx"])

# =========================
# Settings
# =========================

st.header("2. Settings")

audit_type = st.selectbox(
    "Audit Type",
    ["SSL", "NARV", "Media Compliance", "Deliveries (WIP)"],
    key="audit_type"
)

split_option = st.selectbox(
    "Split Imports By",
    ["item_to_order", "order_internal_id"]
)

result_filter = st.selectbox(
    "Revisits For",
    ["Fails Only", "Aborts Only", "Fails and Aborts"]
)

email_type = st.selectbox(
    "Email Type",
    ["Full", "Mini", "Full and Mini"],
    key="email_type"
)

# Visit Info

if not st.session_state.get("visit_info_toggle", False):
    st.session_state.visit_info_text = st.text_input(
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

visit_info_toggle = st.toggle(
    "Take Visit Info from Store DB",
    value=st.session_state.get("visit_info_toggle", False),
    key="visit_info_toggle"
)

# Tokens

if not st.session_state.get("tokens_toggle", False):
    st.session_state.tokens_text = st.text_input(
        "Tokens (Optional)",
        value=st.session_state.tokens_text,
        help="NARV / MC / Deliveries tokens not required here as long as the correct audit type is selected."
    )
else:
    st.info(
        """
**Store DB requirement for Tokens:**

- Must include a column header named **Tokens**
"""
    )

tokens_toggle = st.toggle(
    "Take Tokens from Store DB",
    value=st.session_state.get("tokens_toggle", False),
    key="tokens_toggle"
)

# =========================
# Generate Section
# =========================

st.header("3. Generate")

download_zip = st.toggle("Download all files as a ZIP", value=False)

if st.button("Generate Imports"):

    st.session_state.generated_files = None

    if not audit_file or not store_file:
        st.error("Please upload required files.")
        st.stop()

    if audit_type != "SSL" and not tokens_file:
        st.error("Please upload the required tokens file.")
        st.stop()

    try:
        audit_df = load_audit_file(audit_file)
        store_df = load_store_file(
            store_file,
            visit_info_required=visit_info_toggle,
            email_type=email_type,
            tokens_required=tokens_toggle
        )
        revisit_df = load_revisit_file(revisit_file) if revisit_file else None
        tokens_df = load_tokens_file(tokens_file) if tokens_file else None
    except Exception as e:
        import traceback
        st.error("An error occurred:")
        st.text(traceback.format_exc())
        st.stop()

    required_cols = ["site_internal_id", "primary_result", split_option, "client_name", "site_post_code"]

    for col in required_cols:
        if col not in audit_df.columns:
            st.error(f"Missing column: {col}")
            st.stop()

    audit_df = audit_df[normalise_result(audit_df["primary_result"], result_filter)]
    
    original_split_groups = audit_df[split_option].nunique()
    
    # =========================
    # Exclusions (REINSERTED)
    # =========================

    if revisit_df is not None:

        required_revisit_cols = ["site_internal_id", "item_to_order"]

        for col in required_revisit_cols:
            if col not in revisit_df.columns:
                st.error(f"Missing column in revisits file: {col}")
                st.stop()

        revisit_df["site_internal_id"] = revisit_df["site_internal_id"].astype(str)
        revisit_df["item_to_order"] = revisit_df["item_to_order"].astype(str)

        audit_df["site_internal_id"] = audit_df["site_internal_id"].astype(str)
        audit_df["item_to_order"] = audit_df["item_to_order"].astype(str)

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

    if audit_df.empty:
        st.warning("No matching audits.")
        st.stop()

    audit_df["country"] = audit_df["site_post_code"].apply(classify_country)

    merged_df = audit_df.merge(
        store_df,
        left_on="site_internal_id",
        right_on="Site Internal ID",
        how="left"
    )

    missing = merged_df[merged_df["Site Internal ID"].isna()]["site_internal_id"].unique()

    if len(missing) > 0:
        st.error("Missing site IDs in Store DB:")
        st.write(list(missing))
        st.stop()

    # Tokens logic unchanged

    if audit_type in ["NARV", "Media Compliance"]:
        col_map = {
            "NARV": "Region NARV",
            "Media Compliance": "MC Region"
        }

        lookup_col = col_map[audit_type]

        tokens_lookup = dict(
            zip(tokens_df["PC"].astype(str).str.upper(), tokens_df[lookup_col])
        )

        def assign_token(row):
            if row["country"] == "IE":
                return "NARV Ireland" if audit_type == "NARV" else "MC Ireland"
            prefix = get_pc_prefix(row["site_post_code"])
            return tokens_lookup.get(prefix, "")

        merged_df["base_tokens"] = merged_df.apply(assign_token, axis=1)

    elif audit_type == "Deliveries (WIP)":
        merged_df["base_tokens"] = ""
    else:
        merged_df["base_tokens"] = ""

    if tokens_toggle:
        merged_df["extra_tokens"] = merged_df["Tokens"]
    else:
        merged_df["extra_tokens"] = st.session_state.tokens_text

    merged_df["tokens"] = merged_df.apply(
        lambda r: ", ".join([t for t in [r["base_tokens"], r["extra_tokens"]] if str(t).strip() != ""]),
        axis=1
    )

    client_name = clean_filename(audit_df["client_name"].dropna().iloc[0])

    total_split_groups = original_split_groups
    total_countries = merged_df["country"].nunique()

    files = {}

    for group_value, group_df in merged_df.groupby(split_option):
        for country, sub_df in group_df.groupby("country"):

            output_data = {
                "site_internal_id": sub_df["site_internal_id"]
            }

            if email_type in ["Full", "Mini"]:
                suffix = "full" if email_type == "Full" else "mini"
                output_data[f"report_PASS_{suffix}"] = sub_df["Pass Email"]
                output_data[f"report_FAIL_{suffix}"] = sub_df["Fail Email"]
                output_data[f"report_ABORT_{suffix}"] = sub_df["Abort Email"]
            else:
                output_data["report_PASS_full"] = sub_df["Pass Email Full"]
                output_data["report_FAIL_full"] = sub_df["Fail Email Full"]
                output_data["report_ABORT_full"] = sub_df["Abort Email Full"]
                output_data["report_PASS_mini"] = sub_df["Pass Email Mini"]
                output_data["report_FAIL_mini"] = sub_df["Fail Email Mini"]
                output_data["report_ABORT_mini"] = sub_df["Abort Email Mini"]

            if visit_info_toggle:
                output_data["visit_info"] = sub_df["Visit Info"]
            elif st.session_state.visit_info_text.strip():
                output_data["visit_info"] = st.session_state.visit_info_text

            if audit_type != "SSL" or sub_df["tokens"].str.strip().any():
                output_data["tokens"] = sub_df["tokens"]

            output_df = pd.DataFrame(output_data)

            if output_df.empty:
                continue

            country_label = "UK" if country == "GB" else "IE"

            include_split = total_split_groups > 1
            include_country = total_countries > 1

            parts = ["import"]

            if include_split:
                parts.append(clean_filename(group_value))

            if include_country:
                parts.append(country_label)

            parts.append(client_name)

            filename = "_".join(parts) + ".csv"

            buffer = io.StringIO()
            output_df.to_csv(buffer, index=False)

            files[filename] = buffer.getvalue()

    if not files:
        st.warning("No files generated.")
    else:
        st.session_state.generated_files = files

# =========================
# Output Section
# =========================

if st.session_state.generated_files:

    st.success(f"{len(st.session_state.generated_files)} file(s) generated.")

    if download_zip:
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            for name, data in st.session_state.generated_files.items():
                zf.writestr(name, data)

        st.download_button("Download All as ZIP", zip_buffer.getvalue(), "revisit_imports.zip")

    else:
        for name, data in st.session_state.generated_files.items():
            st.download_button(f"Download {name}", data, name)
