
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









