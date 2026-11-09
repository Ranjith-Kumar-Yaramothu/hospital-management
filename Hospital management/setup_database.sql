-- ============================================================
-- HOSPITAL MANAGEMENT SYSTEM - COMPLETE DATABASE SETUP
-- Run ONCE in MySQL Workbench: Ctrl+A, then Ctrl+Shift+Enter
-- Creates: hospital_db, all tables, procedures, triggers, views,
-- sample data, availability, payments, and the app login user.
-- ============================================================

-- =====================================================
-- Hospital Management System (MySQL 8.0+)
-- Run in MySQL Workbench or the mysql CLI
-- =====================================================

DROP DATABASE IF EXISTS hospital_db;
CREATE DATABASE hospital_db;
USE hospital_db;

-- ---------- 1. TABLES ----------

CREATE TABLE departments (
    dept_id     INT AUTO_INCREMENT PRIMARY KEY,
    dept_name   VARCHAR(60) NOT NULL UNIQUE
);

CREATE TABLE doctors (
    doctor_id        INT AUTO_INCREMENT PRIMARY KEY,
    full_name        VARCHAR(100) NOT NULL,
    specialization   VARCHAR(80),
    dept_id          INT NOT NULL,
    phone            VARCHAR(15) UNIQUE,
    consultation_fee DECIMAL(8,2) NOT NULL CHECK (consultation_fee >= 0),
    FOREIGN KEY (dept_id) REFERENCES departments(dept_id)
);

CREATE TABLE patients (
    patient_id    INT AUTO_INCREMENT PRIMARY KEY,
    full_name     VARCHAR(100) NOT NULL,
    gender        ENUM('Male','Female','Other') NOT NULL,
    date_of_birth DATE NOT NULL,
    phone         VARCHAR(15) UNIQUE,
    address       VARCHAR(200),
    registered_on DATE DEFAULT (CURRENT_DATE)
);

CREATE TABLE appointments (
    appointment_id INT AUTO_INCREMENT PRIMARY KEY,
    patient_id     INT NOT NULL,
    doctor_id      INT NOT NULL,
    appt_date      DATE NOT NULL,
    appt_time      TIME NOT NULL,
    status         ENUM('Scheduled','Completed','Cancelled') DEFAULT 'Scheduled',
    reason         VARCHAR(200),
    FOREIGN KEY (patient_id) REFERENCES patients(patient_id),
    FOREIGN KEY (doctor_id)  REFERENCES doctors(doctor_id),
    INDEX idx_doctor_slot (doctor_id, appt_date, appt_time),
    INDEX idx_patient (patient_id)
);

CREATE TABLE medicines (
    medicine_id   INT AUTO_INCREMENT PRIMARY KEY,
    medicine_name VARCHAR(100) NOT NULL UNIQUE,
    unit_price    DECIMAL(8,2) NOT NULL CHECK (unit_price >= 0),
    stock_qty     INT NOT NULL DEFAULT 0 CHECK (stock_qty >= 0)
);

CREATE TABLE prescriptions (
    prescription_id INT AUTO_INCREMENT PRIMARY KEY,
    appointment_id  INT NOT NULL UNIQUE,
    diagnosis       VARCHAR(200),
    notes           VARCHAR(300),
    FOREIGN KEY (appointment_id) REFERENCES appointments(appointment_id)
);

CREATE TABLE prescription_items (
    item_id         INT AUTO_INCREMENT PRIMARY KEY,
    prescription_id INT NOT NULL,
    medicine_id     INT NOT NULL,
    dosage          VARCHAR(30),          -- e.g. 1-0-1
    days            INT NOT NULL CHECK (days > 0),
    quantity        INT NOT NULL CHECK (quantity > 0),
    FOREIGN KEY (prescription_id) REFERENCES prescriptions(prescription_id),
    FOREIGN KEY (medicine_id)     REFERENCES medicines(medicine_id)
);

CREATE TABLE bills (
    bill_id             INT AUTO_INCREMENT PRIMARY KEY,
    appointment_id      INT NOT NULL UNIQUE,
    consultation_charge DECIMAL(10,2) NOT NULL,
    medicine_charge     DECIMAL(10,2) NOT NULL DEFAULT 0,
    total_amount        DECIMAL(10,2) GENERATED ALWAYS AS (consultation_charge + medicine_charge) STORED,
    payment_status      ENUM('Unpaid','Paid') DEFAULT 'Unpaid',
    bill_date           DATE DEFAULT (CURRENT_DATE),
    FOREIGN KEY (appointment_id) REFERENCES appointments(appointment_id)
);

CREATE TABLE appointment_audit (
    audit_id       INT AUTO_INCREMENT PRIMARY KEY,
    appointment_id INT NOT NULL,
    old_status     VARCHAR(20),
    new_status     VARCHAR(20),
    changed_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ---------- 2. STORED PROCEDURES ----------

DELIMITER $$

-- Book an appointment (validates date and doctor availability)
CREATE PROCEDURE sp_book_appointment(
    IN p_patient_id INT,
    IN p_doctor_id  INT,
    IN p_date       DATE,
    IN p_time       TIME,
    IN p_reason     VARCHAR(200)
)
BEGIN
    IF p_date < CURRENT_DATE THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Cannot book an appointment in the past';
    END IF;

    IF EXISTS (SELECT 1 FROM appointments
               WHERE doctor_id = p_doctor_id
                 AND appt_date = p_date
                 AND appt_time = p_time
                 AND status <> 'Cancelled') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Doctor already has an appointment at this slot';
    END IF;

    INSERT INTO appointments (patient_id, doctor_id, appt_date, appt_time, reason)
    VALUES (p_patient_id, p_doctor_id, p_date, p_time, p_reason);

    SELECT LAST_INSERT_ID() AS new_appointment_id;
END$$

-- Generate (or refresh) the bill for an appointment
CREATE PROCEDURE sp_generate_bill(IN p_appointment_id INT)
BEGIN
    DECLARE v_fee DECIMAL(10,2);
    DECLARE v_meds DECIMAL(10,2);

    SELECT d.consultation_fee INTO v_fee
    FROM appointments a
    JOIN doctors d ON d.doctor_id = a.doctor_id
    WHERE a.appointment_id = p_appointment_id;

    IF v_fee IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Appointment not found';
    END IF;

    SELECT COALESCE(SUM(pi.quantity * m.unit_price), 0) INTO v_meds
    FROM prescriptions p
    JOIN prescription_items pi ON pi.prescription_id = p.prescription_id
    JOIN medicines m           ON m.medicine_id = pi.medicine_id
    WHERE p.appointment_id = p_appointment_id;

    INSERT INTO bills (appointment_id, consultation_charge, medicine_charge)
    VALUES (p_appointment_id, v_fee, v_meds)
    ON DUPLICATE KEY UPDATE consultation_charge = v_fee,
                            medicine_charge     = v_meds;

    SELECT * FROM bills WHERE appointment_id = p_appointment_id;
END$$

-- ---------- 3. TRIGGERS ----------

-- Block prescriptions that exceed available stock
CREATE TRIGGER trg_check_stock
BEFORE INSERT ON prescription_items
FOR EACH ROW
BEGIN
    DECLARE v_stock INT;
    SELECT stock_qty INTO v_stock FROM medicines WHERE medicine_id = NEW.medicine_id;
    IF v_stock < NEW.quantity THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Insufficient medicine stock';
    END IF;
END$$

-- Reduce stock after a medicine is prescribed
CREATE TRIGGER trg_reduce_stock
AFTER INSERT ON prescription_items
FOR EACH ROW
BEGIN
    UPDATE medicines
    SET stock_qty = stock_qty - NEW.quantity
    WHERE medicine_id = NEW.medicine_id;
END$$

-- Log every appointment status change
CREATE TRIGGER trg_appointment_audit
AFTER UPDATE ON appointments
FOR EACH ROW
BEGIN
    IF OLD.status <> NEW.status THEN
        INSERT INTO appointment_audit (appointment_id, old_status, new_status)
        VALUES (NEW.appointment_id, OLD.status, NEW.status);
    END IF;
END$$

DELIMITER ;

-- ---------- 4. VIEWS ----------

CREATE VIEW v_todays_appointments AS
SELECT a.appointment_id, a.appt_time, p.full_name AS patient, d.full_name AS doctor, a.status
FROM appointments a
JOIN patients p ON p.patient_id = a.patient_id
JOIN doctors  d ON d.doctor_id  = a.doctor_id
WHERE a.appt_date = CURRENT_DATE;

CREATE VIEW v_doctor_revenue AS
SELECT d.doctor_id, d.full_name, dp.dept_name,
       COUNT(b.bill_id) AS billed_visits,
       COALESCE(SUM(b.total_amount), 0) AS revenue
FROM doctors d
JOIN departments dp ON dp.dept_id = d.dept_id
LEFT JOIN appointments a ON a.doctor_id = d.doctor_id
LEFT JOIN bills b        ON b.appointment_id = a.appointment_id
GROUP BY d.doctor_id, d.full_name, dp.dept_name;

CREATE VIEW v_patient_history AS
SELECT p.patient_id, p.full_name AS patient, a.appt_date, d.full_name AS doctor,
       pr.diagnosis, b.total_amount, b.payment_status
FROM patients p
JOIN appointments a      ON a.patient_id = p.patient_id
JOIN doctors d           ON d.doctor_id = a.doctor_id
LEFT JOIN prescriptions pr ON pr.appointment_id = a.appointment_id
LEFT JOIN bills b        ON b.appointment_id = a.appointment_id;

CREATE VIEW v_pending_bills AS
SELECT b.bill_id, p.full_name AS patient, b.total_amount, b.bill_date
FROM bills b
JOIN appointments a ON a.appointment_id = b.appointment_id
JOIN patients p     ON p.patient_id = a.patient_id
WHERE b.payment_status = 'Unpaid';

-- ---------- 5. SAMPLE DATA ----------

INSERT INTO departments (dept_name) VALUES ('General Medicine'), ('Cardiology'), ('Orthopedics');

INSERT INTO doctors (full_name, specialization, dept_id, phone, consultation_fee) VALUES
('Dr. Anil Kumar',  'General Physician', 1, '9000000001', 300),
('Dr. Meera Rao',   'Cardiologist',      2, '9000000002', 700),
('Dr. Suresh Babu', 'Orthopedic Surgeon',3, '9000000003', 600);

INSERT INTO patients (full_name, gender, date_of_birth, phone, address) VALUES
('Ravi Teja',   'Male',   '1995-04-12', '9111111101', 'Hyderabad'),
('Sneha Reddy', 'Female', '1988-09-30', '9111111102', 'Wanaparthy'),
('Arjun Das',   'Male',   '2001-01-18', '9111111103', 'Warangal');

INSERT INTO medicines (medicine_name, unit_price, stock_qty) VALUES
('Paracetamol 500mg', 2.00, 500),
('Amoxicillin 250mg', 8.00, 300),
('Aspirin 75mg',      3.00, 400),
('Ibuprofen 400mg',   5.00, 8);

-- Past (completed) appointments inserted directly
INSERT INTO appointments (patient_id, doctor_id, appt_date, appt_time, status, reason) VALUES
(1, 1, '2026-10-01', '10:00:00', 'Completed', 'Fever'),
(2, 2, '2026-10-02', '11:00:00', 'Completed', 'Chest discomfort'),
(1, 1, '2026-10-03', '09:30:00', 'Completed', 'Follow-up');

INSERT INTO prescriptions (appointment_id, diagnosis, notes) VALUES
(1, 'Viral fever',  'Rest and fluids'),
(2, 'Mild angina',  'ECG advised');

INSERT INTO prescription_items (prescription_id, medicine_id, dosage, days, quantity) VALUES
(1, 1, '1-1-1', 5, 15),
(1, 2, '1-0-1', 5, 10),
(2, 3, '0-1-0', 10, 10);

CALL sp_generate_bill(1);
CALL sp_generate_bill(2);
CALL sp_generate_bill(3);

-- Future appointment via the procedure
CALL sp_book_appointment(3, 3, CURDATE() + INTERVAL 1 DAY, '10:00:00', 'Knee pain');

-- ---------- 6. TEST THE TRIGGERS / PROCEDURES ----------

-- Should fail: slot already taken
-- CALL sp_book_appointment(2, 3, CURDATE() + INTERVAL 1 DAY, '10:00:00', 'Back pain');

-- Should fail: only 8 Ibuprofen in stock
-- INSERT INTO prescription_items (prescription_id, medicine_id, dosage, days, quantity) VALUES (1, 4, '1-0-1', 10, 20);

-- Should create an audit row
UPDATE appointments SET status = 'Cancelled' WHERE appointment_id = 4;
SELECT * FROM appointment_audit;

-- ---------- 7. INTERVIEW-STYLE QUERIES ----------

-- 1. Patients with more than one visit
SELECT p.full_name, COUNT(*) AS visits
FROM patients p JOIN appointments a ON a.patient_id = p.patient_id
GROUP BY p.patient_id, p.full_name
HAVING COUNT(*) > 1;

-- 2. Revenue ranking of doctors within each department (window function)
SELECT dept_name, full_name, revenue,
       RANK() OVER (PARTITION BY dept_name ORDER BY revenue DESC) AS dept_rank
FROM v_doctor_revenue;

-- 3. Monthly revenue with running total
SELECT DATE_FORMAT(bill_date, '%Y-%m') AS month,
       SUM(total_amount) AS revenue,
       SUM(SUM(total_amount)) OVER (ORDER BY DATE_FORMAT(bill_date, '%Y-%m')) AS running_total
FROM bills
GROUP BY DATE_FORMAT(bill_date, '%Y-%m');

-- 4. Medicines running low on stock
SELECT medicine_name, stock_qty FROM medicines WHERE stock_qty < 20;

-- 5. Patients who have never had a prescription (subquery)
SELECT full_name FROM patients
WHERE patient_id NOT IN (
    SELECT a.patient_id FROM appointments a
    JOIN prescriptions pr ON pr.appointment_id = a.appointment_id
);

-- 6. Most prescribed medicine
SELECT m.medicine_name, SUM(pi.quantity) AS total_qty
FROM prescription_items pi JOIN medicines m ON m.medicine_id = pi.medicine_id
GROUP BY m.medicine_id, m.medicine_name
ORDER BY total_qty DESC
LIMIT 1;

-- 7. Doctors with no appointments (LEFT JOIN + NULL check)
SELECT d.full_name
FROM doctors d LEFT JOIN appointments a ON a.doctor_id = d.doctor_id
WHERE a.appointment_id IS NULL;

-- 8. Pending bills report
SELECT * FROM v_pending_bills;

-- 9. Average age of patients by gender
SELECT gender, ROUND(AVG(TIMESTAMPDIFF(YEAR, date_of_birth, CURDATE())), 1) AS avg_age
FROM patients GROUP BY gender;

-- 10. Check index usage on the slot lookup
EXPLAIN SELECT * FROM appointments
WHERE doctor_id = 1 AND appt_date = '2026-10-01' AND appt_time = '10:00:00';

-- ================= PART 2: UPGRADE =================

-- Patient email (needed for email features)
ALTER TABLE patients ADD COLUMN email VARCHAR(120) NULL AFTER phone;

-- Doctor availability (weekly schedule)
CREATE TABLE doctor_availability (
    avail_id    INT AUTO_INCREMENT PRIMARY KEY,
    doctor_id   INT NOT NULL,
    day_of_week ENUM('Mon','Tue','Wed','Thu','Fri','Sat','Sun') NOT NULL,
    start_time  TIME NOT NULL,
    end_time    TIME NOT NULL,
    FOREIGN KEY (doctor_id) REFERENCES doctors(doctor_id),
    CHECK (end_time > start_time)
);

-- Payments (a bill can be paid in parts)
CREATE TABLE payments (
    payment_id INT AUTO_INCREMENT PRIMARY KEY,
    bill_id    INT NOT NULL,
    amount     DECIMAL(10,2) NOT NULL CHECK (amount > 0),
    method     ENUM('Cash','Card','UPI','Insurance') NOT NULL,
    paid_on    DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (bill_id) REFERENCES bills(bill_id)
);

-- Default availability: Mon-Sat, 09:00-17:00 for every doctor
INSERT INTO doctor_availability (doctor_id, day_of_week, start_time, end_time)
SELECT d.doctor_id, x.dow, '09:00:00', '17:00:00'
FROM doctors d
JOIN (SELECT 'Mon' AS dow UNION ALL SELECT 'Tue' UNION ALL SELECT 'Wed'
      UNION ALL SELECT 'Thu' UNION ALL SELECT 'Fri' UNION ALL SELECT 'Sat') x;

DELIMITER $$

-- Booking now also checks doctor availability
DROP PROCEDURE IF EXISTS sp_book_appointment$$
CREATE PROCEDURE sp_book_appointment(
    IN p_patient_id INT,
    IN p_doctor_id  INT,
    IN p_date       DATE,
    IN p_time       TIME,
    IN p_reason     VARCHAR(200)
)
BEGIN
    IF p_date < CURRENT_DATE THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Cannot book an appointment in the past';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM doctor_availability
                   WHERE doctor_id = p_doctor_id
                     AND day_of_week = LEFT(DAYNAME(p_date), 3)
                     AND p_time >= start_time
                     AND p_time <  end_time) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Doctor is not available on this day/time';
    END IF;

    IF EXISTS (SELECT 1 FROM appointments
               WHERE doctor_id = p_doctor_id
                 AND appt_date = p_date
                 AND appt_time = p_time
                 AND status <> 'Cancelled') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Doctor already has an appointment at this slot';
    END IF;

    INSERT INTO appointments (patient_id, doctor_id, appt_date, appt_time, reason)
    VALUES (p_patient_id, p_doctor_id, p_date, p_time, p_reason);

    SELECT LAST_INSERT_ID() AS new_appointment_id;
END$$

-- Cancel an appointment (only if still scheduled)
CREATE PROCEDURE sp_cancel_appointment(IN p_appointment_id INT)
BEGIN
    DECLARE v_status VARCHAR(20);

    SELECT status INTO v_status FROM appointments WHERE appointment_id = p_appointment_id;

    IF v_status IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Appointment not found';
    END IF;
    IF v_status <> 'Scheduled' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Only scheduled appointments can be cancelled';
    END IF;

    UPDATE appointments SET status = 'Cancelled' WHERE appointment_id = p_appointment_id;
END$$

-- Record a payment (cannot exceed the bill balance)
CREATE PROCEDURE sp_record_payment(
    IN p_bill_id INT,
    IN p_amount  DECIMAL(10,2),
    IN p_method  VARCHAR(20)
)
BEGIN
    DECLARE v_total DECIMAL(10,2);
    DECLARE v_paid  DECIMAL(10,2);

    SELECT total_amount INTO v_total FROM bills WHERE bill_id = p_bill_id;
    IF v_total IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Bill not found';
    END IF;

    SELECT COALESCE(SUM(amount), 0) INTO v_paid FROM payments WHERE bill_id = p_bill_id;
    IF v_paid + p_amount > v_total THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Payment exceeds the bill balance';
    END IF;

    INSERT INTO payments (bill_id, amount, method) VALUES (p_bill_id, p_amount, p_method);
END$$

-- Mark the bill as Paid once payments cover the total
CREATE TRIGGER trg_update_bill_status
AFTER INSERT ON payments
FOR EACH ROW
BEGIN
    UPDATE bills
    SET payment_status = 'Paid'
    WHERE bill_id = NEW.bill_id
      AND (SELECT SUM(amount) FROM payments WHERE bill_id = NEW.bill_id) >= total_amount;
END$$

DELIMITER ;


-- ================= PART 3: APP LOGIN USER =================
DROP USER IF EXISTS 'hospital_user'@'localhost';
CREATE USER 'hospital_user'@'localhost' IDENTIFIED BY 'Hospital@123';
GRANT ALL PRIVILEGES ON hospital_db.* TO 'hospital_user'@'localhost';
FLUSH PRIVILEGES;

USE hospital_db;
SHOW TABLES;
SELECT * FROM v_doctor_revenue;
