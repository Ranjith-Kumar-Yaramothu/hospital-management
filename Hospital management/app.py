"""Hospital Management System - Python + MySQL + Streamlit
Run with:  streamlit run app.py
"""
import io
import smtplib
from datetime import date, time
from email.message import EmailMessage

import mysql.connector
import pandas as pd
import plotly.express as px
import streamlit as st
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

st.set_page_config(page_title="Hospital Management System", page_icon="🏥", layout="wide")


# ============================================================
# Database helpers
# ============================================================
def get_conn():
    cfg = st.secrets["mysql"]
    return mysql.connector.connect(
        host=cfg["host"],
        port=int(cfg.get("port", 3306)),
        user=cfg["user"],
        password=cfg["password"],
        database=cfg["database"],
    )


def query(sql, params=None):
    """Run a SELECT and return a DataFrame."""
    conn = get_conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, params or ())
        return pd.DataFrame(cur.fetchall())
    finally:
        conn.close()


def execute(sql, params=None):
    """Run INSERT / UPDATE / DELETE."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def call(proc, args):
    """Call a stored procedure; returns a list of DataFrames (its result sets)."""
    conn = get_conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.callproc(proc, args)
        results = [pd.DataFrame(r.fetchall()) for r in cur.stored_results()]
        conn.commit()
        return results
    finally:
        conn.close()


def run(action, success_msg=None):
    """Run a DB action, showing MySQL errors (e.g. from SIGNAL) nicely."""
    try:
        result = action()
        if success_msg:
            st.success(success_msg)
        return result
    except mysql.connector.Error as e:
        st.error(f"Database error: {e.msg}")
        return None


def num(df, cols):
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c])
    return df


def pick(label, sql, params=None, key=None):
    """Selectbox built from a query returning `id` and `label` columns."""
    df = query(sql, params)
    if df.empty:
        st.info(f"Nothing available for: {label}")
        return None
    mapping = {row["label"]: int(row["id"]) for _, row in df.iterrows()}
    return mapping[st.selectbox(label, list(mapping.keys()), key=key)]


def show(df):
    if df.empty:
        st.caption("No records found.")
    else:
        st.dataframe(df, width="stretch", hide_index=True)


def chart(fig):
    st.plotly_chart(fig, width="stretch")


# ============================================================
# Email + PDF helpers
# ============================================================
def email_configured():
    return "email" in st.secrets


def send_email(to, subject, body, attachment=None, filename="bill.pdf"):
    cfg = st.secrets["email"]
    msg = EmailMessage()
    msg["From"] = cfg["sender"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if attachment:
        msg.add_attachment(attachment, maintype="application", subtype="pdf", filename=filename)
    with smtplib.SMTP(cfg["host"], int(cfg["port"])) as server:
        server.starttls()
        server.login(cfg["username"], cfg["password"])
        server.send_message(msg)


def bill_details(bill_id):
    header = query(
        """SELECT b.bill_id, b.bill_date, b.consultation_charge, b.medicine_charge,
                  b.total_amount, b.payment_status, p.full_name AS patient, p.email,
                  d.full_name AS doctor, a.appt_date
           FROM bills b
           JOIN appointments a ON a.appointment_id = b.appointment_id
           JOIN patients p     ON p.patient_id = a.patient_id
           JOIN doctors d      ON d.doctor_id = a.doctor_id
           WHERE b.bill_id = %s""",
        (bill_id,),
    ).iloc[0]
    meds = query(
        """SELECT m.medicine_name, pi.quantity, m.unit_price,
                  pi.quantity * m.unit_price AS amount
           FROM bills b
           JOIN prescriptions pr      ON pr.appointment_id = b.appointment_id
           JOIN prescription_items pi ON pi.prescription_id = pr.prescription_id
           JOIN medicines m           ON m.medicine_id = pi.medicine_id
           WHERE b.bill_id = %s""",
        (bill_id,),
    )
    return header, num(meds, ["unit_price", "amount"])


def make_bill_pdf(h, meds):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _, height = A4
    y = height - 60

    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, y, "Hospital Bill Receipt")
    y -= 30

    c.setFont("Helvetica", 11)
    for line in [
        f"Bill No: {h['bill_id']}",
        f"Bill date: {h['bill_date']}",
        f"Patient: {h['patient']}",
        f"Doctor: {h['doctor']}",
        f"Visit date: {h['appt_date']}",
        f"Payment status: {h['payment_status']}",
    ]:
        c.drawString(50, y, line)
        y -= 18
    y -= 12

    c.setFont("Helvetica-Bold", 11)
    c.drawString(50, y, "Item")
    c.drawString(300, y, "Qty")
    c.drawString(360, y, "Price")
    c.drawString(450, y, "Amount")
    y -= 18

    c.setFont("Helvetica", 11)
    c.drawString(50, y, "Consultation")
    c.drawString(450, y, f"{float(h['consultation_charge']):.2f}")
    y -= 18
    for _, m in meds.iterrows():
        c.drawString(50, y, str(m["medicine_name"]))
        c.drawString(300, y, str(m["quantity"]))
        c.drawString(360, y, f"{float(m['unit_price']):.2f}")
        c.drawString(450, y, f"{float(m['amount']):.2f}")
        y -= 18

    y -= 12
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, f"Total: Rs. {float(h['total_amount']):.2f}")
    c.save()
    return buf.getvalue()


# ============================================================
# Pages
# ============================================================
def page_dashboard():
    st.header("Dashboard and appointment analytics")
    t = query(
        """SELECT (SELECT COUNT(*) FROM patients)     AS patients,
                  (SELECT COUNT(*) FROM doctors)      AS doctors,
                  (SELECT COUNT(*) FROM appointments) AS appointments,
                  (SELECT COALESCE(SUM(amount), 0) FROM payments) AS collected"""
    ).iloc[0]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Patients", int(t["patients"]))
    c2.metric("Doctors", int(t["doctors"]))
    c3.metric("Appointments", int(t["appointments"]))
    c4.metric("Collected (Rs.)", f"{float(t['collected']):,.2f}")

    left, right = st.columns(2)
    status = query("SELECT status, COUNT(*) AS total FROM appointments GROUP BY status")
    if not status.empty:
        left.subheader("Appointments by status")
        with left:
            chart(px.pie(status, names="status", values="total", hole=0.4))

    per_doctor = query(
        """SELECT d.full_name AS doctor, COUNT(*) AS appointments
           FROM appointments a JOIN doctors d ON d.doctor_id = a.doctor_id
           GROUP BY d.doctor_id, d.full_name"""
    )
    if not per_doctor.empty:
        right.subheader("Appointments per doctor")
        with right:
            chart(px.bar(per_doctor, x="doctor", y="appointments"))

    monthly = query(
        """SELECT LEFT(appt_date, 7) AS month, COUNT(*) AS appointments
           FROM appointments GROUP BY LEFT(appt_date, 7) ORDER BY month"""
    )
    if not monthly.empty:
        st.subheader("Appointments per month")
        chart(px.line(monthly, x="month", y="appointments", markers=True))


def page_patients():
    st.header("Patient registration")
    with st.form("new_patient", clear_on_submit=True):
        c1, c2 = st.columns(2)
        name = c1.text_input("Full name")
        gender = c2.selectbox("Gender", ["Male", "Female", "Other"])
        dob = c1.date_input("Date of birth", value=date(2000, 1, 1),
                            min_value=date(1900, 1, 1), max_value=date.today())
        phone = c2.text_input("Phone")
        email = c1.text_input("Email")
        address = c2.text_input("Address")
        submitted = st.form_submit_button("Register patient")
    if submitted:
        if not name.strip():
            st.error("Name is required")
        else:
            run(lambda: execute(
                """INSERT INTO patients (full_name, gender, date_of_birth, phone, email, address)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (name.strip(), gender, dob, phone.strip() or None,
                 email.strip() or None, address.strip() or None)),
                "Patient registered")

    st.subheader("All patients")
    search = st.text_input("Search by name or phone")
    df = query("""SELECT patient_id, full_name, gender, date_of_birth, phone, email,
                         address, registered_on
                  FROM patients ORDER BY patient_id DESC""")
    if search and not df.empty:
        mask = (df["full_name"].str.contains(search, case=False, na=False)
                | df["phone"].astype(str).str.contains(search, na=False))
        df = df[mask]
    show(df)


def page_departments():
    st.header("Department management")
    with st.form("new_dept", clear_on_submit=True):
        name = st.text_input("Department name")
        submitted = st.form_submit_button("Add department")
    if submitted and name.strip():
        run(lambda: execute("INSERT INTO departments (dept_name) VALUES (%s)", (name.strip(),)),
            "Department added")
    show(query("""SELECT dp.dept_id, dp.dept_name, COUNT(d.doctor_id) AS doctors
                  FROM departments dp LEFT JOIN doctors d ON d.dept_id = dp.dept_id
                  GROUP BY dp.dept_id, dp.dept_name ORDER BY dp.dept_name"""))


def page_doctors():
    st.header("Doctor management and availability")
    tab1, tab2 = st.tabs(["Doctors", "Availability"])

    with tab1:
        with st.form("new_doctor", clear_on_submit=True):
            c1, c2 = st.columns(2)
            name = c1.text_input("Full name")
            spec = c2.text_input("Specialization")
            dept = pick("Department",
                        "SELECT dept_id AS id, dept_name AS label FROM departments ORDER BY dept_name",
                        key="doc_dept")
            phone = c1.text_input("Phone")
            fee = c2.number_input("Consultation fee", min_value=0.0, value=300.0, step=50.0)
            submitted = st.form_submit_button("Add doctor")
        if submitted:
            if not name.strip() or dept is None:
                st.error("Name and department are required")
            else:
                run(lambda: execute(
                    """INSERT INTO doctors (full_name, specialization, dept_id, phone, consultation_fee)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (name.strip(), spec.strip() or None, dept, phone.strip() or None, fee)),
                    "Doctor added")
        df = query("""SELECT d.doctor_id, d.full_name, d.specialization, dp.dept_name,
                             d.phone, d.consultation_fee
                      FROM doctors d JOIN departments dp ON dp.dept_id = d.dept_id
                      ORDER BY d.full_name""")
        show(num(df, ["consultation_fee"]))

    with tab2:
        doctor = pick("Doctor",
                      "SELECT doctor_id AS id, full_name AS label FROM doctors ORDER BY full_name",
                      key="avail_doc")
        if doctor:
            c1, c2, c3 = st.columns(3)
            day = c1.selectbox("Day", ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
            start = c2.time_input("From", value=time(9, 0), key="avail_start")
            end = c3.time_input("To", value=time(17, 0), key="avail_end")
            if st.button("Add availability slot"):
                run(lambda: execute(
                    """INSERT INTO doctor_availability (doctor_id, day_of_week, start_time, end_time)
                       VALUES (%s, %s, %s, %s)""", (doctor, day, start, end)),
                    "Availability added")
            show(query(
                """SELECT day_of_week AS weekday, LEFT(start_time, 5) AS from_time,
                          LEFT(end_time, 5) AS to_time
                   FROM doctor_availability WHERE doctor_id = %s
                   ORDER BY FIELD(day_of_week, 'Mon','Tue','Wed','Thu','Fri','Sat','Sun')""",
                (doctor,)))


def page_book():
    st.header("Book appointment")
    patient = pick("Patient",
                   """SELECT patient_id AS id, CONCAT(full_name, ' (#', patient_id, ')') AS label
                      FROM patients ORDER BY full_name""", key="book_patient")
    doctor = pick("Doctor",
                  """SELECT doctor_id AS id,
                            CONCAT(full_name, ' - ', COALESCE(specialization, ''), ' (fee ',
                                   consultation_fee, ')') AS label
                     FROM doctors ORDER BY full_name""", key="book_doctor")
    if doctor:
        st.caption("Doctor availability")
        show(query(
            """SELECT day_of_week AS weekday, LEFT(start_time, 5) AS from_time,
                      LEFT(end_time, 5) AS to_time
               FROM doctor_availability WHERE doctor_id = %s
               ORDER BY FIELD(day_of_week, 'Mon','Tue','Wed','Thu','Fri','Sat','Sun')""",
            (doctor,)))

    c1, c2 = st.columns(2)
    appt_date = c1.date_input("Date", min_value=date.today())
    appt_time = c2.time_input("Time", value=time(10, 0), step=900)
    reason = st.text_input("Reason for visit")
    notify = st.checkbox("Email a confirmation to the patient (if email is on file)")

    if patient and doctor and st.button("Book appointment"):
        res = run(lambda: call("sp_book_appointment",
                               [patient, doctor, appt_date, appt_time, reason.strip() or None]))
        if res and not res[0].empty:
            st.success(f"Appointment #{int(res[0].iloc[0, 0])} booked")
            if notify:
                info = query("SELECT full_name, email FROM patients WHERE patient_id = %s",
                             (patient,)).iloc[0]
                if pd.notna(info["email"]) and email_configured():
                    try:
                        send_email(info["email"], "Appointment confirmation",
                                   f"Hello {info['full_name']},\n\nYour appointment is confirmed "
                                   f"for {appt_date} at {appt_time.strftime('%H:%M')}.\n\nThank you.")
                        st.info("Confirmation email sent")
                    except Exception as e:  # noqa: BLE001
                        st.warning(f"Could not send email: {e}")
                else:
                    st.warning("No patient email on file, or email is not configured")


def page_appointments():
    st.header("Appointments")
    scheduled_sql = """SELECT a.appointment_id AS id,
                              CONCAT('#', a.appointment_id, ' - ', p.full_name, ' with ',
                                     d.full_name, ' on ', a.appt_date, ' ', LEFT(a.appt_time, 5)) AS label
                       FROM appointments a
                       JOIN patients p ON p.patient_id = a.patient_id
                       JOIN doctors d  ON d.doctor_id = a.doctor_id
                       WHERE a.status = 'Scheduled' ORDER BY a.appt_date, a.appt_time"""

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Cancel appointment")
        cancel_id = pick("Scheduled appointment", scheduled_sql, key="cancel_pick")
        if cancel_id and st.button("Cancel appointment"):
            run(lambda: call("sp_cancel_appointment", [cancel_id]), "Appointment cancelled")
    with c2:
        st.subheader("Mark as completed")
        done_id = pick("Scheduled appointment", scheduled_sql, key="done_pick")
        if done_id and st.button("Mark completed"):
            run(lambda: execute("UPDATE appointments SET status = 'Completed' WHERE appointment_id = %s",
                                (done_id,)), "Appointment marked completed")

    st.subheader("All appointments")
    statuses = st.multiselect("Filter by status", ["Scheduled", "Completed", "Cancelled"],
                              default=["Scheduled", "Completed", "Cancelled"])
    if statuses:
        placeholders = ",".join(["%s"] * len(statuses))
        show(query(
            f"""SELECT a.appointment_id, p.full_name AS patient, d.full_name AS doctor,
                       a.appt_date, LEFT(a.appt_time, 5) AS appt_time, a.status, a.reason
                FROM appointments a
                JOIN patients p ON p.patient_id = a.patient_id
                JOIN doctors d  ON d.doctor_id = a.doctor_id
                WHERE a.status IN ({placeholders})
                ORDER BY a.appt_date DESC, a.appt_time DESC""",
            tuple(statuses)))


def page_prescriptions():
    st.header("Prescriptions")
    tab1, tab2, tab3 = st.tabs(["Create prescription", "Add medicines", "Medicine stock"])

    with tab1:
        appt = pick(
            "Appointment without a prescription",
            """SELECT a.appointment_id AS id,
                      CONCAT('#', a.appointment_id, ' - ', p.full_name, ' / ', d.full_name,
                             ' / ', a.appt_date) AS label
               FROM appointments a
               JOIN patients p ON p.patient_id = a.patient_id
               JOIN doctors d  ON d.doctor_id = a.doctor_id
               LEFT JOIN prescriptions pr ON pr.appointment_id = a.appointment_id
               WHERE pr.prescription_id IS NULL AND a.status <> 'Cancelled'
               ORDER BY a.appt_date DESC""", key="rx_appt")
        diagnosis = st.text_input("Diagnosis")
        notes = st.text_area("Notes")
        if appt and st.button("Save prescription"):
            run(lambda: execute(
                "INSERT INTO prescriptions (appointment_id, diagnosis, notes) VALUES (%s, %s, %s)",
                (appt, diagnosis.strip() or None, notes.strip() or None)), "Prescription saved")

    with tab2:
        rx = pick("Prescription",
                  """SELECT pr.prescription_id AS id,
                            CONCAT('Rx #', pr.prescription_id, ' - ', p.full_name, ' - ',
                                   COALESCE(pr.diagnosis, 'no diagnosis')) AS label
                     FROM prescriptions pr
                     JOIN appointments a ON a.appointment_id = pr.appointment_id
                     JOIN patients p     ON p.patient_id = a.patient_id
                     ORDER BY pr.prescription_id DESC""", key="rx_pick")
        med = pick("Medicine",
                   """SELECT medicine_id AS id,
                             CONCAT(medicine_name, ' (stock ', stock_qty, ')') AS label
                      FROM medicines ORDER BY medicine_name""", key="med_pick")
        c1, c2, c3 = st.columns(3)
        dosage = c1.text_input("Dosage (e.g. 1-0-1)")
        days = c2.number_input("Days", min_value=1, value=5)
        qty = c3.number_input("Quantity", min_value=1, value=10)
        if rx and med and st.button("Add medicine"):
            run(lambda: execute(
                """INSERT INTO prescription_items (prescription_id, medicine_id, dosage, days, quantity)
                   VALUES (%s, %s, %s, %s, %s)""",
                (rx, med, dosage.strip() or None, int(days), int(qty))), "Medicine added")
        if rx:
            show(query(
                """SELECT m.medicine_name, pi.dosage, pi.days, pi.quantity
                   FROM prescription_items pi JOIN medicines m ON m.medicine_id = pi.medicine_id
                   WHERE pi.prescription_id = %s""", (rx,)))

    with tab3:
        with st.form("new_med", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            name = c1.text_input("Medicine name")
            price = c2.number_input("Unit price", min_value=0.0, value=5.0, step=1.0)
            stock = c3.number_input("Stock quantity", min_value=0, value=100)
            submitted = st.form_submit_button("Add medicine to stock")
        if submitted and name.strip():
            run(lambda: execute(
                "INSERT INTO medicines (medicine_name, unit_price, stock_qty) VALUES (%s, %s, %s)",
                (name.strip(), price, int(stock))), "Medicine added")
        show(num(query("SELECT medicine_id, medicine_name, unit_price, stock_qty "
                       "FROM medicines ORDER BY medicine_name"), ["unit_price"]))


def page_billing():
    st.header("Billing and payments")
    tab1, tab2, tab3 = st.tabs(["Generate bill", "Record payment", "Receipt (PDF / email)"])

    with tab1:
        appt = pick(
            "Appointment without a bill",
            """SELECT a.appointment_id AS id,
                      CONCAT('#', a.appointment_id, ' - ', p.full_name, ' / ', a.appt_date) AS label
               FROM appointments a
               JOIN patients p ON p.patient_id = a.patient_id
               LEFT JOIN bills b ON b.appointment_id = a.appointment_id
               WHERE b.bill_id IS NULL AND a.status <> 'Cancelled'
               ORDER BY a.appt_date DESC""", key="bill_appt")
        if appt and st.button("Generate bill"):
            run(lambda: call("sp_generate_bill", [appt]), "Bill generated")

    with tab2:
        bill = pick(
            "Unpaid bill",
            """SELECT b.bill_id AS id,
                      CONCAT('Bill #', b.bill_id, ' - ', p.full_name, ' - total ', b.total_amount) AS label
               FROM bills b
               JOIN appointments a ON a.appointment_id = b.appointment_id
               JOIN patients p     ON p.patient_id = a.patient_id
               WHERE b.payment_status = 'Unpaid' ORDER BY b.bill_id DESC""", key="pay_bill")
        if bill:
            balance = float(query(
                """SELECT b.total_amount - COALESCE((SELECT SUM(amount) FROM payments
                                                     WHERE bill_id = b.bill_id), 0) AS balance
                   FROM bills b WHERE b.bill_id = %s""", (bill,)).iloc[0]["balance"])
            st.write(f"Balance due: Rs. {balance:,.2f}")
            amount = st.number_input("Amount", min_value=0.01, value=max(balance, 0.01),
                                     step=50.0, key=f"amt_{bill}")
            method = st.selectbox("Method", ["Cash", "Card", "UPI", "Insurance"])
            if st.button("Record payment"):
                run(lambda: call("sp_record_payment", [bill, amount, method]), "Payment recorded")

    with tab3:
        bill = pick(
            "Bill",
            """SELECT b.bill_id AS id,
                      CONCAT('Bill #', b.bill_id, ' - ', p.full_name, ' (', b.payment_status, ')') AS label
               FROM bills b
               JOIN appointments a ON a.appointment_id = b.appointment_id
               JOIN patients p     ON p.patient_id = a.patient_id
               ORDER BY b.bill_id DESC""", key="receipt_bill")
        if bill:
            header, meds = bill_details(bill)
            pdf = make_bill_pdf(header, meds)
            st.download_button("Download PDF receipt", pdf, file_name=f"bill_{bill}.pdf",
                               mime="application/pdf")
            default_email = str(header["email"]) if pd.notna(header["email"]) else ""
            to = st.text_input("Send receipt to", value=default_email, key=f"to_{bill}")
            if st.button("Email receipt"):
                if not email_configured():
                    st.error("Email is not configured in .streamlit/secrets.toml")
                elif not to.strip():
                    st.error("Enter an email address")
                else:
                    try:
                        send_email(to.strip(), f"Your hospital bill #{bill}",
                                   f"Hello {header['patient']},\n\nPlease find your bill attached.\n\nThank you.",
                                   pdf, f"bill_{bill}.pdf")
                        st.success("Receipt emailed")
                    except Exception as e:  # noqa: BLE001
                        st.error(f"Could not send email: {e}")

    st.subheader("All bills")
    df = query(
        """SELECT b.bill_id, p.full_name AS patient, b.total_amount,
                  COALESCE(SUM(pay.amount), 0) AS paid,
                  b.total_amount - COALESCE(SUM(pay.amount), 0) AS balance,
                  b.payment_status
           FROM bills b
           JOIN appointments a ON a.appointment_id = b.appointment_id
           JOIN patients p     ON p.patient_id = a.patient_id
           LEFT JOIN payments pay ON pay.bill_id = b.bill_id
           GROUP BY b.bill_id, p.full_name, b.total_amount, b.payment_status
           ORDER BY b.bill_id DESC""")
    show(num(df, ["total_amount", "paid", "balance"]))


def page_history():
    st.header("Patient history")
    patient = pick("Patient",
                   """SELECT patient_id AS id, CONCAT(full_name, ' (#', patient_id, ')') AS label
                      FROM patients ORDER BY full_name""", key="hist_patient")
    if not patient:
        return
    st.subheader("Visits and billing")
    df = query("""SELECT appt_date, doctor, diagnosis, total_amount, payment_status
                  FROM v_patient_history WHERE patient_id = %s ORDER BY appt_date DESC""", (patient,))
    show(num(df, ["total_amount"]))
    st.subheader("Prescribed medicines")
    show(query(
        """SELECT a.appt_date, d.full_name AS doctor, pr.diagnosis, m.medicine_name,
                  pi.dosage, pi.days, pi.quantity
           FROM appointments a
           JOIN doctors d             ON d.doctor_id = a.doctor_id
           JOIN prescriptions pr      ON pr.appointment_id = a.appointment_id
           JOIN prescription_items pi ON pi.prescription_id = pr.prescription_id
           JOIN medicines m           ON m.medicine_id = pi.medicine_id
           WHERE a.patient_id = %s ORDER BY a.appt_date DESC""", (patient,)))


def page_doctor_reports():
    st.header("Doctor reports")
    rev = num(query("SELECT full_name, dept_name, billed_visits, revenue FROM v_doctor_revenue "
                    "ORDER BY revenue DESC"), ["revenue"])
    show(rev)
    if not rev.empty:
        chart(px.bar(rev, x="full_name", y="revenue", color="dept_name",
                     labels={"full_name": "Doctor", "revenue": "Revenue (Rs.)"}))

    doctor = pick("Doctor details",
                  "SELECT doctor_id AS id, full_name AS label FROM doctors ORDER BY full_name",
                  key="rep_doc")
    if doctor:
        show(query(
            """SELECT a.appointment_id, p.full_name AS patient, a.appt_date,
                      LEFT(a.appt_time, 5) AS appt_time, a.status
               FROM appointments a JOIN patients p ON p.patient_id = a.patient_id
               WHERE a.doctor_id = %s ORDER BY a.appt_date DESC""", (doctor,)))


# ============================================================
# Navigation
# ============================================================
PAGES = {
    "Dashboard": page_dashboard,
    "Patients": page_patients,
    "Departments": page_departments,
    "Doctors & Availability": page_doctors,
    "Book Appointment": page_book,
    "Appointments": page_appointments,
    "Prescriptions": page_prescriptions,
    "Billing & Payments": page_billing,
    "Patient History": page_history,
    "Doctor Reports": page_doctor_reports,
}

st.sidebar.title("🏥 Hospital System")
choice = st.sidebar.radio("Menu", list(PAGES.keys()))

try:
    PAGES[choice]()
except mysql.connector.Error as e:
    st.error(f"Could not talk to MySQL: {e.msg}. Check .streamlit/secrets.toml and that the "
             "upgrade script has been run.")
