# Radhhanand Sangeet Vidyalaya — Tabla Class & Music Academy Management System
> *"Preserving Tradition. Nurturing Artistry. Mastering Rhythm."*

**Radhhanand Sangeet Vidyalaya** (internally codebase **TAAL**) is an enterprise-grade, beginner-friendly Django web application designed for tabla teachers, gurus, and Indian classical music academies. It manages the complete operations of the academy—including student admissions, batch scheduling, automatic recurring timetables, session-linked attendance, dedicated fee collections with official PDF e-receipts, WhatsApp notifications, and parent chatbot assistance.

---

## 1. Academy Overview & Technology Stack

* **Exact Academy Name:** **Radhhanand Sangeet Vidyalaya**
* **Primary Discipline:** Indian Classical Tabla & Hindustani Sangeet
* **Backend Framework:** Python 3.13, Django 6.1 (Django ORM, Authentication, Migrations)
* **Database:** SQLite (`db.sqlite3`) with relational integrity, foreign keys, and automated backup snapshots
* **Document Engine:** ReportLab 5.0 for dynamic vector PDF e-receipt generation with Indian Rupee (`₹`) symbol formatting
* **Messaging Integration:** Meta WhatsApp Business Cloud API with safe local Test Mode simulation and delivery tracking
* **Frontend:** Bootstrap 5, Bootstrap Icons, responsive tables, modal dialogs, and print stylesheets
* **Data Security:** CSRF protection, SQL injection prevention, safe CSV formula sanitization (CWE-1236 protection), and OTP verification for parent chatbot queries

---

## 2. Core Functional Modules

### 1. Academy Dashboard
* **Real-time Metric Cards:** Active students, active batches, today's scheduled classes, today's attendance ratio, monthly fees collected, and total outstanding dues.
* **Quick Access Toolbar:** One-click shortcuts to Students, Batches, Timetable, Attendance, Fees & Payments, Reports, WhatsApp Center, and Settings.
* **Alerts & Reminders:** Automatically alerts staff to low attendance, consecutive missed classes, or upcoming payments.

### 2. Student Management
* **Fields:** Student ID (`TAL-YYYY-XXXX`), Full Name, Contact Number, Parent/Guardian Name, Guardian WhatsApp, Email, Residential Address, Admission Date, Learning Level, Monthly Tuition Fee, Active/Archived status, and Musical Notes.
* **Features:** Search by name/ID/phone/batch, filter active vs archived, attendance percentages, upcoming classes schedule, complete payment history, and safe non-destructive archiving.

### 3. Batch Management
* **Fields:** Batch Name, Course (e.g. Tabla), Curriculum Level, Instructor, Regular Day, Start/End Times, Max Capacity, Standard Monthly Fee, Start/End Dates, Active/Archived status.
* **Features:** Visual capacity meter, assign/remove students, batch timetable rules, and safe archiving that preserves all past class and attendance records.

### 4. Automatic Recurring Timetable
* **Weekly Recurring Rules:** Configurable slots per batch. Includes academy default presets:
  * **Tuesday, Thursday, Saturday:** 5:00 PM – 6:00 PM, 6:00 PM – 7:00 PM, 7:00 PM – 8:00 PM
  * **Sunday:** 8:00 AM – 11:00 AM (or split shorter sessions)
* **Idempotent Schedule Generation:** Generates upcoming classes for 30, 60, 90, or 180 days ahead without ever duplicating existing sessions (`generate_future_sessions`).
* **Rescheduling & Cancellation:** Move individual classes with recorded reasons (`reschedule_reason`), or cancel sessions while keeping past attendance intact.

### 5. Attendance Management
* **Session-linked Attendance:** Attendance is tied directly to scheduled class sessions and recorded by authorized staff.
* **Status Options:** Present, Absent, On Leave, and optional Late.
* **Analytical Indicators:** Real-time attendance percentage calculations, consecutive absence tracking, and low-attendance watchlist.
* **Audit Trail:** Any corrections to saved attendance automatically record the user, previous status, new status, and audit reason.

### 6. Dedicated Fees & Payments Section
* **Financial Overview:** Total collected this month, total collected this year, and outstanding dues across all students.
* **Filter & Search:** Filter transactions by status (Paid in Full, Partially Paid, Pending Dues), Batch, Month, Year, and Payment Method (Cash, UPI, Bank Transfer, Cheque).
* **Payment Processing:** Records payments with duplicate submission prevention via idempotency keys, partial balance calculations, and safe payment reversal with audit notes.
* **Official E-Receipts:** Formatted e-receipt view with sequential numbering (`RSV-REC-YYYY-XXXX`).

### 7. Professional PDF E-Receipts (ReportLab)
* Direct download at `/fees/receipts/<id>/pdf/` generating an official PDF receipt.
* Features academy branding, registered address, student ID, billing period, fee breakdown table, outstanding balance, and authorized signatory line.

### 8. WhatsApp Business Integration & Chatbot
* **Test Mode:** Runs out-of-the-box in simulated mode without requiring external API credentials.
* **Class Reminders:** Dispatches automated class reminders to parent WhatsApp numbers with duplicate prevention.
* **Receipt Delivery:** Dispatches receipt notifications directly to parents upon payment.
* **Parent Chatbot Assistant:** Handles queries about today's class time, next upcoming class, fee balances, and academy contact.
* **Privacy Safe:** Only registered guardian numbers receive student-specific information.

### 9. Academy Reports
* **Attendance Reports:** Comprehensive register by date range and batch, plus low-attendance watchlist.
* **Fee Reports:** Income by payment method, fully paid students, and pending dues register.
* **Timetable Reports:** Overview of conducted, scheduled, rescheduled, and cancelled sessions.
* **Exporting:** One-click CSV exports sanitized against spreadsheet formula injection.

---

## 3. Quick Start Guide for Windows

### Step 1: Open PowerShell in Project Folder
```powershell
cd c:\Users\Admin\Desktop\NEWAS
```

### Step 2: Confirm Python Environment
```powershell
python --version
```
*(Python 3.10+ recommended; Python 3.13.0 verified)*

### Step 3: Install Required Dependencies
Ensure the necessary libraries are installed:
```powershell
pip install -r requirements.txt
```
*(Dependencies: Django >= 5.0, reportlab >= 4.0, requests >= 2.28)*

### Step 4: Run Database Migrations
Apply any pending database migrations:
```powershell
python manage.py migrate
```

### Step 5: Start the Development Server
```powershell
python manage.py runserver
```
Open your browser and navigate to:
```
http://127.0.0.1:8000/
```

Default credentials (if configured) or create an admin account:
```powershell
python manage.py createsuperuser
```

---

## 4. Useful Management Commands

### 1. Generate Upcoming Recurring Classes
To generate upcoming classes from batch weekly timetable rules for the next 60 days:
```powershell
python manage.py generate_sessions --days 60
```
*Note: This command is idempotent and can be safely executed repeatedly via Windows Task Scheduler or cron without duplicating classes.*

### 2. Dispatch WhatsApp Class Reminders
To send automated class reminders for today's upcoming scheduled sessions:
```powershell
python manage.py send_class_reminders
```
*(In Test Mode, this safely logs simulated messages to `WhatsAppMessageLog`)*

### 3. Run Automated Tests
Execute the complete test suite (30 unit & acceptance tests):
```powershell
python manage.py test
```

---

## 5. Live WhatsApp Business Cloud API Configuration (Optional)

To enable live WhatsApp delivery instead of simulated Test Mode:

1. Obtain your **Phone Number ID** and **Permanent Access Token** from the [Meta for Developers Portal](https://developers.facebook.com/).
2. Set the following environment variables (or add them to your environment):
```powershell
$env:WHATSAPP_TEST_MODE = "False"
$env:WHATSAPP_PHONE_NUMBER_ID = "YOUR_META_PHONE_NUMBER_ID"
$env:WHATSAPP_ACCESS_TOKEN = "YOUR_META_PERMANENT_ACCESS_TOKEN"
$env:WHATSAPP_VERIFY_TOKEN = "YOUR_CUSTOM_WEBHOOK_VERIFY_TOKEN"
```
3. Configure the Meta Webhook URL:
   * **Callback URL:** `https://your-domain.com/whatsapp/webhook/`
   * **Verify Token:** Matching `WHATSAPP_VERIFY_TOKEN`
   * **Subscribed Fields:** `messages`

When `WHATSAPP_TEST_MODE` is `"True"` (or credentials are left unset), the application safely logs all messages to the local database under `simulated` status without making external network calls.

---

## 6. Database Safety & Backup Procedures

### Database Location
The active database is stored at:
```text
c:\Users\Admin\Desktop\NEWAS\db.sqlite3
```

### Pre-Migration Backup Location
A pre-improvement snapshot of the database is preserved at:
```text
c:\Users\Admin\Desktop\NEWAS\backups\backup_before_improvements_20261013.sqlite3
```

### Manual Backup Creation
To create a manual timestamped database snapshot at any time:
1. Log in to the application.
2. Navigate to **Administration > Database Backups** (`/backups/`).
3. Click **"Create Database Backup Now"**.
4. The snapshot is saved to the `backups/` folder and can be downloaded directly from the web interface.

---

## 7. Academy Branding Guidelines
* All user-facing titles, receipt headings, email/WhatsApp templates, and navigation banners strictly display:
  **Radhhanand Sangeet Vidyalaya**
* Tagline: *"Preserving Tradition. Nurturing Artistry. Mastering Rhythm."*
* Official Currency: Indian Rupee (`₹`)
