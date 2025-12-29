import streamlit as st
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, date
import io
import re
import calendar
from typing import Optional, Set, Tuple

# --- INITIAL SETUP ---
st.set_page_config(page_title="E2B_R3 XML Triage Application", layout="wide")
st.title("📊🧠 E2B_R3 XML Triage Application 🛠️ 🚀")

# --- AUTHENTICATION ---
def _get_password():
    DEFAULT_PASSWORD = "7064242966"
    try:
        return st.secrets["auth"]["password"]
    except Exception:
        return DEFAULT_PASSWORD

def is_authenticated() -> bool:
    exp = st.session_state.get("auth_expires", None)
    if exp and datetime.now() < exp:
        return True
    return False

if not is_authenticated():
    password = st.text_input("Enter Password:", type="password")
    if password == _get_password():
        st.session_state["auth_expires"] = datetime.now() + timedelta(hours=24)
        st.success("Access granted.")
        st.rerun()
    else:
        if password: st.warning("Incorrect password.")
        st.stop()

# --- CONFIGURATION & LISTS ---
company_products = [
    "abiraterone", "apixaban", "apremilast", "bexarotene",
    "clobazam", "clonazepam", "cyanocobalamin", "dabigatran",
    "dapagliflozin", "dimethyl fumarate", "famotidine",
    "fesoterodine", "icatibant", "itraconazole", "linagliptin",
    "linagliptin + metformin", "nintedanib", "pirfenidone",
    "raltegravir", "ranolazine", "rivaroxaban", "saxagliptin",
    "sitagliptin", "tamsulosin + solifenacin", "tapentadol",
    "ticagrelor", "tamsulosin", "solifenacin",
    "cyclogest", "progesterone", "luteum", "amelgen"
]

category2_products = {
    "clobazam", "clonazepam", "cyanocobalamin",
    "famotidine", "itraconazole", "tamsulosin", 
    "solifenacin", "tapentadol", "cyclogest",
    "progesterone", "luteum", "amelgen"
}

# --- HELPER FUNCTIONS ---
def normalize_text(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r'[^a-z0-9\s\+\-]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

@st.cache_resource
def get_optimized_matcher(prod_list):
    valid_products = sorted([p for p in prod_list if normalize_text(p)], key=len, reverse=True)
    combined_pattern = r'\b(' + '|'.join(re.escape(normalize_text(p)) for p in valid_products) + r')\b'
    return re.compile(combined_pattern)

product_regex = get_optimized_matcher(company_products)

def contains_company_product_fast(text: str, regex) -> str:
    norm = normalize_text(text)
    match = regex.search(norm)
    return match.group(0) if match else ""

def format_date(date_str: str) -> str:
    digits = re.sub(r"\D", "", (date_str or "").strip())
    try:
        if len(digits) >= 8:
            return datetime.strptime(digits[:8], "%Y%m%d").strftime("%d-%b-%Y")
        return ""
    except: return ""

def parse_date_obj(date_str: str) -> Optional[date]:
    digits = re.sub(r"\D", "", (date_str or "").strip())
    try:
        if len(digits) >= 8:
            return datetime.strptime(digits[:8], "%Y%m%d").date()
        return None
    except: return None

def parse_dd_mmm_yy(s):
    return datetime.strptime(s, "%d-%b-%y").date()

LAUNCH_INFO = {
    "abiraterone": ("launched", parse_dd_mmm_yy("08-Sep-22")),
    "apixaban": ("launched", parse_dd_mmm_yy("26-Feb-25")),
    "apremilast": ("yet", None),
    "bexarotene": ("launched", parse_dd_mmm_yy("19-Jan-23")),
    "clobazam": ("launched", parse_dd_mmm_yy("26-Sep-24")),
    "clonazepam": ("launched", parse_dd_mmm_yy("20-Jan-25")),
    "dapagliflozin": ("launched_by_strength", {10.0: parse_dd_mmm_yy("26-Aug-25"), 5.0: parse_dd_mmm_yy("10-Sep-25")}),
    "dimethyl fumarate": ("launched", parse_dd_mmm_yy("05-Feb-24")),
    "famotidine": ("launched", parse_dd_mmm_yy("21-Feb-25")),
    "icatibant": ("launched", parse_dd_mmm_yy("28-Jul-22")),
    "pirfenidone": ("launched", parse_dd_mmm_yy("29-Jun-22")),
    "ranolazine": ("launched", parse_dd_mmm_yy("20-Jul-23")),
    "rivaroxaban": ("launched_by_strength", {2.5: parse_dd_mmm_yy("02-Apr-24"), 10.0: parse_dd_mmm_yy("23-May-24")}),
    "tapentadol": ("launched", parse_dd_mmm_yy("01-Feb-24")),
    "cyclogest": ("launched", None), # Special case: launched but no specific date provided
}

def get_launch_date(product_name: str, strength_mg: Optional[float]) -> Optional[date]:
    info = LAUNCH_INFO.get(normalize_text(product_name))
    if not info: return None
    status, payload = info
    if status == "launched": return payload
    if status == "launched_by_strength" and isinstance(payload, dict):
        return payload.get(strength_mg) if strength_mg in payload else min(payload.values())
    return None

def assess_event_listedness(llt_norm, suspect_prods_norm, listed_pairs, ref_drugs) -> str:
    if not listed_pairs: return "Reference not uploaded"
    suspect_in_ref = {p for p in suspect_prods_norm if p in ref_drugs}
    if not suspect_in_ref: return "Reference not updated"
    for p in suspect_in_ref:
        if (p, llt_norm) in listed_pairs: return "Listed"
    return "Unlisted"

# --- MAIN UI ---
tab1, tab2 = st.tabs(["Upload & Parse", "Export & Edit"])

with tab1:
    uploaded_files = st.file_uploader("Upload E2B XMLs", type=["xml"], accept_multiple_files=True)
    mapping_file = st.file_uploader("Upload LLT-PT Mapping (Excel)", type=["xlsx"])
    listed_ref_file = st.file_uploader("Upload Listedness Ref (Excel)", type=["xlsx"])

    mapping_df = pd.read_excel(mapping_file) if mapping_file else None
    listed_pairs = set()
    ref_drugs = set()
    if listed_ref_file:
        ref_df = pd.read_excel(listed_ref_file)
        for _, r in ref_df.iterrows():
            dn, lt = normalize_text(str(r.iloc[0])), normalize_text(str(r.iloc[1]))
            listed_pairs.add((dn, lt))
            ref_drugs.add(dn)

    if uploaded_files and st.button("Process Files"):
        all_rows = []
        for uploaded_file in uploaded_files:
            tree = ET.parse(uploaded_file)
            root = tree.getroot()
            ns = {'hl7': 'urn:hl7-org:v3'}
            
            # Transmission Date
            creation_raw = root.find('.//hl7:creationTime', ns).attrib.get('value', '')
            trans_date_obj = parse_date_obj(creation_raw)
            
            # Patient Details
            has_patient = root.find('.//hl7:administrativeGenderCode', ns) is not None
            
            # Product Parsing
            case_products_norm = set()
            case_drug_dates_display = []
            product_details = []
            
            suspect_ids = [caus.find('.//hl7:id', ns).attrib.get('root') 
                           for caus in root.findall('.//hl7:causalityAssessment', ns) 
                           if caus.find('.//hl7:value', ns).attrib.get('code') == '1']

            for drug in root.findall('.//hl7:substanceAdministration', ns):
                drug_id = drug.find('.//hl7:id', ns).attrib.get('root')
                if drug_id in suspect_ids:
                    name_elem = drug.find('.//hl7:kindOfProduct/hl7:name', ns)
                    raw_name = name_elem.text if name_elem is not None else ""
                    matched_prod = contains_company_product_fast(raw_name, product_regex)
                    
                    if matched_prod:
                        norm_p = normalize_text(matched_prod)
                        case_products_norm.add(norm_p)
                        product_details.append(f"Drug: {raw_name}")
                        case_drug_dates_display.append((norm_p, None, trans_date_obj))

            # Event Parsing
            event_details = []
            for reaction in root.findall('.//hl7:observation', ns):
                if reaction.find('hl7:code', ns).attrib.get('displayName') == 'reaction':
                    val = reaction.find('hl7:value', ns)
                    llt_code = val.attrib.get('code', '')
                    llt_term = ""
                    if mapping_df is not None:
                        match_row = mapping_df[mapping_df['LLT Code'].astype(str) == str(llt_code)]
                        if not match_row.empty:
                            llt_term = match_row['LLT Term'].values[0]
                    
                    l_status = assess_event_listedness(normalize_text(llt_term), case_products_norm, listed_pairs, ref_drugs)
                    event_details.append(f"Event: {llt_term} | Listedness: {l_status}")

            # VALIDITY BRAIN (v1.5.2)
            is_valid = True
            reasons = []
            if not has_patient:
                is_valid = False
                reasons.append("No Patient Details")
            if not case_products_norm:
                is_valid = False
                reasons.append("Non-company product")
            else:
                launched = False
                for p_norm, st_mg, t_obj in case_drug_dates_display:
                    l_date = get_launch_date(p_norm, st_mg)
                    # Valid if launched date is past OR status is launched but no date provided (e.g. Cyclogest)
                    if (l_date and t_obj and t_obj >= l_date) or (LAUNCH_INFO.get(p_norm, [None])[0] == "launched" and l_date is None):
                        launched = True
                        break
                if not launched:
                    is_valid = False
                    reasons.append("Product not yet launched")

            assessment = "Valid" if is_valid else f"Non-Valid ({', '.join(reasons)})"
            all_rows.append({"File": uploaded_file.name, "Assessment": assessment, "Products": "\n".join(product_details), "Events": "\n".join(event_details)})

        st.session_state["df_display"] = pd.DataFrame(all_rows)
        st.success("Parsing Complete!")

with tab2:
    if "df_display" in st.session_state:
        st.data_editor(st.session_state["df_display"], use_container_width=True)

