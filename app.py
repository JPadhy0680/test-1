import streamlit as st
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, date
import io
import re
import calendar
from typing import Optional, Set, List

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

def parse_dd_mmm_yy(s):
    return datetime.strptime(s, "%d-%b-%y").date()

# Product Launch Data for v1.5.2 Validity
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
    "cyclogest": ("launched", None),
    "progesterone": ("launched", None),
    "luteum": ("launched", None),
    "amelgen": ("launched", None),
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

def get_launch_date(product_name: str) -> Optional[date]:
    info = LAUNCH_INFO.get(normalize_text(product_name))
    if info and info[0] == "launched": return info[1]
    return None

def assess_event_listedness(llt_norm, suspect_prods_norm, listed_pairs, ref_drugs) -> str:
    if not listed_pairs: return "Reference not uploaded"
    suspect_in_ref = {p for p in suspect_prods_norm if p in ref_drugs}
    if not suspect_in_ref: return "Reference not updated"
    for p in suspect_in_ref:
        if (p, llt_norm) in listed_pairs: return "Listed"
    return "Unlisted"

# --- MAIN LOGIC ---
tab1, tab2 = st.tabs(["Upload & Parse", "Export & Edit"])

with tab1:
    uploaded_files = st.file_uploader("Upload E2B XMLs", type=["xml"], accept_multiple_files=True)
    mapping_file = st.file_uploader("Upload LLT-PT Mapping (Excel)", type=["xlsx"])
    listed_ref_file = st.file_uploader("Upload Listedness Ref (Excel)", type=["xlsx"])

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
            try:
                tree = ET.parse(uploaded_file)
                root = tree.getroot()
                ns = {'hl7': 'urn:hl7-org:v3'}
                
                # 1. Transmission Date
                creation_elem = root.find('.//hl7:creationTime', ns)
                creation_raw = creation_elem.attrib.get('value', '') if creation_elem is not None else ''
                trans_date_obj = parse_date_obj(creation_raw)
                
                # 2. Patient Validity
                has_patient = root.find('.//hl7:administrativeGenderCode', ns) is not None
                
                # 3. Product Parsing (Safe Attribute Access)
                suspect_ids = []
                for caus in root.findall('.//hl7:causalityAssessment', ns):
                    val_elem = caus.find('.//hl7:value', ns)
                    id_elem = caus.find('.//hl7:subject2/hl7:productUseReference/hl7:id', ns)
                    if val_elem is not None and val_elem.attrib.get('code') == '1' and id_elem is not None:
                        suspect_ids.append(id_elem.attrib.get('root'))

                case_products_norm = set()
                prod_displays = []
                prod_launched_at_time = False

                for drug in root.findall('.//hl7:substanceAdministration', ns):
                    drug_id_elem = drug.find('.//hl7:id', ns)
                    if drug_id_elem is not None and drug_id_elem.attrib.get('root') in suspect_ids:
                        name_elem = drug.find('.//hl7:kindOfProduct/hl7:name', ns)
                        raw_name = name_elem.text if name_elem is not None else "Unknown"
                        
                        for p in company_products:
                            if normalize_text(p) in normalize_text(raw_name):
                                p_norm = normalize_text(p)
                                case_products_norm.add(p_norm)
                                prod_displays.append(f"Drug: {raw_name}")
                                
                                # Launch Date Check (v1.5.2)
                                l_date = get_launch_date(p_norm)
                                if l_date is None or (trans_date_obj and trans_date_obj >= l_date):
                                    prod_launched_at_time = True

                # 4. Event Parsing
                event_displays = []
                for reaction in root.findall('.//hl7:observation', ns):
                    obs_code = reaction.find('hl7:code', ns)
                    if obs_code is not None and obs_code.attrib.get('displayName') == 'reaction':
                        val_elem = reaction.find('hl7:value', ns)
                        llt_code = val_elem.attrib.get('code', '') if val_elem is not None else ''
                        llt_term = "Unknown Term"
                        if mapping_df is not None and llt_code:
                            match = mapping_df[mapping_df['LLT Code'].astype(str) == str(llt_code)]
                            if not match.empty: llt_term = str(match['LLT Term'].values[0])
                        
                        # Listedness (v1.5.0: Only for Valid cases)
                        if has_patient and prod_launched_at_time:
                            l_stat = assess_event_listedness(normalize_text(llt_term), case_products_norm, listed_pairs, ref_drugs)
                            event_displays.append(f"Event: {llt_term} ({l_stat})")
                        else:
                            event_displays.append(f"Event: {llt_term}")

                # 5. Final Assessment
                reasons = []
                if not has_patient: reasons.append("No Patient Details")
                if not case_products_norm: reasons.append("No Company Product")
                elif not prod_launched_at_time: reasons.append("Product not launched at transmission")
                
                assessment = "Valid" if not reasons else f"Non-Valid ({', '.join(reasons)})"
                
                all_rows.append({
                    "File": uploaded_file.name,
                    "App Assessment": assessment,
                    "Transmission Date": format_date(creation_raw),
                    "Products": "\n".join(prod_displays),
                    "Events": "\n".join(event_displays)
                })
            except Exception as e:
                st.error(f"Error processing {uploaded_file.name}: {e}")

        st.session_state["df_display"] = pd.DataFrame(all_rows)
        st.success("Triage Complete.")

with tab2:
    if "df_display" in st.session_state:
        st.data_editor(st.session_state["df_display"], use_container_width=True)







