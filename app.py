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

# --- HELPERS ---
def normalize_text(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r'[^a-z0-9\s\+\-]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

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

    # Load Reference Data
    mapping_df = pd.read_excel(mapping_file) if mapping_file else None
    listed_pairs, ref_drugs = set(), set()
    if listed_ref_file:
        ref_df = pd.read_excel(listed_ref_file)
        for _, r in ref_df.iterrows():
            dn, lt = normalize_text(str(r.iloc[0])), normalize_text(str(r.iloc[1]))
            listed_pairs.add((dn, lt)); ref_drugs.add(dn)

    if uploaded_files and st.button("Process Files"):
        all_rows = []
        for uploaded_file in uploaded_files:
            tree = ET.parse(uploaded_file)
            root = tree.getroot()
            ns = {'hl7': 'urn:hl7-org:v3'}
            
            # Basic Info
            creation_raw = root.find('.//hl7:creationTime', ns).attrib.get('value', '')
            trans_date = format_date(creation_raw)
            
            # Validity Logic
            has_patient = root.find('.//hl7:administrativeGenderCode', ns) is not None
            case_products_norm = set()
            suspect_ids = [caus.find('.//hl7:id', ns).attrib.get('root') for caus in root.findall('.//hl7:causalityAssessment', ns) if caus.find('.//hl7:value', ns).attrib.get('code') == '1']

            # Product Parsing
            prod_displays = []
            for drug in root.findall('.//hl7:substanceAdministration', ns):
                if drug.find('.//hl7:id', ns).attrib.get('root') in suspect_ids:
                    name_elem = drug.find('.//hl7:kindOfProduct/hl7:name', ns)
                    raw_name = name_elem.text if name_elem is not None else "Unknown"
                    norm_name = normalize_text(raw_name)
                    for p in company_products:
                        if normalize_text(p) in norm_name:
                            case_products_norm.add(normalize_text(p))
                            prod_displays.append(f"Drug: {raw_name}")

            # Event Parsing & Listedness
            event_displays = []
            is_valid = has_patient and len(case_products_norm) > 0
            
            for reaction in root.findall('.//hl7:observation', ns):
                if reaction.find('hl7:code', ns).attrib.get('displayName') == 'reaction':
                    val = reaction.find('hl7:value', ns)
                    llt_code = val.attrib.get('code', '')
                    llt_term = ""
                    if mapping_df is not None:
                        match = mapping_df[mapping_df['LLT Code'].astype(str) == str(llt_code)]
                        if not match.empty: llt_term = str(match['LLT Term'].values[0])
                    
                    # Apply v1.5.0 Logic: Omit listedness for Non-Valid
                    if is_valid:
                        l_status = assess_event_listedness(normalize_text(llt_term), case_products_norm, listed_pairs, ref_drugs)
                        event_displays.append(f"Event: {llt_term} (Listedness: {l_status})")
                    else:
                        event_displays.append(f"Event: {llt_term}")

            assessment = "Valid" if is_valid else "Non-Valid (Missing Patient or Product)"
            all_rows.append({
                "File Name": uploaded_file.name,
                "App Assessment": assessment,
                "Transmission Date": trans_date,
                "Product Details": "\n".join(prod_displays),
                "Event Details": "\n".join(event_displays)
            })

        st.session_state["df_display"] = pd.DataFrame(all_rows)
        st.success("Processing complete!")

with tab2:
    if "df_display" in st.session_state:
        st.data_editor(st.session_state["df_display"], use_container_width=True)







