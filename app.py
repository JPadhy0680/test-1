
import streamlit as st
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, date
import io
import re
import calendar  # used for date parsing (last-day-of-month)

# --- App configuration ---
st.set_page_config(page_title="E2B_R3 XML Parser Application", layout="wide")
st.markdown(""" """, unsafe_allow_html=True)
st.title("📊🧠 E2B_R3 XML Parser Application 🛠️ 🚀")

# --- Version header ---
# Baseline v1.0 (do-not-modify core behaviors)
# v1.1: Add Validity assessment + replace st.experimental_rerun() with st.rerun()
# v1.2: Extend Validity assessment with "Product not Launched" rule
# v1.3: Add Comment column and auto-message when PL/PLGB/PLNI numbers are found in product text
# v1.3.1: Patch 1 — strength-gated products use earliest strength launch date if strength is unknown
# v1.4: Lot number detection — comment-only flags when lot text contains competitor/company names; numeric/alphanumeric lots considered valid

# --- Password with 24h persistence (uses st.secrets if present) ---
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
    password = st.text_input(
        "Enter Password to Access App:",
        type="password",
        help="Enter the password to unlock the application."
    )
    if password == _get_password():
        st.session_state["auth_expires"] = datetime.now() + timedelta(hours=24)
        st.success("Access granted for 24 hours.")
    else:
        if password:
            st.warning("Please enter the correct password to proceed.")
        st.stop()

# --- Instructions ---
with st.expander("📖 Instructions"):
    st.markdown("""
- Upload **multiple E2B XML files** and **LLT-PT mapping Excel file**.
- Parsed data appears in the **Export & Edit** tab.
- Columns **Listedness** and **App Assessment** remain editable; other computed columns are locked.
- Only **one Excel** download button is provided (no CSV/HTML/Summary).
""")

# --- Tabs ---
tab1, tab2 = st.tabs(["Upload & Parse", "Export & Edit"])
all_rows_display = []
current_date = datetime.now().strftime("%d-%b-%Y")

# --- Helper mappings & functions ---
def _digits_only(s: str) -> str:
    return re.sub(r"\D", "", (s or "").strip())

def format_date(date_str: str) -> str:
    """
    Friendly display for HL7 TS with variable precision.
    - YYYYMMDD -> DD-Mon-YYYY
    - YYYYMM   -> Mon-YYYY
    - YYYY     -> YYYY
    Returns empty string if parsing fails.
    """
    if not date_str:
        return ""
    digits = _digits_only(date_str)
    try:
        if len(digits) >= 8:
            dt = datetime.strptime(digits[:8], "%Y%m%d").date()
            return dt.strftime("%d-%b-%Y")
        elif len(digits) >= 6:
            year = int(digits[:4])
            month = int(digits[4:6])
            return datetime(year, month, 1).strftime("%b-%Y")
        elif len(digits) >= 4:
            year = int(digits[:4])
            return f"{year}"
        else:
            return ""
    except Exception:
        return ""

def parse_date_obj(date_str: str):
    """
    Robust date object for comparisons:
    - YYYYMMDD -> the exact date
    - YYYYMM   -> last day of that month
    - YYYY     -> Dec 31 of that year
    Returns None if parsing fails or input empty.
    """
    if not date_str:
        return None
    digits = _digits_only(date_str)
    try:
        if len(digits) >= 8:
            return datetime.strptime(digits[:8], "%Y%m%d").date()
        elif len(digits) >= 6:
            year = int(digits[:4])
            month = int(digits[4:6])
            last_day = calendar.monthrange(year, month)[1]
            return datetime(year, month, last_day).date()
        elif len(digits) >= 4:
            year = int(digits[:4])
            return datetime(year, 12, 31).date()
        else:
            return None
    except Exception:
        return None

def map_reporter(code):
    return {
        "1": "Physician",
        "2": "Pharmacist",
        "3": "Other health professional",
        "4": "Lawyer",
        "5": "Consumer or other non-health professional"
    }.get(code, "Unknown")

def map_gender(code):
    return {"1": "Male", "2": "Female"}.get(code, "Unknown")

def map_outcome(code):
    return {
        "1": "Recovered/Resolved",
        "2": "Recovering/Resolving",
        "3": "Not recovered/Ongoing",
        "4": "Recovered with sequelae",
        "5": "Fatal",
        "0": "Unknown"
    }.get(code, "Unknown")

# Age unit mapping: a=year, b=month
age_unit_map = {"a": "year", "b": "month"}

# --- Unknown handling helpers (baseline behavior retained) ---
UNKNOWN_TOKENS = {"unk", "asku", "unknown"}  # lower-cased tokens

def is_unknown(value: str) -> bool:
    """Return True if value is one of UNK/ASKU/Unknown (case-insensitive, trimmed)."""
    if value is None:
        return True
    v = str(value).strip()
    if not v:
        return True
    return v.lower() in UNKNOWN_TOKENS

def clean_value(value: str) -> str:
    """Return empty string if value is unknown; otherwise return the original value."""
    return "" if is_unknown(value) else str(value)

# Normalization + inclusive matching
def normalize_text(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r'[^a-z0-9\s\+\-]', ' ', s)  # keep + and - for combos
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def contains_company_product(text: str, company_products: list) -> str:
    norm = normalize_text(text)
    for prod in company_products:
        pnorm = normalize_text(prod)
        if not pnorm:
            continue
        pattern = r'\b' + re.escape(pnorm) + r'\b'
        if re.search(pattern, norm):
            return prod
    return ""

# Robust strength (mg) extraction: supports "1,000 mg", "2.5 mg", case-insensitive
MG_PATTERN = re.compile(r"""
    (\d{1,3}(?:,\d{3})*\d+(?:\.\d{1,3})?)  # numeric value, supports thousands and decimals
    \s*
    mg\b                                  # mg unit, word boundary
""", re.IGNORECASE | re.VERBOSE)

def extract_strength_mg(raw_text: str, dose_val: str, dose_unit: str):
    """Try to extract strength in mg from raw text or doseQuantity."""
    # Priority 1: doseQuantity unit mg
    if dose_val and dose_unit and dose_unit.lower() == "mg":
        try:
            return float(str(dose_val).replace(",", ""))
        except Exception:
            pass
    # Priority 2: regex in raw text
    if raw_text:
        m = MG_PATTERN.search(raw_text or "")
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except Exception:
                pass
    return None

# --- PL number extraction (PL, PLGB, PLNI) ---
PL_PATTERN = re.compile(
    r'\b(PL|PLGB|PLNI)\s*([0-9]{5})\s*/\s*([0-9]{4,5})\b',
    re.IGNORECASE
)

def extract_pl_numbers(text: str):
    """Return list of normalized PL strings like 'PL 12345/0001' found in the text."""
    out = []
    if not text:
        return out
    for m in PL_PATTERN.finditer(text):
        prefix = m.group(1).upper()
        company_code = m.group(2)
        product_code = m.group(3)
        out.append(f"{prefix} {company_code}/{product_code}")
    return out

# Product portfolio (for matching & Category 2 flag only)
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
    "famotidine", "itraconazole",
    "tamsulosin", "solifenacin",
    "tapentadol", "cyclogest",
    "progesterone", "luteum", "amelgen"
}

# --- Launch dates (for validity comparison) ---
def parse_dd_mmm_yy(s):
    return datetime.strptime(s, "%d-%b-%y").date()

LAUNCH_INFO = {
    "abiraterone": ("launched", parse_dd_mmm_yy("08-Sep-22")),
    "apixaban": ("launched", parse_dd_mmm_yy("26-Feb-25")),
    "apremilast": ("yet", None),
    "bexarotene": ("launched", parse_dd_mmm_yy("19-Jan-23")),
    "clobazam": ("launched", parse_dd_mmm_yy("26-Sep-24")),
    "clonazepam": ("launched", parse_dd_mmm_yy("20-Jan-25")),
    "cyanocobalamin": ("awaited", None),
    "dabigatran": ("yet", None),
    "dapagliflozin": ("launched_by_strength", {10.0: parse_dd_mmm_yy("26-Aug-25"), 5.0: parse_dd_mmm_yy("10-Sep-25")}),
    "dimethyl fumarate": ("launched", parse_dd_mmm_yy("05-Feb-24")),
    "famotidine": ("launched", parse_dd_mmm_yy("21-Feb-25")),
    "fesoterodine": ("yet", None),
    "icatibant": ("launched", parse_dd_mmm_yy("28-Jul-22")),
    "itraconazole": ("awaited", None),  # treat as no launch date for validity rule
    "linagliptin": ("yet", None),
    "linagliptin + metformin": ("awaited", None),
    "nintedanib": ("awaited", None),
    "pirfenidone": ("launched", parse_dd_mmm_yy("29-Jun-22")),
    "raltegravir": ("awaited", None),
    "ranolazine": ("launched", parse_dd_mmm_yy("20-Jul-23")),
    "rivaroxaban": ("launched_by_strength", {
        2.5: parse_dd_mmm_yy("02-Apr-24"),
        10.0: parse_dd_mmm_yy("23-May-24"),
        15.0: parse_dd_mmm_yy("23-May-24"),
        20.0: parse_dd_mmm_yy("23-May-24"),
    }),
    "saxagliptin": ("yet", None),
    "sitagliptin": ("yet", None),
    "tamsulosin + solifenacin": ("launched", parse_dd_mmm_yy("08-May-23")),
    "tamsulosin": ("launched", parse_dd_mmm_yy("08-May-23")),
    "solifenacin": ("launched", parse_dd_mmm_yy("08-May-23")),
    "tapentadol": ("launched", parse_dd_mmm_yy("01-Feb-24")),
    "ticagrelor": ("yet", None),
    "cyclogest": ("launched", None),
    "progesterone": ("launched", None),
    "luteum": ("launched", None),
    "amelgen": ("launched", None),
}

# --- PATCH 1: updated function with conservative fallback for strength-gated products ---
def get_launch_date(product_name: str, strength_mg) -> date | None:
    """
    Return the launch date for a matched company product.
    - 'launched' -> return date if present (else None)
    - 'launched_by_strength' -> return date only if strength provided and matches;
      if strength is unknown, return the EARLIEST strength launch date (conservative fallback).
    - 'yet'/'awaited' -> None
    - unknown -> None
    """
    key = normalize_text(product_name)
    info = LAUNCH_INFO.get(key)
    if not info:
        return None
    status, payload = info
    if status == "launched":
        return payload  # may be None
    if status == "launched_by_strength":
        if isinstance(payload, dict) and payload:
            if strength_mg is not None:
                return payload.get(strength_mg)
            return min(payload.values())  # earliest strength launch date
        return None
    # 'yet' or 'awaited'
    return None

def get_launch_status(product_name: str) -> str | None:
    """Return 'launched', 'launched_by_strength', 'yet', 'awaited' or None if unknown."""
    key = normalize_text(product_name)
    info = LAUNCH_INFO.get(key)
    if not info:
        return None
    return info[0]

# --- v1.4: Company & lot detection helpers ---
MY_COMPANY_NAME = "celix"

DEFAULT_COMPETITOR_NAMES = {
    "glenmark", "cipla", "sun pharma", "dr reddy", "dr. reddy",
    "torrent", "lupin", "intas", "mankind", "micro labs", "zydus"
}

def contains_competitor_name(lot_text: str, competitor_names: set[str]) -> bool:
    """
    Return True if lot_text contains any competitor/company name (case-insensitive).
    Numeric/alphanumeric codes (e.g., 'A12345B') will not match unless they include a name.
    """
    if not lot_text:
        return False
    norm = lot_text.lower()
    # Do not flag if our own company name appears
    if MY_COMPANY_NAME.lower() in norm:
        return False
    for name in competitor_names:
        nm = (name or "").lower().strip()
        if nm and nm in norm:
            return True
    return False

# --- Upload & Parse tab ---
with tab1:
    st.markdown("### 🔎 Upload Files 🗂️")
    if st.button("Clear Inputs", help="Click to clear all uploaded files and reset the app."):
        st.session_state.clear()
        st.rerun()  # FIX: replace deprecated st.experimental_rerun()

    uploaded_files = st.file_uploader(
        "Upload E2B XML files",
        type=["xml"],
        accept_multiple_files=True,
        help="Upload one or more E2B XML files for parsing."
    )

    mapping_file = st.file_uploader(
        "Upload LLT-PT Mapping Excel file",
        type=["xlsx"],
        help="Upload the MedDRA LLT-PT mapping Excel file."
    )

    # Optional: Upload a competitor name list (Excel with column 'Company Identifiers')
    competitor_names = set(DEFAULT_COMPETITOR_NAMES)
    comp_file = st.file_uploader(
        "Upload Competitor Identifiers (Excel)",
        type=["xlsx"],
        help="Optional: Provide competitor/company names (one per row under 'Company Identifiers')."
    )
    if comp_file:
        try:
            comp_df = pd.read_excel(comp_file, engine="openpyxl")
            if "Company Identifiers" in comp_df.columns:
                competitor_names = set(
                    comp_df["Company Identifiers"].astype(str).str.lower().str.strip()
                )
        except Exception as e:
            st.warning(f"Could not read competitor identifier file: {e}")

    mapping_df = None
    if mapping_file:
        mapping_df = pd.read_excel(mapping_file, engine="openpyxl")
        if "LLT Code" in mapping_df.columns:
            mapping_df["LLT Code"] = mapping_df["LLT Code"].astype(str).str.strip()

    seriousness_map = {
        "resultsInDeath": "Death",
        "isLifeThreatening": "LT",
        "requiresInpatientHospitalization": "Hospital",
        "resultsInPersistentOrSignificantDisability": "Disability",
        "congenitalAnomalyBirthDefect": "Congenital",
        "otherMedicallyImportantCondition": "IME"
    }

    if uploaded_files:
        st.markdown("### ⏳ Parsing Files...")
        progress = st.progress(0)
        total_files = len(uploaded_files)
        parsed_rows = 0

        for idx, uploaded_file in enumerate(uploaded_files, start=1):
            warnings = []  # per-file warnings
            comments = []  # v1.3+: per-file comments (PL messages, lot messages)

            try:
                tree = ET.parse(uploaded_file)
                root = tree.getroot()
            except Exception as e:
                st.error(f"Failed to parse XML file {getattr(uploaded_file, 'name', '(unnamed)')}: {e}")
                progress.progress(idx / total_files)
                continue

            ns = {'hl7': 'urn:hl7-org:v3'}

            # Sender & Transmission
            sender_elem = root.find('.//hl7:id[@root="2.16.840.1.113883.3.989.2.1.3.1"]', ns)
            sender_id = clean_value(sender_elem.attrib.get('extension', '') if sender_elem is not None else '')
            creation_elem = root.find('.//hl7:creationTime', ns)
            transmission_date = clean_value(format_date(creation_elem.attrib.get('value', '') if creation_elem is not None else ''))

            # Reporter qualification
            reporter_elem = root.find('.//hl7:asQualifiedEntity/hl7:code', ns)
            reporter_qualification = clean_value(map_reporter(reporter_elem.attrib.get('code', '') if reporter_elem is not None else ''))

            # Patient demographics
            gender_elem = root.find('.//hl7:administrativeGenderCode', ns)
            gender_mapped = map_gender(gender_elem.attrib.get('code', '') if gender_elem is not None else '')
            gender = clean_value(gender_mapped)

            age_elem = root.find('.//hl7:code[@displayName="age"]/../hl7:value', ns)
            age = ""
            if age_elem is not None:
                age_val = age_elem.attrib.get('value', '')
                raw_unit = age_elem.attrib.get('unit', '')  # 'a' or 'b'
                unit_text = age_unit_map.get(raw_unit, raw_unit)
                age_val = clean_value(age_val)
                unit_text_disp = clean_value(unit_text)
                if age_val:
                    try:
                        n = float(age_val)
                        if unit_text_disp in ("year", "month"):
                            unit_text_disp = unit_text_disp + ("s" if n != 1 else "")
                    except Exception:
                        pass
                    age = f"{age_val}" + (f" {unit_text_disp}" if unit_text_disp else "")

            weight_elem = root.find('.//hl7:code[@displayName="bodyWeight"]/../hl7:value', ns)
            weight_val = clean_value(weight_elem.attrib.get('value', '') if weight_elem is not None else '')
            weight_unit = clean_value(weight_elem.attrib.get('unit', '') if weight_elem is not None else '')
            weight = f"{weight_val}" + (f" {weight_unit}" if weight_val and weight_unit else "") if weight_val else ""

            height_elem = root.find('.//hl7:code[@displayName="height"]/../hl7:value', ns)
            height_val = clean_value(height_elem.attrib.get('value', '') if height_elem is not None else '')
            height_unit = clean_value(height_elem.attrib.get('unit', '') if height_elem is not None else '')
            height = f"{height_val}" + (f" {height_unit}" if height_val and height_unit else "") if height_val else ""

            # Patient initials
            patient_initials = ""
            name_elem = root.find('.//hl7:player1/hl7:name', ns)
            if name_elem is not None:
                if 'nullFlavor' in name_elem.attrib and name_elem.attrib.get('nullFlavor') == 'MSK':
                    patient_initials = "Masked"  # not treated as unknown unless requested
                else:
                    init_parts = []
                    for g in name_elem.findall('hl7:given', ns):
                        if g.text and g.text.strip():
                            init_parts.append(g.text.strip()[0].upper())
                    fam = name_elem.find('hl7:family', ns)
                    if fam is not None and fam.text and fam.text.strip():
                        init_parts.append(fam.text.strip()[0].upper())
                    if init_parts:
                        patient_initials = "".join(init_parts)
                    else:
                        if name_elem.text and name_elem.text.strip():
                            patient_initials = name_elem.text.strip()
            patient_initials = clean_value(patient_initials)

            # Age group
            age_group_map = {
                "0": "Foetus",
                "1": "Neonate",
                "2": "Infant",
                "3": "Child",
                "4": "Adolescent",
                "5": "Adult",
                "6": "Elderly"
            }
            age_group_elem = root.find('.//hl7:code[@displayName="ageGroup"]/../hl7:value', ns)
            age_group = ""
            if age_group_elem is not None:
                code_val = age_group_elem.attrib.get('code', '')
                null_flavor = age_group_elem.attrib.get('nullFlavor', '')
                if code_val in age_group_map:
                    age_group = age_group_map[code_val]
                elif null_flavor in ["MSK", "UNK", "ASKU", "NI"] or code_val in ["MSK", "UNK", "ASKU", "NI"]:
                    age_group = "[Masked/Unknown]"
            # Hide unknowns
            age_group = clean_value(age_group)

            # Patient Detail (skip unknown/empty values)
            patient_parts = []
            if patient_initials:
                patient_parts.append(f"Initials: {patient_initials}")
            if gender:
                patient_parts.append(f"Gender: {gender}")
            if age_group:
                patient_parts.append(f"Age Group: {age_group}")
            if age:
                patient_parts.append(f"Age: {age}")
            if height:
                patient_parts.append(f"Height: {height}")
            if weight:
                patient_parts.append(f"Weight: {weight}")
            patient_detail = ", ".join(patient_parts)
            has_any_patient_detail = any([patient_initials, gender, age_group, age, height, weight])

            # Suspect product IDs via causalityAssessment (code == 1)
            suspect_ids = []
            for causality in root.findall('.//hl7:causalityAssessment', ns):
                val_elem = causality.find('.//hl7:value', ns)
                if val_elem is not None and val_elem.attrib.get('code') == '1':
                    subj_id_elem = causality.find('.//hl7:subject2/hl7:productUseReference/hl7:id', ns)
                    if subj_id_elem is not None:
                        suspect_ids.append(subj_id_elem.attrib.get('root', ''))

            # Product/detail build
            product_details_list = []
            case_has_category2 = False

            # Collect dates for validity checks
            case_drug_dates = []   # tuples (product_key, strength_mg, start_date_obj, stop_date_obj)
            case_event_dates = []  # tuples ("event", evt_start_obj, evt_stop_obj)

            for drug in root.findall('.//hl7:substanceAdministration', ns):
                id_elem = drug.find('.//hl7:id', ns)
                drug_id = id_elem.attrib.get('root', '') if id_elem is not None else ''
                if drug_id in suspect_ids:
                    name_elem_drug = drug.find('.//hl7:kindOfProduct/hl7:name', ns)
                    raw_drug_text = ""
                    if name_elem_drug is not None:
                        if name_elem_drug.text and name_elem_drug.text.strip():
                            raw_drug_text = name_elem_drug.text.strip()
                        else:
                            orig = name_elem_drug.find('hl7:originalText', ns)
                            if orig is not None and orig.text and orig.text.strip():
                                raw_drug_text = orig.text.strip()
                            else:
                                if 'displayName' in name_elem_drug.attrib:
                                    raw_drug_text = name_elem_drug.attrib.get('displayName', '').strip()
                    if not raw_drug_text:
                        alt_name = drug.find('.//hl7:manufacturedProduct/hl7:name', ns)
                        if alt_name is not None and alt_name.text and alt_name.text.strip():
                            raw_drug_text = alt_name.text.strip()

                    matched_company_prod = contains_company_product(raw_drug_text, company_products)
                    if matched_company_prod:
                        # Category 2 flag (for reportability only)
                        if normalize_text(matched_company_prod) in category2_products:
                            case_has_category2 = True

                        # Dose/strength parsing
                        text_elem = drug.find('.//hl7:text', ns)
                        dose_elem = drug.find('.//hl7:doseQuantity', ns)
                        dose_val_raw = dose_elem.attrib.get('value', '') if dose_elem is not None else ''
                        dose_unit_raw = dose_elem.attrib.get('unit', '') if dose_elem is not None else ''
                        dose_val = clean_value(dose_val_raw)
                        dose_unit = clean_value(dose_unit_raw)
                        strength_mg = extract_strength_mg(raw_drug_text, dose_val, dose_unit)

                        # Dates (drug start/stop)
                        start_elem = drug.find('.//hl7:low', ns)
                        stop_elem = drug.find('.//hl7:high', ns)
                        start_date_str = start_elem.attrib.get('value', '') if start_elem is not None else ''
                        stop_date_str = stop_elem.attrib.get('value', '') if stop_elem is not None else ''
                        start_date_disp = clean_value(format_date(start_date_str))
                        stop_date_disp = clean_value(format_date(stop_date_str))
                        start_date_obj = parse_date_obj(start_date_str)
                        stop_date_obj = parse_date_obj(stop_date_str)

                        case_drug_dates.append((matched_company_prod, strength_mg, start_date_obj, stop_date_obj))

                        # Product detail parts (skip unknowns)
                        parts = []
                        display_name = raw_drug_text if raw_drug_text else matched_company_prod.title()
                        display_name = clean_value(display_name)
                        if display_name:
                            parts.append(f"Drug: {display_name}")

                        text_clean = ""
                        if text_elem is not None and text_elem.text:
                            text_clean = clean_value(text_elem.text)
                            if text_clean:
                                parts.append(f"Dosage: {text_clean}")

                        if (dose_val or dose_unit):
                            if dose_val and dose_unit:
                                parts.append(f"Dose: {dose_val} {dose_unit}")
                            elif dose_val:
                                parts.append(f"Dose: {dose_val}")
                            elif dose_unit:
                                parts.append(f"Dose Unit: {dose_unit}")

                        if start_date_disp:
                            parts.append(f"Start Date: {start_date_disp}")
                        if stop_date_disp:
                            parts.append(f"Stop Date: {stop_date_disp}")

                        form_elem = drug.find('.//hl7:formCode/hl7:originalText', ns)
                        form_clean = ""
                        if form_elem is not None and form_elem.text:
                            form_clean = clean_value(form_elem.text)
                            if form_clean:
                                parts.append(f"Formulation: {form_clean}")

                        lot_elem = drug.find('.//hl7:lotNumberText', ns)
                        lot_clean = ""
                        if lot_elem is not None and lot_elem.text:
                            lot_clean = clean_value(lot_elem.text)
                            if lot_clean:
                                parts.append(f"Lot No: {lot_clean}")

                        # --- v1.3: PL detection -> add comments
                        pl_hits = set()
                        for t in [display_name, text_clean, form_clean, lot_clean]:
                            for pl in extract_pl_numbers(t):
                                pl_hits.add(pl)
                        for pl in sorted(pl_hits):
                            if display_name:
                                comments.append(f"plz check product name as {display_name} {pl} given")
                            else:
                                comments.append(f"plz check product name: {pl} given")

                        # --- v1.4: Lot detection -> add comments when lot contains competitor/company names
                        if lot_clean and contains_competitor_name(lot_clean, competitor_names):
                            comments.append(f"Lot number '{lot_clean}' may belong to another company — please verify.")

                        # Only add this drug block if at least one displayable part remains
                        if parts:
                            product_details_list.append(" \n ".join(parts))

            # Event details (collect seriousness and event dates)
            seriousness_criteria = list(seriousness_map.keys())
            event_details_list = []
            event_count = 1
            case_has_serious_event = False

            for reaction in root.findall('.//hl7:observation', ns):
                code_elem = reaction.find('hl7:code', ns)
                if code_elem is not None and code_elem.attrib.get('displayName') == 'reaction':
                    value_elem = reaction.find('hl7:value', ns)
                    llt_code = value_elem.attrib.get('code', '') if value_elem is not None else ''
                    llt_term, pt_term = llt_code, ''
                    if mapping_df is not None and llt_code:
                        try:
                            llt_code_str = str(llt_code).strip()
                            row = mapping_df[mapping_df['LLT Code'] == llt_code_str]
                            if not row.empty:
                                llt_term = str(row['LLT Term'].values[0])
                                pt_term = str(row['PT Term'].values[0])
                            else:
                                warnings.append(f"LLT code {llt_code_str} not found in mapping file")
                        except Exception as e:
                            warnings.append(f"LLT mapping failed for code {llt_code}: {e}")

                    # Seriousness
                    seriousness_flags = []
                    for criterion in seriousness_criteria:
                        criterion_elem = reaction.find(f'.//hl7:code[@displayName="{criterion}"]/../hl7:value', ns)
                        if criterion_elem is not None and criterion_elem.attrib.get('value') == 'true':
                            seriousness_flags.append(seriousness_map.get(criterion, criterion))
                    if not seriousness_flags:
                        seriousness_display = "Non-serious"
                    else:
                        seriousness_display = ", ".join(seriousness_flags)
                        case_has_serious_event = True

                    # Outcome
                    outcome_elem = reaction.find('.//hl7:code[@displayName="outcome"]/../hl7:value', ns)
                    outcome = map_outcome(outcome_elem.attrib.get('code', '') if outcome_elem is not None else '')
                    outcome = clean_value(outcome)

                    # Event dates (effectiveTime low/high if present)
                    evt_low = reaction.find('.//hl7:effectiveTime/hl7:low', ns)
                    evt_high = reaction.find('.//hl7:effectiveTime/hl7:high', ns)
                    evt_low_str = evt_low.attrib.get('value', '') if evt_low is not None else ''
                    evt_high_str = evt_high.attrib.get('value', '') if evt_high is not None else ''
                    evt_low_disp = clean_value(format_date(evt_low_str))    # Display: Start
                    evt_high_disp = clean_value(format_date(evt_high_str))  # Display: End
                    evt_low_obj = parse_date_obj(evt_low_str)               # Comparison: Start
                    evt_high_obj = parse_date_obj(evt_high_str)             # Comparison: End
                    case_event_dates.append(("event", evt_low_obj, evt_high_obj))

                    # Event section details — explicit Start/End labels
                    details_parts = [f"Event {event_count}: {llt_term} ({pt_term})"]
                    seriousness_clean = clean_value(seriousness_display)
                    if seriousness_clean:
                        details_parts.append(f"Seriousness: {seriousness_clean}")
                    if outcome:
                        details_parts.append(f"Outcome: {outcome}")
                    if evt_low_disp:
                        details_parts.append(f"Event Start: {evt_low_disp}")
                    if evt_high_disp:
                        details_parts.append(f"Event End: {evt_high_disp}")

                    if len(details_parts) > 1:
                        event_details_list.append(" (" + "; ".join(details_parts[1:]) + ") " + details_parts[0])
                    else:
                        event_details_list.append(details_parts[0])

                    event_count += 1

            event_details_combined_display = "\n".join(event_details_list)

            # --- Reportability (kept from baseline) ---
            if case_has_serious_event and case_has_category2:
                reportability = "Category 2, serious, reportable case"
            else:
                reportability = "Non-Reportable"

            # --- Validity assessment (single reason only, ordered rules) ---
            validity_reason = None

            # Rule 1: No patient details
            if not has_any_patient_detail:
                validity_reason = "No patient details"

            # Rule 3: Product not Launched (apply before date comparison rule)
            if validity_reason is None:
                for prod, strength_mg, sdt, edt in case_drug_dates:
                    status = get_launch_status(prod)
                    if status in ("yet", "awaited"):
                        validity_reason = "Product not Launched"
                        break

            # Rule 2: Any event/drug dates prior to launch date
            if validity_reason is None:
                launch_dates = []
                for prod, strength_mg, sdt, edt in case_drug_dates:
                    ld = get_launch_date(prod, strength_mg)
                    if ld:
                        launch_dates.append(ld)
                if launch_dates:
                    min_launch_dt = min(launch_dates)

                    # Check event dates
                    for _, evt_start, evt_stop in case_event_dates:
                        if (evt_start and evt_start < min_launch_dt) or (evt_stop and evt_stop < min_launch_dt):
                            validity_reason = "Drug exposure prior to Launch"
                            break

                    # Check drug dates only if no reason yet
                    if validity_reason is None:
                        for _, _, drug_start, drug_stop in case_drug_dates:
                            if (drug_start and drug_start < min_launch_dt) or (drug_stop and drug_stop < min_launch_dt):
                                validity_reason = "Drug exposure prior to Launch"
                                break

            validity_value = f"Non-Valid ({validity_reason})" if validity_reason else "Valid"

            # Narrative (full text, no truncation)
            narrative_elem = root.find('.//hl7:code[@code="PAT_ADV_EVNT"]/../hl7:text', ns)
            narrative_full_raw = narrative_elem.text if narrative_elem is not None else ''
            narrative_full = clean_value(narrative_full_raw)

            # Collect row (add Comment column)
            all_rows_display.append({
                'SL No': idx,
                'Date': current_date,
                'Sender ID': sender_id,
                'Transmission Date': transmission_date,
                'Reporter Qualification': reporter_qualification,
                'Patient Detail': patient_detail,
                'Product Detail': " \n ".join(product_details_list),
                'Event Details': event_details_combined_display,
                'Narrative': narrative_full,
                'Reportability': reportability,
                'Validity': validity_value,
                'Listedness': '',
                'App Assessment': '',
                'Comment': "; ".join(sorted(set(comments))),  # v1.3+: PL & lot messages
                'Parsing Warnings': "; ".join(warnings) if warnings else ""
            })
            parsed_rows += 1
            progress.progress(idx / total_files)

        st.success(f"Parsing complete ✅ — Files processed: {total_files}, Rows created: {parsed_rows}")

# --- Export & Edit tab ---
with tab2:
    st.markdown("### 📋 Parsed Data Table 🧾")
    if all_rows_display:
        df_display = pd.DataFrame(all_rows_display)

        # Optional narrative truncation for table UX
        show_full_narrative = st.checkbox("Show full narrative (may be long)", value=True)
        if not show_full_narrative:
            df_display['Narrative'] = df_display['Narrative'].astype(str).str.slice(0, 1000)

        editable_cols = ['Listedness', 'App Assessment']  # keep Comment read-only
        disabled_cols = [col for col in df_display.columns if col not in editable_cols]

        edited_df = st.data_editor(
            df_display,
            num_rows="dynamic",
            use_container_width=True,
            disabled=disabled_cols
        )

        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            edited_df.to_excel(writer, index=False, sheet_name="Parsed Data")
        st.download_button("⬇️ Download Excel", excel_buffer.getvalue(), "parsed_data.xlsx")
    else:
        st.info("No data available yet. Please upload files in the first tab.")

# Footer
st.markdown("""
**Developed by Jagamohan** _Disclaimer: App is in developmental stage, validate before using the data._
""", unsafe_allow_html=True)



