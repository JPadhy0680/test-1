# E2B_R3 XML Triage Application

This version loads permanent Excel master files from the repository `data/` folder and refreshes cached data when those Excel files change.

## Required repository structure

```text
app.py
requirements.txt
data/
  MedDRA.xlsx
  Listedness_CX.xlsx
```

## What changed

- The XML uploader remains available.
- The MedDRA uploader has been removed.
- The Listedness uploader has been removed.
- The app automatically loads:
  - `data/MedDRA.xlsx`
  - `data/Listedness_CX.xlsx`
- Cache refresh was improved using file modified time and file size, so when the Excel files are replaced in GitHub/deployment, the app reloads the latest data after redeploy/reboot.

## Deployment note

After pushing updated Excel files to GitHub, reboot or redeploy the Streamlit app so the deployment filesystem receives the latest files.
