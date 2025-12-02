
import streamlit as st
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime
import io
import logging

logging.basicConfig(level=logging.INFO)

# ---------------- Helper Functions ---------------- #
def format_date(date_str):
    if not date_str or len(date_str) < 8:
        return ""
    try:
        return datetime.strptime(date_str[:8], "%Y%m%d").strftime("%d-%b-%Y")
    except ValueError as e:
        logging.warning(f"Date parsing failed: {e}")
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

# ---------------- Streamlit UI ---------------- #
st.title("👉 E2B XML Parser with LLT/PT Mapping ✅")

uploaded_file = st.file_uploader("Upload E2B XML file", type=["xml"])
mapping_file = st.file_uploader("Upload LLT-PT Mapping Excel file", type=["xlsx"])

if uploaded_file:
    tree = ET.parse(uploaded_file)
    root = tree.getroot()
    ns = {'hl7': 'urn:hl7-org:v3'}
    current_date = datetime.now().strftime("%d-%b-%Y")

    # Extract XML details
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

    # Suspect drugs
    drugs_info = {}
    for drug in root.findall('.//hl7:substanceAdministration', ns):
        id_elem = drug.find('.//hl7:id', ns)
        drug_id = id_elem.attrib.get('root', '') if id_elem is not None else ''
        name_elem = drug.find('.//hl7:kindOfProduct/hl7:name', ns)
        drug_name = name_elem.text if name_elem is not None else ''
        start_elem = drug.find('.//hl7:low', ns)
        start_date = format_date(start_elem.attrib.get('value', '') if start_elem is not None else '')
        stop_elem = drug.find('.//hl7:high', ns)
        stop_date = format_date(stop_elem.attrib.get('value', '') if stop_elem is not None else '')
        drugs_info[drug_id] = {'name': drug_name, 'start': start_date, 'stop': stop_date}

    suspect_drugs, suspect_starts, suspect_stops = [], [], []
    for causality in root.findall('.//hl7:causalityAssessment', ns):
        val_elem = causality.find('.//hl7:value', ns)
        if val_elem is not None and val_elem.attrib.get('code') == '1':
            subj_id_elem = causality.find('.//hl7:subject2/hl7:productUseReference/hl7:id', ns)
            if subj_id_elem is not None:
                ref_id = subj_id_elem.attrib.get('root', '')
                if ref_id in drugs_info:
                    suspect_drugs.append(drugs_info[ref_id]['name'])
                    suspect_starts.append(drugs_info[ref_id]['start'])
                    suspect_stops.append(drugs_info[ref_id]['stop'])

    drug_names_combined = ', '.join(suspect_drugs)
    start_dates_combined = ', '.join(suspect_starts)
    stop_dates_combined = ', '.join(suspect_stops)

    # Event Details and LLT Codes
    seriousness_criteria = [
        "resultsInDeath",
        "isLifeThreatening",
        "requiresInpatientHospitalization",
        "resultsInPersistentOrSignificantDisability",
        "congenitalAnomalyBirthDefect",
        "otherMedicallyImportantCondition"
    ]
    
event_details_list = []
event_count = 1
llt_codes = []

for reaction in root.findall('.//hl7:observation', ns):
    code_elem = reaction.find('hl7:code', ns)
    if code_elem is not None and code_elem.attrib.get('displayName') == 'reaction':
        value_elem = reaction.find('hl7:value', ns)
        llt_code = value_elem.attrib.get('code', '') if value_elem is not None else ''
        if llt_code:
            llt_codes.append(llt_code)

            # Lookup LLT Term and PT Term
            llt_term, pt_term = '', ''
            if mapping_file:
                row = mapping_df[mapping_df['LLT Code'] == int(llt_code)]
                if not row.empty:
                    llt_term = row['LLT Term'].values[0]
                    pt_term = row['PT Term'].values[0]

            # Seriousness flags
            seriousness_flags = []
            for criterion in seriousness_criteria:
                criterion_elem = reaction.find(f'.//hl7:code[@displayName="{criterion}"]/../hl7:value', ns)
                if criterion_elem is not None and criterion_elem.attrib.get('value') == 'true':
                    seriousness_flags.append(criterion)

            outcome_elem = reaction.find('.//hl7:code[@displayName="outcome"]/../hl7:value', ns)
            outcome = map_outcome(outcome_elem.attrib.get('code', '') if outcome_elem is not None else '')

            # Build event detail string
            details = f"Event {event_count}: {llt_term} ({pt_term}) (Seriousness: {', '.join(seriousness_flags)}; Outcome: {outcome})"
            event_details_list.append(details)
            event_count += 1

event_details_combined = "\n".join(event_details_list)


    # Narrative
    narrative_elem = root.find('.//hl7:code[@code="PAT_ADV_EVNT"]/../hl7:text', ns)
    narrative = narrative_elem.text if narrative_elem is not None else ''

    # LLT/PT Mapping
    llt_terms, pt_terms = [], []
    if mapping_file:
        mapping_df = pd.read_excel(mapping_file)
        for code in llt_codes:
            row = mapping_df[mapping_df['LLT Code'] == int(code)]
            if not row.empty:
                llt_terms.append(row['LLT Term'].values[0])
                pt_terms.append(row['PT Term'].values[0])
            else:
                llt_terms.append('')
                pt_terms.append('')

    llt_codes_combined = ', '.join(llt_codes)
    llt_terms_combined = ', '.join(llt_terms)
    pt_terms_combined = ', '.join(pt_terms)

    # Prepare DataFrame
    data = [{
        'Current Date': current_date,
        'Sender ID': sender_id,
        'Transmission Date': transmission_date,
        'Reporter Qualification': reporter_qualification,
        'Gender': gender,
        'Age': age,
        'Weight': weight,
        'Height': height,
        'Drug Names': drug_names_combined,
        'Start Dates': start_dates_combined,
        'Stop Dates': stop_dates_combined,
        'Event Details': event_details_combined,
        'LLT Codes': llt_codes_combined,
        'LLT Terms': llt_terms_combined,
        'PT Terms': pt_terms_combined,
        'Narrative': narrative
    }]
    df = pd.DataFrame(data)
    st.dataframe(df)

    # Export options
    csv = df.to_csv(index=False)
    excel_buffer = io.BytesIO()
    with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    st.download_button("Download CSV", csv, "parsed_data.csv")








