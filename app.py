
import streamlit as st
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime
import io

# Configure page layout
st.set_page_config(layout="wide")

# Custom CSS for layout optimization
st.markdown("""
<style>
.block-container {
    padding-top: 1rem;
    padding-left: 1rem;
    padding-right: 1rem;
}
.scroll-container {
    overflow-x: auto;
    overflow-y: auto;
    max-height: 500px;
    border: 1px solid #ddd;
    padding: 10px;
    width: 100%;
}
table {
    white-space: nowrap;
    width: 100%;
}
.footer {
    margin-top: 20px;
    font-size: 14px;
    color: gray;
    text-align: center;
}
</style>
""", unsafe_allow_html=True)

# ✅ Password Protection
password = st.text_input("Enter Password to Access App:", type="password")
if password != "7064242966":
    st.warning("Please enter the correct password to proceed.")
    st.stop()

# ✅ Embedded MedDRA Mapping File
# Replace this with actual path or embedded data
embedded_mapping_path = "meddra_mapping.xlsx"
mapping_df = pd.read_excel(embedded_mapping_path)

# UI
st.title("📊 E2B XML Parser with Multiple File Support")
st.markdown("""
### ✅ Instructions:
- Upload **multiple E2B XML files**.
- Combined data will be displayed in a scrollable window.
- You can edit Listedness, Validity, and App Assessment directly in the table.
- Download options for CSV and Excel are available below.
""")

# Clear Inputs Button
if st.button("Clear Inputs"):
    st.session_state.clear()
    st.experimental_rerun()

# File Uploads
uploaded_files = st.file_uploader("Upload E2B XML files", type=["xml"], accept_multiple_files=True)

all_rows_display = []
all_rows_export = []
current_date = datetime.now().strftime("%d-%b-%Y")

if uploaded_files:
    for idx, uploaded_file in enumerate(uploaded_files, start=1):
        tree = ET.parse(uploaded_file)
        root = tree.getroot()
        ns = {'hl7': 'urn:hl7-org:v3'}

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

        # Patient details
        patient_parts = []
        if gender: patient_parts.append(f"Gender: {gender}")
        if age: patient_parts.append(f"Age: {age}")
        if height: patient_parts.append(f"Height: {height}")
        if weight: patient_parts.append(f"Weight: {weight}")
        patient_detail = ", ".join(patient_parts)

        # Suspect drug IDs
        suspect_ids = []
        for causality in root.findall('.//hl7:causalityAssessment', ns):
            val_elem = causality.find('.//hl7:value', ns)
            if val_elem is not None and val_elem.attrib.get('code') == '1':
                subj_id_elem = causality.find('.//hl7:subject2/hl7:productUseReference/hl7:id', ns)
                if subj_id_elem is not None:
                    suspect_ids.append(subj_id_elem.attrib.get('root', ''))

        # Product details
        product_details_list = []
        for drug in root.findall('.//hl7:substanceAdministration', ns):
            id_elem = drug.find('.//hl7:id', ns)
            drug_id = id_elem.attrib.get('root', '') if id_elem is not None else ''
            if drug_id in suspect_ids:
                name_elem = drug.find('.//hl7:kindOfProduct/hl7:name', ns)
                drug_name = name_elem.text.lower() if name_elem is not None and name_elem.text else ''
                if drug_name in company_products:
                    parts = []
                    if drug_name: parts.append(f"Drug: {name_elem.text}")
                    text_elem = drug.find('.//hl7:text', ns)
                    if text_elem is not None and text_elem.text: parts.append(f"Dosage: {text_elem.text}")
                    dose_elem = drug.find('.//hl7:doseQuantity', ns)
                    if dose_elem is not None:
                        dose_val = dose_elem.attrib.get('value', '')
                        dose_unit = dose_elem.attrib.get('unit', '')
                        if dose_val or dose_unit: parts.append(f"Dose: {dose_val} {dose_unit}")
                    form_elem = drug.find('.//hl7:formCode/hl7:originalText', ns)
                    if form_elem is not None and form_elem.text: parts.append(f"Formulation: {form_elem.text}")
                    lot_elem = drug.find('.//hl7:lotNumberText', ns)
                    if lot_elem is not None and lot_elem.text: parts.append(f"Lot No: {lot_elem.text}")
                    start_elem = drug.find('.//hl7:low', ns)
                    start_date = format_date(start_elem.attrib.get('value', '') if start_elem is not None else '')
                    if start_date: parts.append(f"Start Date: {start_date}")
                    stop_elem = drug.find('.//hl7:high', ns)
                    stop_date = format_date(stop_elem.attrib.get('value', '') if stop_elem is not None else '')
                    if stop_date: parts.append(f"Stop Date: {stop_date}")
                    if parts: product_details_list.append(" | ".join(parts))

        product_details_combined = " | ".join(product_details_list)

        # Event details
        seriousness_criteria = list(seriousness_map.keys())
        event_details_list = []
        event_count = 1
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

        event_details_combined_display = "<br>".join(event_details_list)
        event_details_combined_export = "\n".join(event_details_list)

        # Narrative
        narrative_elem = root.find('.//hl7:code[@code="PAT_ADV_EVNT"]/../hl7:text', ns)
        narrative_full = narrative_elem.text if narrative_elem is not None else ''
        narrative_display = " ".join(narrative_full.split()[:10]) + "..." if len(narrative_full.split()) > 10 else narrative_full

        # Append rows
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
            'Listedness': '',
            'Validity': '',
            'App Assessment': ''
        })

        all_rows_export.append({
            'SL No': idx,
            'Date': current_date,
            'Sender ID': sender_id,
            'Transmission Date': transmission_date,
            'Reporter Qualification': reporter_qualification,
            'Patient Detail': patient_detail,
            'Product Detail': product_details_combined,
            'Event Details': event_details_combined_export,
            'Narrative': narrative_full,
            'Listedness': '',
            'Validity': '',
            'App Assessment': ''
        })

    # Editable Table (only last 3 columns editable)
    df_display = pd.DataFrame(all_rows_display)
    editable_cols = ['Listedness', 'Validity', 'App Assessment']
    disabled_cols = [col for col in df_display.columns if col not in editable_cols]
    edited_df = st.data_editor(df_display, num_rows="dynamic", use_container_width=True, disabled=disabled_cols)

    # Export options
    df_export = pd.DataFrame(all_rows_export)
    csv = df_export.to_csv(index=False)
    excel_buffer = io.BytesIO()
    with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
        df_export.to_excel(writer, index=False)

    st.download_button("Download CSV", csv, "parsed_data.csv")
    st.download_button("Download Excel", excel_buffer.getvalue(), "parsed_data.xlsx")

# Footer
st.markdown("""
<div class="footer">
    <b>Developed by Jagamohan</b><br>
    <i>Disclaimer: App is in developmental stage, validate before using the data.</i>
</div>
""", unsafe_allow_html=True)





