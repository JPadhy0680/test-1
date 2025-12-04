
import streamlit as st
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime
import io
import re

# Configure page layout
st.set_page_config(page_title="E2B XML Parser", layout="wide")

# Custom CSS for layout optimization (placeholder)
st.markdown(""" """, unsafe_allow_html=True)

# ✅ Application Name
st.title("📊🧠 E2B_R3 XML Parser Application 🛠️ 🚀")

# ✅ Password Protection
password = st.text_input("Enter Password to Access App:", type="password", help="Enter the password to unlock the application.")
if password != "7064242966":
    st.warning("Please enter the correct password to proceed.")
    st.stop()

# Collapsible Instructions
with st.expander("📖 Instructions"):
    st.markdown("""
- Upload **multiple E2B XML files** and **LLT-PT mapping Excel file**.
- Combined data will be displayed in the Export & Edit tab.
- You can edit Listedness, Validity, and App Assessment directly in the table.
- Download options for CSV, Excel, HTML (openable as PDF), and Summary Statistics are available side by side.
""")

# Tabs for navigation
tab1, tab2 = st.tabs(["Upload & Parse", "Export & Edit"])

all_rows_display = []
current_date = datetime.now().strftime("%d-%b-%Y")

with tab1:
    st.markdown("### 🔍 Upload Files 🗂️")

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

    # Prefer explicit engine for reliability
    mapping_df = pd.read_excel(mapping_file, engine="openpyxl") if mapping_file else None

    # -------------------------
    # Helper Functions
    # -------------------------
    def format_date(date_str):
        if not date_str or len(date_str) < 8:
            return ""
        try:
            return datetime.strptime(date_str[:8], "%Y%m%d").strftime("%d-%b-%Y")
        except ValueError:
            return ""

    def map_reporter(code):
        mapping = {
            "1": "Physician",
            "2": "Pharmacist",
            "3": "Other health professional",
            "4": "Lawyer",
            "5": "Consumer or other non-health professional"
        }
        return mapping.get(code, "Unknown")

    def map_gender(code):
        return {"1": "Male", "2": "Female"}.get(code, "Unknown")

    def map_outcome(code):
        mapping = {
            "1": "Recovered/Resolved",
            "2": "Recovering/Resolving",
            "3": "Not recovered/Ongoing",
            "4": "Recovered with sequelae",
            "5": "Fatal",
            "0": "Unknown"
        }
        return mapping.get(code, "Unknown")

    # Age unit mapping: a=year, b=month
    age_unit_map = {
        "a": "year",
        "b": "month"
    }

    # Inclusive product detection helpers
    def normalize_text(s: str) -> str:
        """Lowercase and remove non-alphanumeric except spaces; collapse spaces."""
        s = (s or "").lower()
        s = re.sub(r'[^a-z0-9\s]', ' ', s)  # keep letters, digits, spaces
        s = re.sub(r'\s+', ' ', s).strip()
        return s

    def contains_company_product(text: str, company_products: list) -> str:
        """
        Returns the matched company product (canonical molecule/brand name) if any is present
        in the given text; otherwise returns ''.
        Uses word-boundary regex over normalized text.
        """
        norm = normalize_text(text)
        for prod in company_products:
            pnorm = normalize_text(prod)
            if not pnorm:
                continue
            pattern = r'\b' + re.escape(pnorm) + r'\b'
            if re.search(pattern, norm):
                return prod  # return canonical prod key
        return ""

    # Company products (filter suspects) — includes Category 2 + others
    company_products = [
        # Category 1 (rest — keep your original portfolio)
        "abiraterone", "apixaban", "apremilast", "bexarotene",
        # "clobazam", "clonazepam" -> Category 2 (listed separately below)
        "dabigatran", "dapagliflozin",
        "dimethyl fumarate", "icatibant", "linagliptin",
        "pirfenidone", "ranolazine", "rivaroxaban", "saxagliptin",
        "sitagliptin", "solifenacin", "tamsulosin", "tapentadol",
        "ticagrelor", "nintedanib",
        # Additions requested previously (some are Category 2)
        "famotidine", "cyclogest", "progesterone", "luteum", "amelgen",
        # Newly added requested items
        "cyanocobalamin", "itraconazole",
        # Also ensure "clobazam" and "clonazepam" are in products list for matching
        "clobazam", "clonazepam"
    ]

    # Define Category 2 products explicitly
    category2_products = {
        "clobazam", "clonazepam", "cyanocobalamin",
        "famotidine", "itraconazole",
        "tamsulosin", "solifenacin",
        "tapentadol", "cyclogest",
        "progesterone", "luteum", "amelgen"
    }

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

        for idx, uploaded_file in enumerate(uploaded_files, start=1):
            tree = ET.parse(uploaded_file)
            root = tree.getroot()
            ns = {'hl7': 'urn:hl7-org:v3'}

            # Sender ID
            sender_elem = root.find('.//hl7:id[@root="2.16.840.1.113883.3.989.2.1.3.1"]', ns)
            sender_id = sender_elem.attrib.get('extension', '') if sender_elem is not None else ''

            # Transmission Date
            creation_elem = root.find('.//hl7:creationTime', ns)
            transmission_date = format_date(creation_elem.attrib.get('value', '') if creation_elem is not None else '')

            # Reporter Qualification
            reporter_elem = root.find('.//hl7:asQualifiedEntity/hl7:code', ns)
            reporter_qualification = map_reporter(reporter_elem.attrib.get('code', '') if reporter_elem is not None else '')

            # Gender
            gender_elem = root.find('.//hl7:administrativeGenderCode', ns)
            gender = map_gender(gender_elem.attrib.get('code', '') if gender_elem is not None else '')

            # Age (value + unit mapping a/b)
            age_elem = root.find('.//hl7:code[@displayName="age"]/../hl7:value', ns)
            age = ""
            if age_elem is not None:
                age_val = age_elem.attrib.get('value', '')
                raw_unit = age_elem.attrib.get('unit', '')  # 'a' or 'b'
                unit_text = age_unit_map.get(raw_unit, raw_unit)
                if age_val:
                    # pluralize when needed
                    try:
                        n = float(age_val)
                        if unit_text in ("year", "month"):
                            unit_text_disp = unit_text + ("s" if n != 1 else "")
                        else:
                            unit_text_disp = unit_text
                    except Exception:
                        unit_text_disp = unit_text
                    age = f"{age_val} {unit_text_disp}".strip()

            # Weight
            weight_elem = root.find('.//hl7:code[@displayName="bodyWeight"]/../hl7:value', ns)
            weight = f"{weight_elem.attrib.get('value', '')} {weight_elem.attrib.get('unit', '')}" if weight_elem is not None else ''

            # Height
            height_elem = root.find('.//hl7:code[@displayName="height"]/../hl7:value', ns)
            height = f"{height_elem.attrib.get('value', '')} {height_elem.attrib.get('unit', '')}" if height_elem is not None else ''

            # --- Patient initials extraction ---
            patient_initials = ""
            name_elem = root.find('.//hl7:player1/hl7:name', ns)
            if name_elem is not None:
                if 'nullFlavor' in name_elem.attrib and name_elem.attrib.get('nullFlavor') == 'MSK':
                    patient_initials = "[Masked]"
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

            # --- Age Group extraction ---
            age_group_map = {
                "0": "Foetus",
                "1": "Neonate (Preterm and Term newborns)",
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

            # Patient Detail assembly (Initials first)
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

            # Identify suspect products through causalityAssessment (code==1)
            suspect_ids = []
            for causality in root.findall('.//hl7:causalityAssessment', ns):
                val_elem = causality.find('.//hl7:value', ns)
                if val_elem is not None and val_elem.attrib.get('code') == '1':
                    subj_id_elem = causality.find('.//hl7:subject2/hl7:productUseReference/hl7:id', ns)
                    if subj_id_elem is not None:
                        suspect_ids.append(subj_id_elem.attrib.get('root', ''))

            # Product details (only company products, suspect only)
            product_details_list = []
            case_has_category2 = False  # flag for reportability
            for drug in root.findall('.//hl7:substanceAdministration', ns):
                id_elem = drug.find('.//hl7:id', ns)
                drug_id = id_elem.attrib.get('root', '') if id_elem is not None else ''
                if drug_id in suspect_ids:
                    name_elem_drug = drug.find('.//hl7:kindOfProduct/hl7:name', ns)

                    # Prefer textual content of <name>; try fallbacks
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

                    # Further fallback to other common locations
                    if not raw_drug_text:
                        alt_name = drug.find('.//hl7:manufacturedProduct/hl7:name', ns)
                        if alt_name is not None and alt_name.text and alt_name.text.strip():
                            raw_drug_text = alt_name.text.strip()

                    # Decide whether this is one of your company products by inclusive matching
                    matched_company_prod = contains_company_product(raw_drug_text, company_products)

                    if matched_company_prod:
                        # Track Category 2 presence for reportability
                        if normalize_text(matched_company_prod) in category2_products:
                            case_has_category2 = True

                        parts = []
                        display_name = raw_drug_text if raw_drug_text else matched_company_prod.title()
                        parts.append(f"Drug: {display_name}")

                        text_elem = drug.find('.//hl7:text', ns)
                        if text_elem is not None and text_elem.text:
                            parts.append(f"Dosage: {text_elem.text}")

                        dose_elem = drug.find('.//hl7:doseQuantity', ns)
                        if dose_elem is not None:
                            dose_val = dose_elem.attrib.get('value', '')
                            dose_unit = dose_elem.attrib.get('unit', '')
                            if dose_val or dose_unit:
                                parts.append(f"Dose: {dose_val} {dose_unit}")

                        form_elem = drug.find('.//hl7:formCode/hl7:originalText', ns)
                        if form_elem is not None and form_elem.text:
                            parts.append(f"Formulation: {form_elem.text}")

                        lot_elem = drug.find('.//hl7:lotNumberText', ns)
                        if lot_elem is not None and lot_elem.text:
                            parts.append(f"Lot No: {lot_elem.text}")

                        start_elem = drug.find('.//hl7:low', ns)
                        start_date = format_date(start_elem.attrib.get('value', '') if start_elem is not None else '')
                        if start_date:
                            parts.append(f"Start Date: {start_date}")

                        stop_elem = drug.find('.//hl7:high', ns)
                        stop_date = format_date(stop_elem.attrib.get('value', '') if stop_elem is not None else '')
                        if stop_date:
                            parts.append(f"Stop Date: {stop_date}")

                        if parts:
                            product_details_list.append(" \n ".join(parts))

            product_details_combined = " \n ".join(product_details_list)

            # Event details
            seriousness_criteria = list(seriousness_map.keys())
            event_details_list = []
            event_count = 1
            case_has_serious_event = False  # flag for reportability

            for reaction in root.findall('.//hl7:observation', ns):
                code_elem = reaction.find('hl7:code', ns)
                if code_elem is not None and code_elem.attrib.get('displayName') == 'reaction':
                    value_elem = reaction.find('hl7:value', ns)
                    llt_code = value_elem.attrib.get('code', '') if value_elem is not None else ''
                    llt_term, pt_term = llt_code, ''
                    if mapping_df is not None and llt_code:
                        # Guard against non-integer LLT codes
                        try:
                            row = mapping_df[mapping_df['LLT Code'] == int(llt_code)]
                            if not row.empty:
                                llt_term = row['LLT Term'].values[0]
                                pt_term = row['PT Term'].values[0]
                        except Exception:
                            pass

                    # Collect seriousness flags
                    seriousness_flags = []
                    for criterion in seriousness_criteria:
                        criterion_elem = reaction.find(f'.//hl7:code[@displayName="{criterion}"]/../hl7:value', ns)
                        if criterion_elem is not None and criterion_elem.attrib.get('value') == 'true':
                            seriousness_flags.append(seriousness_map.get(criterion, criterion))

                    # ✅ Default to "Non-serious" if no criteria present
                    if not seriousness_flags:
                        seriousness_display = "Non-serious"
                    else:
                        seriousness_display = ", ".join(seriousness_flags)
                        case_has_serious_event = True  # mark case as having serious event

                    # Outcome
                    outcome_elem = reaction.find('.//hl7:code[@displayName="outcome"]/../hl7:value', ns)
                    outcome = map_outcome(outcome_elem.attrib.get('code', '') if outcome_elem is not None else '')

                    details = (
                        f"Event {event_count}: {llt_term} ({pt_term}) "
                        f"(Seriousness: {seriousness_display}; Outcome: {outcome})"
                    )
                    event_details_list.append(details)
                    event_count += 1

            event_details_combined_display = "\n".join(event_details_list)

            # --- NEW: Reportability calculation ---
            if case_has_serious_event and case_has_category2:
                reportability = "Category 2, serious, reportable case"
            else:
                reportability = "Non-Reportable"

            # Narrative
            narrative_elem = root.find('.//hl7:code[@code="PAT_ADV_EVNT"]/../hl7:text', ns)
            narrative_full = narrative_elem.text if narrative_elem is not None else ''
            narrative_display = " ".join(narrative_full.split()[:10]) + "..." if len(narrative_full.split()) > 10 else narrative_full

            # Collect row (include Reportability)
            all_rows_display.append({
                'SL No': idx,
                'Date': current_date,
                'Sender ID': sender_id,
                'Transmission Date': transmission_date,
                'Reporter Qualification': reporter_qualification,
                'Patient Detail': patient_detail,
                'Product Detail': product_details_combined,
                'Event Details': event_details_combined_display,
                'Narrative': narrative_display,
                'Reportability': reportability,          # ✅ New column
                'Listedness': '',
                'Validity': '',
                'App Assessment': ''
            })

            progress.progress(idx / len(uploaded_files))

with tab2:
    st.markdown("### 📋 Parsed Data Table 🧾")
    if all_rows_display:
        df_display = pd.DataFrame(all_rows_display)

        # Keep only specific columns editable; Reportability is computed -> disabled
        editable_cols = ['Listedness', 'Validity', 'App Assessment']
        disabled_cols = [col for col in df_display.columns if col not in editable_cols]

        edited_df = st.data_editor(df_display, num_rows="dynamic", use_container_width=True, disabled=disabled_cols)

        # Summary Statistics
        st.markdown("### 📈 Summary Statistics 🌐")
        gender_counts = {}
        try:
            gender_series = edited_df['Patient Detail'].str.extract(r'Gender:\s*(Male|Female|Unknown)')[0]
            gender_counts = gender_series.value_counts().to_dict()
        except Exception:
            gender_counts = {}

        summary_data = {
            "Total Cases": len(edited_df),
            "Reporter Qualification Counts": edited_df['Reporter Qualification'].value_counts().to_dict(),
            "Gender Counts": gender_counts
            # (Optionally add Reportability counts here)
        }

        summary_df = pd.DataFrame(list(summary_data.items()), columns=["Metric", "Value"])
        st.table(summary_df)

        # Export main table
        csv = edited_df.to_csv(index=False)
        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            edited_df.to_excel(writer, index=False)

        # HTML export for main table
        html_buffer = io.BytesIO()
        html_buffer.write(edited_df.to_html(index=False).encode('utf-8'))
        html_buffer.seek(0)

        # Export summary
        summary_csv = summary_df.to_csv(index=False)
        summary_html_buffer = io.BytesIO()
        summary_html_buffer.write(summary_df.to_html(index=False).encode('utf-8'))
        summary_html_buffer.seek(0)

        # Download buttons side by side
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.download_button("⬇️ CSV", csv, "parsed_data.csv")
        with col2:
            st.download_button("⬇️ Excel", excel_buffer.getvalue(), "parsed_data.xlsx")
        with col3:
            st.download_button("⬇️ HTML (PDF)", html_buffer.getvalue(), "parsed_data.html")
        with col4:
            st.download_button("⬇️ Summary CSV", summary_csv, "summary.csv")
        with col5:
            st.download_button("⬇️ Summary HTML", summary_html_buffer.getvalue(), "summary.html")
    else:
        st.info("No data available yet. Please upload files in the first tab.")

# Footer
st.markdown("""
**Developed by Jagamohan** _Disclaimer: App is in developmental stage, validate before using the data._
""", unsafe_allow_html=True)



