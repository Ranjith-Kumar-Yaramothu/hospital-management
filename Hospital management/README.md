# Hospital Management System
Python + MySQL + Streamlit (with Pandas, Plotly, PDF receipts and Email)

## Features
Patient registration, doctor and department management, doctor availability,
appointment booking and cancellation, patient history, prescriptions, billing,
payments, doctor reports, appointment analytics, PDF receipts, email.

## Folder contents
| File | Purpose |
|---|---|
| setup_database.sql | ONE script: creates hospital_db, tables, procedures, triggers, views, sample data, and the app login user |
| app.py | The Streamlit application |
| requirements.txt | Python packages |
| .streamlit/secrets.toml | Database login used by app.py (already matches setup_database.sql) |
| hospital_management_system.sql, hospital_upgrade.sql | The two parts that setup_database.sql combines (for reference) |

## How to run
1. MySQL Workbench: open setup_database.sql, press Ctrl+A, then Ctrl+Shift+Enter.
   (It DROPS and recreates hospital_db, so run it once.)
2. In a terminal inside this folder:
   python -m pip install -r requirements.txt
3. Start the app:
   python -m streamlit run app.py

## Login created by the setup script
user: hospital_user   password: Hospital@123   database: hospital_db
Change the password in BOTH setup_database.sql and .streamlit/secrets.toml if you want a different one.

## Email (optional)
Uncomment the [email] section in .streamlit/secrets.toml and use a Gmail App Password.

## Before uploading to GitHub
Never upload .streamlit/secrets.toml (the included .gitignore already excludes it).
