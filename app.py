
import streamlit as st
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime
import io

# Helper Functions
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

# Company product list
company_products = [
    "abiraterone", "apixaban", "apremilast", "bexarotene", "clobazam", "clonazepam",
    "dabigatran", "dapagliflozin", "dimethyl fumarate", "famotidine", "fesoterodine",
    "icatibant", "linagliptin", "pirfenidone", "ranolazine", "rivaroxaban", "saxagliptin",
    "sitagliptin", "solifenacin + tamsulosin", "tapentadol", "ticagrelor", "nintedanib"
]

# Seriousness mapping
seriousness_map = {
    "resultsInDeath": "Death",
    "isLifeThreatening": "LT",
    "requiresInpatientHospitalization": "Hospital",
    "resultsInPersistentOrSignificantDisability": "Disability",
    "congenitalAnomalyBirthDefect": "Congenital",
    "otherMedicallyImportantCondition": "IME"
}

# UI
st.title("👉 E2B XML Parser with Company Suspect Products ✅")
st.markdown("""
### Instructions:
1. Upload the E2B XML file.
2. Upload the LLT-PT mapping Excel file.
3. The output table will include:
   - Patient details (only non-empty fields)
   - Suspect company products with dosage and other details
   - Event details with seriousness mapped to short labels
4. Download options for CSV and Excel are provided below.
""")

uploaded_file = st.file_uploader("Upload E2B XML file", type=["xml"])
mapping_file = st.file_uploader("Upload LLT-PT Mapping Excel file", type=["xlsx"])

if uploaded_file:
    tree = ET.parse(uploaded_file)
    root = tree.getroot()
    ns = {'hl7': 'urn:hl7-org:v3'}
    current_date = datetime.now().strftime("%d-%b-%Y")

    # Extract basic info
    sender_elem = root.find('.//hl7:id[@root="2.16.840.1.113883.3.989.2.1.3.1"]', ns)
    sender_id = sender_elem.attrib.get('extension', '') if sender_elem is not None else ''

    creation_elem = root.find('.//hl7:creationTime', ns)
    transmission_date = format_date(creation_elem.attrib.get('value', '') if creation_elem is not None else '')

    reporter_elem = root.find('.//hl7:asQualifiedEntity/hl7:code', ns)
    reporter_qualification = map_reporter(reporter_elem.attrib.get('code', '') if reporter_elem is not None else '')

    gender_elem = root.find('.//hl7:administrativeGenderCode', ns)
    gender = map_gender(gender_elem.attrib.get('code', '') if gender_elem is not None else '')

    age_elem = root.find('.//hl7:code[@displayName="age"]/../hl7:value', ns)
    age = f"{age_elem.attrib.get('value', '')} {age_elem.attrib.get('unit', '')}" if age_elem is not None else ''

    weight_elem = root.find('.//hl7:code[@displayName="bodyWeight"]/../hl7:value', ns)
    weight = f"{weight_elem.attrib.get('value', '')} {weight_elem.attrib.get('unit', '')}" if weight_elem is not None else ''

    height_elem = root.find('.//hl7:code[@displayName="height"]/../hl7:value', ns)
    height = f"{height_elem.attrib.get('value', '')} {height_elem.attrib.get('unit', '')}" if height_elem is not None else ''

    # Dynamic Patient Detail
    patient_parts = []
    if gender: patient_parts.append(f"Gender: {gender}")
    if age: patient_parts.append(f"Age: {age}")
    if height: patient_parts.append(f"Height: {height}")
    if weight: patient_parts.append(f"Weight: {weight}")
    patient_detail = ", ".join(patient_parts)

    # Identify suspect drug IDs
    suspect_ids = []
    for causality in root.findall('.//hl7:causalityAssessment', ns):
        val_elem = causality.find('.//hl7:value', ns)
        if val_elem is not None and val_elem.attrib.get('code') == '1':
            subj_id_elem = causality.find('.//hl7:subject2/hl7:productUseReference/hl7:id', ns)
            if subj_id_elem is not None:
                suspect_ids.append(subj_id_elem.attrib.get('root', ''))

    # Dynamic Product Detail for suspect drugs & company products
    product_details_list = []
    for drug in root.findall('.//hl7:substanceAdministration', ns):
        id_elem = drug.find('.//hl7:id', ns)
        drug_id = id_elem.attrib.get('root', '') if id_elem is not None else ''
        if drug_id in suspect_ids:
            name_elem = drug.find('.//hl7:kindOfProduct/hl7:name', ns)
            drug_name = name_elem.text.lower() if name_elem is not None and name_elem.text else ''
            if drug_name in company_products:  # Only company products
                parts = []
                if drug_name: parts.append(f"Drug: {name_elem.text}")
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
                    product_details_list.append(", ".join(parts))

    product_details_combined = "\n".join(product_details_list)

    # Event Details
    seriousness_criteria = list(seriousness_map.keys())
    event_details_list = []
    event_count = 1
    mapping_df = pd.read_excel(mapping_file) if mapping_file else None

    for reaction in root.findall('.//hl7:observation', ns):
        code_elem = reaction.find('hl7:code', ns)
        if code_elem is not None and code_elem.attrib.get('displayName') == 'reaction':
            value_elem = reaction.find('hl7:value', ns)
            llt_code = value_elem.attrib.get('code', '') if value_elem is not None else ''
            llt_term, pt_term = llt_code, ''
            if mapping_df is not None and llt_code:
                row = mapping_df[mapping_df['LLT Code'] == int(llt_code)]
                if not row.empty:
                    llt_term = row['LLT Term'].values[0]
                    pt_term = row['PT Term'].values[0]

            seriousness_flags = []
            for criterion in seriousness_criteria:
                criterion_elem = reaction.find(f'.//hl7:code[@displayName="{criterion}"]/../hl7:value', ns)
                if criterion_elem is not None and criterion_elem.attrib.get('value') == 'true':
                    seriousness_flags.append(seriousness_map.get(criterion, criterion))

            outcome_elem = reaction.find('.//hl7:code[@displayName="outcome"]/../hl7:value', ns)
            outcome = map_outcome(outcome_elem.attrib.get('code', '') if outcome_elem is not None else '')

            details = f"Event {event_count}: {llt_term} ({pt_term}) (Seriousness: {', '.join(seriousness_flags)}; Outcome: {outcome})"
            event_details_list.append(details)
            event_count += 1

    event_details_combined = "\n".join(event_details_list)

    # Narrative
    narrative_elem = root.find('.//hl7:code[@code="PAT_ADV_EVNT"]/../hl7:text', ns)
    narrative = narrative_elem.text if narrative_elem is not None else ''

    # Prepare DataFrame
    data = [{
        'SL No': 1,
        'Date': current_date,
        'Sender ID': sender_id,
        'Transmission Date': transmission_date,
        'Reporter Qualification': reporter_qualification,
        'Patient Detail': patient_detail,
        'Product Detail': product_details_combined,
        'Event Details': event_details_combined,
        'Narrative': narrative,
        'Listedness': '',
        'Validity': '',
        'Tool Assessment': ''
    }]
    df = pd.DataFrame(data)

    # Display without index
    st.write(df.to_html(index=False), unsafe_allow_html=True)

    # Export options
    csv = df.to_csv(index=False)
    excel_buffer = io.BytesIO()
    with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    st.download_button("Download CSV", csv, "parsed_data.csv")
    st.download_button("Download Excel", excel_buffer.getvalue(), "parsed_data.xlsx")


















