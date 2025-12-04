
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

