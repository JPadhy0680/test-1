
import streamlit as st
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import io
import re

# -----------------------------------------------------
# App configuration
# -----------------------------------------------------
st.set_page_config(page_title="E2B_R3 XML Parser Application", layout="wide")
st.markdown(""" """, unsafe_allow_html=True)
st.title("📊🧠 E2B_R3 XML Parser Application 🛠️ 🚀")

# -----------------------------------------------------
# Password with 24h persistence (uses st.secrets if present)
# -----------------------------------------------------
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

# -----------------------------------------------------
# Instructions
# -----------------------------------------------------
with st.expander("📖 Instructions"):
    st.markdown("""
- Upload **multiple E2B XML files** and **LLT-PT mapping Excel file**.
- Parsed data appears in the **Export & Edit** tab.
- Columns **Listedness** and **App Assessment** remain editable; other computed columns are locked.
- **Validity** is computed automatically (with reason).
- Only **one Excel** download button is provided (no CSV/HTML/Summary).
""")

# -----------------------------------------------------
# Tabs
# -----------------------------------------------------
tab1, tab2 = st.tabs(["Upload & Parse", "Export & Edit"])
all_rows_display = []
current_date = datetime.now().strftime("%d-%b-%Y")

# -----------------------------------------------------
# Helper mappings & functions
# -----------------------------------------------------
def format_date(date_str: str) -> str:
    """Return DD-Mon-YYYY from HL7 date string (YYYYMMDD...) or empty if invalid."""
    if not date_str or len(date_str) < 8:
        return ""
    try:
        return datetime.strptime(date_str[:8], "%Y%m%d").strftime("%d-%b-%Y")
    except Exception:
        return ""

def parse_date_obj(date_str: str):
    """Parse HL7 date string (YYYYMMDD...) to datetime.date; return None if invalid."""
    if not date_str or len(date_str) < 8:
        return None
    try:
        return datetime.strptime(date_str[:8], "%Y%m%d").date()
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
    (\d{1,3}(?:,\d{3})*|\d+(?:\.\d{1,3})?)   # numeric value, supports thousands and decimals
    \s*
    mg\b                                     # mg unit, word boundary
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

# -----------------------------------------------------
# Product portfolio & launch info
# -----------------------------------------------------
# Company portfolio (for matching)
company_products = [
    # Category 1 + 2 combined (for detection)
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

# Category 2 set (as provided)
category2_products = {
    "clobazam", "clonazepam", "cyanocobalamin",
    "famotidine", "itraconazole",
    "tamsulosin", "solifenacin",
    "tapentadol", "cyclogest",
    "progesterone", "luteum", "amelgen"
}

# Launch info mapping
def parse_dd_mmm_yy(s):
    return datetime.strptime(s, "%d-%b-%y").date()

launch_info = {
    "abiraterone": {"status": "launched", "date": parse_dd_mmm_yy("08-Sep-22")},
    "apixaban": {"status": "launched", "date": parse_dd_mmm_yy("26-Feb-25")},
    "apremilast": {"status": "yet", "date": None},
    "bexarotene": {"status": "launched", "date": parse_dd_mmm_yy("19-Jan-23")},
    "clobazam": {"status": "launched", "date": parse_dd_mmm_yy("26-Sep-24")},
    "clonazepam": {"status": "launched", "date": parse_dd_mmm_yy("20-Jan-25")},
    "cyanocobalamin": {"status": "awaited", "date": None},
    "dabigatran": {"status": "yet", "date": None},
    "dapagliflozin": {
        "status": "launched_by_strength",
        "strengths": {10.0: parse_dd_mmm_yy("26-Aug-25"), 5.0: parse_dd_mmm_yy("10-Sep-25")}
    },
    "dimethyl fumarate": {"status": "launched", "date": parse_dd_mmm_yy("05-Feb-24")},
    "famotidine": {"status": "launched", "date": parse_dd_mmm_yy("21-Feb-25")},
    "fesoterodine": {"status": "yet", "date": None},
    "icatibant": {"status": "launched", "date": parse_dd_mmm_yy("28-Jul-22")},
    "itraconazole": {"status": "awaited", "date": None, "strength_specific": {100.0: "awaited"}},
    "linagliptin": {"status": "yet", "date": None},
    "linagliptin + metformin": {"status": "awaited", "date": None},
    "nintedanib": {"status": "awaited", "date": None},
    "pirfenidone": {"status": "launched", "date": parse_dd_mmm_yy("29-Jun-22")},
    "raltegravir": {"status": "awaited", "date": None},
    "ranolazine": {"status": "launched", "date": parse_dd_mmm_yy("20-Jul-23")},
    "rivaroxaban": {
        "status": "launched_by_strength",
        "strengths": {
            2.5: parse_dd_mmm_yy("02-Apr-24"),
            10.0: parse_dd_mmm_yy("23-May-24"),
            15.0: parse_dd_mmm_yy("23-May-24"),
            20.0: parse_dd_mmm_yy("23-May-24"),
        }
    },
    "saxagliptin": {"status": "yet", "date": None},
    "sitagliptin": {"status": "yet", "date": None},
    "tamsulosin + solifenacin": {"status": "launched", "date": parse_dd_mmm_yy("08-May-23")},
    # Map singles to combo launch date for safety
    "tamsulosin": {"status": "launched", "date": parse_dd_mmm_yy("08-May-23")},
    "solifenacin": {"status": "launched", "date": parse_dd_mmm_yy("08-May-23")},
    "tapentadol": {"status": "launched", "date": parse_dd_mmm_yy("01-Feb-24")},
    "ticagrelor": {"status": "yet", "date": None},
    # Brands of progesterone (treat as launched without specific dates)
    "cyclogest": {"status": "launched", "date": None},
    "progesterone": {"status": "launched", "date": None},
    "luteum": {"status": "launched", "date": None},
    "amelgen": {"status": "launched", "date": None},
}

def resolve_launch(product_name: str, strength_mg):
    """
    Return (is_launched: bool, launch_date: date or None, non_launch_reason: str or None)
    Reason text for non-launched: "Product not Launched"
    Safer rule for strength-gated products: require explicit strength match; otherwise non-launched.
    """
    key = normalize_text(product_name)
    info = launch_info.get(key)
    if not info:
        # If unknown, assume launched (no restriction)
        return True, None, None

    status = info.get("status")
    if status == "launched":
        return True, info.get("date"), None

    if status in ("yet", "awaited"):
        return False, None, "Product not Launched"

    if status == "launched_by_strength":
        strengths = info.get("strengths", {})
        # must match explicitly
        if strength_mg is not None and strength_mg in strengths:
            return True, strengths[strength_mg], None
        return False, None, "Product not Launched"

    # Strength-specific awaited for itraconazole 100 mg
    if key == "itraconazole" and strength_mg is not None:
        spec = info.get("strength_specific", {})
        if spec.get(strength_mg) == "awaited":
            return False, None, "Product not Launched"

    # Default: launched (generic)
    return True, info.get("date"), None

# -----------------------------------------------------
# Upload & Parse tab
# -----------------------------------------------------
with tab1:
    st.markdown("### 🔎 Upload Files 🗂️")
    if st.button("Clear Inputs", help="Click to clear all uploaded files and reset the app."):
        st.session_state.clear()
        st.experimental_rerun()

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

    mapping_df = None
    if mapping_file:
        mapping_df = pd.read_excel(mapping_file, engine="openpyxl")
        # normalize LLT Code to string for robust matching
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
            sender_id = sender_elem.attrib.get('extension', '') if sender_elem is not None else ''
            creation_elem = root.find('.//hl7:creationTime', ns)
            transmission_date = format_date(creation_elem.attrib.get('value', '') if creation_elem is not None else '')

            # Reporter qualification
            reporter_elem = root.find('.//hl7:asQualifiedEntity/hl7:code', ns)
            reporter_qualification = map_reporter(reporter_elem.attrib.get('code', '') if reporter_elem is not None else '')

            # Patient demographics
            gender_elem = root.find('.//hl7:administrativeGenderCode', ns)
            gender = map_gender(gender_elem.attrib.get('code', '') if gender_elem is not None else '')

            age_elem = root.find('.//hl7:code[@displayName="age"]/../hl7:value', ns)
            age = ""
            if age_elem is not None:
                age_val = age_elem.attrib.get('value', '')
                raw_unit = age_elem.attrib.get('unit', '')  # 'a' or 'b'
                unit_text = age_unit_map.get(raw_unit, raw_unit)
                if age_val:
                    try:
                        n = float(age_val)
                        if unit_text in ("year", "month"):
                            unit_text_disp = unit_text + ("s" if n != 1 else "")
                        else:
                            unit_text_disp = unit_text
                    except Exception:
                        unit_text_disp = unit_text
                    age = f"{age_val} {unit_text_disp}".strip()

            weight_elem = root.find('.//hl7:code[@displayName="bodyWeight"]/../hl7:value', ns)
            weight = f"{weight_elem.attrib.get('value', '')} {weight_elem.attrib.get('unit', '')}" if weight_elem is not None else ''
            height_elem = root.find('.//hl7:code[@displayName="height"]/../hl7:value', ns)
            height = f"{height_elem.attrib.get('value', '')} {height_elem.attrib.get('unit', '')}" if height_elem is not None else ''

            # Patient initials
            patient_initials = ""
            name_elem = root.find('.//hl7:player1/hl7:name', ns)
            if name_elem is not None:
                if 'nullFlavor' in name_elem.attrib and name_elem.attrib.get('nullFlavor') == 'MSK':
                    patient_initials = "Masked"
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

            # Patient Detail
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

            # Suspect product IDs via causalityAssessment (code == 1)
            suspect_ids = []
            for causality in root.findall('.//hl7:causalityAssessment', ns):
                val_elem = causality.find('.//hl7:value', ns)
                if val_elem is not None and val_elem.attrib.get('code') == '1':
                    subj_id_elem = causality.find('.//hl7:subject2/hl7:productUseReference/hl7:id', ns)
                    if subj_id_elem is not None:
                        suspect_ids.append(subj_id_elem.attrib.get('root', ''))

            # Product/detail build and launch/validity checks
            product_details_list = []
            case_has_category2 = False

            # For validity
            case_non_valid_reasons = []
            case_valid = True

            # Collect all relevant dates to compare with launch
            case_drug_dates = []   # tuples (product_key, start_date, stop_date)
            case_event_dates = []  # tuples ("event", event_start, event_stop)

            for drug in root.findall('.//hl7:substanceAdministration', ns):
                id_elem = drug.find('.//hl7:id', ns)
                drug_id = id_elem.attrib.get('root', '') if id_elem is not None else ''
                if drug_id in suspect_ids:
                    name_elem_drug = drug.find('.//hl7:kindOfProduct/hl7:name', ns)
                    # Collect a friendly display name
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
                        # Category 2 flag
                        if normalize_text(matched_company_prod) in category2_products:
                            case_has_category2 = True

                        # Dose/strength parsing
                        text_elem = drug.find('.//hl7:text', ns)
                        dose_elem = drug.find('.//hl7:doseQuantity', ns)
                        dose_val = dose_elem.attrib.get('value', '') if dose_elem is not None else ''
                        dose_unit = dose_elem.attrib.get('unit', '') if dose_elem is not None else ''
                        strength_mg = extract_strength_mg(raw_drug_text, dose_val, dose_unit)

                        # Dates (drug start/stop)
                        start_elem = drug.find('.//hl7:low', ns)
                        stop_elem = drug.find('.//hl7:high', ns)
                        start_date_str = start_elem.attrib.get('value', '') if start_elem is not None else ''
                        stop_date_str = stop_elem.attrib.get('value', '') if stop_elem is not None else ''
                        start_date_disp = format_date(start_date_str)
                        stop_date_disp = format_date(stop_date_str)
                        start_date_obj = parse_date_obj(start_date_str)
                        stop_date_obj = parse_date_obj(stop_date_str)
                        case_drug_dates.append((matched_company_prod, start_date_obj, stop_date_obj))

                        # Launch resolution & validity checks for each drug
                        launched, launch_date, reason = resolve_launch(matched_company_prod, strength_mg)
                        if not launched:
                            case_valid = False
                            if reason:
                                case_non_valid_reasons.append(reason)

                        # If launched with known date, compare drug dates
                        if launch_date:
                            if start_date_obj and start_date_obj < launch_date:
                                case_valid = False
                                case_non_valid_reasons.append(
                                    f"{matched_company_prod} start date ({start_date_disp}) before launch date ({launch_date.strftime('%d-%b-%Y')})"
                                )
                            if stop_date_obj and stop_date_obj < launch_date:
                                case_valid = False
                                case_non_valid_reasons.append(
                                    f"{matched_company_prod} stop date ({stop_date_disp}) before launch date ({launch_date.strftime('%d-%b-%Y')})"
                                )

                        # Product detail parts
                        parts = []
                        display_name = raw_drug_text if raw_drug_text else matched_company_prod.title()
                        parts.append(f"Drug: {display_name}")
                        if text_elem is not None and text_elem.text:
                            parts.append(f"Dosage: {text_elem.text}")
                        if dose_elem is not None and (dose_val or dose_unit):
                            parts.append(f"Dose: {dose_val} {dose_unit}")
                        if start_date_disp:
                            parts.append(f"Start Date: {start_date_disp}")
                        if stop_date_disp:
                            parts.append(f"Stop Date: {stop_date_disp}")
                        form_elem = drug.find('.//hl7:formCode/hl7:originalText', ns)
                        if form_elem is not None and form_elem.text:
                            parts.append(f"Formulation: {form_elem.text}")
                        lot_elem = drug.find('.//hl7:lotNumberText', ns)
                        if lot_elem is not None and lot_elem.text:
                            parts.append(f"Lot No: {lot_elem.text}")
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

                    # Event dates (effectiveTime low/high if present)
                    evt_low = reaction.find('.//hl7:effectiveTime/hl7:low', ns)
                    evt_high = reaction.find('.//hl7:effectiveTime/hl7:high', ns)
                    evt_low_str = evt_low.attrib.get('value', '') if evt_low is not None else ''
                    evt_high_str = evt_high.attrib.get('value', '') if evt_high is not None else ''
                    evt_low_disp = format_date(evt_low_str)
                    evt_high_disp = format_date(evt_high_str)
                    evt_low_obj = parse_date_obj(evt_low_str)
                    evt_high_obj = parse_date_obj(evt_high_str)
                    case_event_dates.append(("event", evt_low_obj, evt_high_obj))

                    details_parts = [
                        f"Event {event_count}: {llt_term} ({pt_term})",
                        f"Seriousness: {seriousness_display}",
                        f"Outcome: {outcome}"
                    ]
                    if evt_low_disp:
                        details_parts.append(f"Event Start: {evt_low_disp}")
                    if evt_high_disp:
                        details_parts.append(f"Event End: {evt_high_disp}")
                    event_details_list.append(" (" + "; ".join(details_parts[1:]) + ") " + details_parts[0])
                    event_count += 1

            event_details_combined_display = "\n".join(event_details_list)

            # --- Reportability ---
            if case_has_serious_event and case_has_category2:
                reportability = "Category 2, serious, reportable case"
            else:
                reportability = "Non-Reportable"

            # --- Validity assessment ---
            # Rule: Non-valid if
            # - no patient details
            # - any drug start/stop OR event start/stop date < product launch date
            # - product not launched (reason: "Product not Launched")
            if not patient_detail:
                case_valid = False
                case_non_valid_reasons.append("No patient details present")

            # Compare event dates against all known launch dates of matched products
            # We use minimum launch date among matched products (safest) if multiple.
            matched_launch_dates = []
            for prod, sdt, edt in case_drug_dates:
                launched, launch_dt, _ = resolve_launch(prod, None)  # strength already handled earlier per-drug
                if launch_dt:
                    matched_launch_dates.append(launch_dt)

            if matched_launch_dates:
                min_launch_dt = min(matched_launch_dates)
                for _, evt_start, evt_stop in case_event_dates:
                    if evt_start and evt_start < min_launch_dt:
                        case_valid = False
                        case_non_valid_reasons.append(
                            f"Event start date ({evt_start.strftime('%d-%b-%Y')}) before launch date ({min_launch_dt.strftime('%d-%b-%Y')})"
                        )
                    if evt_stop and evt_stop < min_launch_dt:
                        case_valid = False
                        case_non_valid_reasons.append(
                            f"Event end date ({evt_stop.strftime('%d-%b-%Y')}) before launch date ({min_launch_dt.strftime('%d-%b-%Y')})"
                        )

            validity_value = "Valid" if case_valid else "Non-Valid"
            non_valid_reason = "; ".join(sorted(set(case_non_valid_reasons))) if case_non_valid_reasons else ""

            # Narrative (full text, no truncation)
            narrative_elem = root.find('.//hl7:code[@code="PAT_ADV_EVNT"]/../hl7:text', ns)
            narrative_full = narrative_elem.text if narrative_elem is not None else ''

            # Collect row
            all_rows_display.append({
                'SL No': idx,
                'Date': current_date,
                'Sender ID': sender_id,
                'Transmission Date': transmission_date,
                'Reporter Qualification': reporter_qualification,
                'Patient Detail': patient_detail,
                'Product Detail': " \n ".join(product_details_list),
                'Event Details': event_details_combined_display,
                'Narrative': narrative_full,  # ✅ full narrative
                'Reportability': reportability,  # computed
                'Validity': validity_value,      # computed
                'Non-Valid Reason': non_valid_reason,  # computed
                'Listedness': '',               # editable
                'App Assessment': '',           # editable
                'Parsing Warnings': "; ".join(warnings) if warnings else ""
            })
            parsed_rows += 1
            progress.progress(idx / total_files)

        st.success(f"Parsing complete ✅ — Files processed: {total_files}, Rows created: {parsed_rows}")

# -----------------------------------------------------
# Export & Edit tab
# -----------------------------------------------------
with tab2:
    st.markdown("### 📋 Parsed Data Table 🧾")
    if all_rows_display:
        df_display = pd.DataFrame(all_rows_display)

        # Optional narrative truncation for table UX
        show_full_narrative = st.checkbox("Show full narrative (may be long)", value=True)
        if not show_full_narrative:
            df_display['Narrative'] = df_display['Narrative'].astype(str).str.slice(0, 1000)

        # Only these columns editable; computed columns locked
        editable_cols = ['Listedness', 'App Assessment']
        disabled_cols = [col for col in df_display.columns if col not in editable_cols]

        edited_df = st.data_editor(
            df_display,
            num_rows="dynamic",
            use_container_width=True,
            disabled=disabled_cols
        )

        # Single Excel download
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





