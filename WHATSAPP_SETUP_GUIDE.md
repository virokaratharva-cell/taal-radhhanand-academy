# Official WhatsApp Setup & Activation Guide
**Radhhanand Sangeet Vidyalaya — TAAL Academy System**

This guide is designed for beginners. It explains exactly how WhatsApp messaging is built into your academy system, what is currently working in Test Mode, and what exact steps you must take to send real messages to parents.

---

## 1. Status of the Current WhatsApp Integration

* **Implementation Status:** Fully implemented in the backend code (`academy/services.py`, `academy/views.py`, `academy/management/commands/send_class_reminders.py`).
* **Current Operational State:** Currently operating in **Test Mode (Simulated)**.
* **Why it operates in Test Mode:** The system does not have live Meta API credentials yet. In Test Mode, every reminder and fee receipt is generated with real student and timetable data, validated, and logged into the `WhatsAppMessageLog` database table without calling Meta's servers or incurring charges. The entire academy system remains 100% operational even without API credentials.

---

## 2. Which WhatsApp Service is Used and Why

* **Provider:** **Meta WhatsApp Business Platform Cloud API** (Direct Graph API v21.0).
* **Why this provider was chosen:**
  1. Direct connection to Meta without paying middleman markups (like Twilio or third-party gateways).
  2. Official Meta compliance — avoids phone numbers being banned for spam.
  3. Supports WhatsApp Message Templates, two-way chatbot webhooks, and automated PDF receipt notifications.
  4. Meta provides 1,000 free service conversations per month for every WhatsApp Business account.

---

## 3. Account Requirements: What You Need

To send real messages to parents, you need:
1. A **Personal Facebook Account** (to log into Meta for Developers).
2. A **Meta for Developers Account** (free to register).
3. A **Meta Business Portfolio / WhatsApp Business Account** (created automatically during developer setup).
4. A **Dedicated Phone Number** for the academy (a number not currently active on personal WhatsApp on a mobile phone, or a virtual landline/mobile number).

---

## 4. How to Create and Configure the Meta Account (Step by Step)

1. Go to [developers.facebook.com](https://developers.facebook.com) and log in with your Facebook credentials.
2. Click **Get Started** or **My Apps** in the top-right corner.
3. Click **Create App**.
4. Select **Other** > click **Next**.
5. Select **Business** as the app type > click **Next**.
6. Enter an App Name (e.g., `Radhhanand Academy Alerts`) and enter your email address.
7. Click **Create App**.
8. On the App Dashboard, scroll to **WhatsApp** and click **Set up**.
9. Select or create your Meta Business Account.

---

## 5. How to Obtain the Phone Number ID and Access Token

Once WhatsApp is added to your app:

1. Navigate to **WhatsApp** > **API Setup** on the left menu.
2. You will see:
   * **Temporary Access Token** (valid for 24 hours for initial testing).
   * **Phone number ID** (a 15-digit number, e.g. `104829104928104`).
   * **WhatsApp Business Account ID** (e.g. `109283746192837`).
3. For a **Permanent Access Token** (required for production):
   * Go to **Meta Business Settings** (`business.facebook.com/settings`).
   * Navigate to **Users** > **System Users**.
   * Click **Add**, name it `taal-bot`, and assign the **Admin** role.
   * Click **Generate New Token**, select your WhatsApp App, and choose permissions:
     * `whatsapp_business_messaging`
     * `whatsapp_business_management`
   * Copy the generated token immediately and store it securely.

---

## 6. Exact Environment Variable Names

The Django project expects these exact environment variable names in `config/settings.py`:

| Variable Name | Required? | Example Value | Description |
| :--- | :--- | :--- | :--- |
| `WHATSAPP_PHONE_NUMBER_ID` | Yes (for live) | `105829104928104` | Your Meta Phone Number ID |
| `WHATSAPP_ACCESS_TOKEN` | Yes (for live) | `EAAG...` | Permanent System User Token |
| `WHATSAPP_VERIFY_TOKEN` | Optional | `radhhanand_webhook_secret_2026` | Webhook verification token |
| `WHATSAPP_API_VERSION` | Optional | `v21.0` | Meta Graph API Version (default: v21.0) |
| `WHATSAPP_TEST_MODE` | Yes | `True` or `False` | `False` for real messages, `True` for simulation |

---

## 7. Where to Configure Variables Locally Without Exposing Secrets

Never commit API tokens to GitHub.

1. In the project folder `c:\Users\Admin\Desktop\NEWAS\`, create a file named `.env` (or set environment variables in your terminal).
2. Add your values:
   ```env
   WHATSAPP_PHONE_NUMBER_ID=105829104928104
   WHATSAPP_ACCESS_TOKEN=EAAGxxxxxxxxxxxxxxxxx
   WHATSAPP_VERIFY_TOKEN=radhhanand_webhook_secret_2026
   WHATSAPP_API_VERSION=v21.0
   WHATSAPP_TEST_MODE=False
   ```
3. In PowerShell, you can also set them for your session:
   ```powershell
   $env:WHATSAPP_PHONE_NUMBER_ID="105829104928104"
   $env:WHATSAPP_ACCESS_TOKEN="EAAGxxxxxxxxxxxxxxxxx"
   $env:WHATSAPP_TEST_MODE="False"
   ```
4. Verify that `.env` is listed in your `.gitignore` file.

---

## 8. Webhook Configuration (For Two-Way Chatbot Queries)

If you want parents to query the system via WhatsApp (e.g. asking for class times or fee balances):

1. Your server must be hosted online with HTTPS (e.g. `https://academy.yourdomain.com`).
2. In Meta for Developers, go to **WhatsApp** > **Configuration**.
3. Under **Webhook**, click **Edit**.
4. Set **Callback URL**: `https://academy.yourdomain.com/whatsapp/webhook/`
5. Set **Verify Token**: `radhhanand_webhook_secret_2026` (matching your `WHATSAPP_VERIFY_TOKEN`).
6. Click **Verify and Save**.
7. Under **Webhook fields**, click **Manage** and subscribe to `messages`.

---

## 9. Message Templates and WhatsApp Messaging Rules

Meta enforces strict rules for business messages:
* **User-Initiated (Within 24 Hours):** If a parent sends a message to the academy number first, you can reply with freeform text within 24 hours.
* **Business-Initiated (Outside 24 Hours):** Class reminders and payment receipts sent proactively must use pre-approved Meta message templates.

### Recommended Templates to Submit in Meta Business Manager:

#### A. Class Reminder Template
* **Template Name:** `class_reminder_v1`
* **Category:** Utility
* **Language:** English
* **Body:**
  ```text
  Hello! This is Radhhanand Sangeet Vidyalaya.

  Reminder: Your child's {{1}} Tabla class is scheduled for today ({{2}}) at {{3}}.

  Please ensure regular riyaz before class. Contact the academy if you need any assistance.

  Thank you!
  ```

#### B. Fee Payment Receipt Template
* **Template Name:** `fee_receipt_v1`
* **Category:** Utility
* **Language:** English
* **Body:**
  ```text
  Hello! This is Radhhanand Sangeet Vidyalaya.

  Fee Payment Confirmed:
  • Receipt No: {{1}}
  • Student: {{2}} ({{3}})
  • Fee Period: {{4}}
  • Amount Received: ₹{{5}}
  • Remaining Balance: ₹{{6}}
  • Payment Date: {{7}}

  You can view and download your official PDF receipt anytime from the academy portal.

  Thank you!
  ```

---

## 10. Recipient Phone Numbers and Consent Handling

1. **Format:** Enter parent numbers as 10-digit Indian numbers (e.g., `9876543210`) or with country code (`+919876543210`). The system automatically cleans spaces and normalizes to standard international format `919876543210`.
2. **Consent:** When enrolling a student in `StudentForm`, the WhatsApp number is saved.
3. **Opt-Out:** If a parent requests not to receive WhatsApp messages, check **Parent opted out of WhatsApp reminders & receipts** on the student profile. The system will automatically skip sending reminders and receipts to that parent.

---

## 11. How to Test One Message Safely

Before enabling automatic messages:
1. In Meta Developer Dashboard under **API Setup**, add your personal phone number as a **Test Recipient**.
2. Keep `WHATSAPP_TEST_MODE=True`.
3. Open the academy system in your browser and visit:
   `http://localhost:8000/whatsapp/simulator/`
4. Send a test reminder or test receipt.
5. Visit `http://localhost:8000/whatsapp/` (WhatsApp Center) to see the message logged with status `Simulated (Test Mode)`.
6. When ready to send one real message:
   * Set `WHATSAPP_TEST_MODE=False` in environment.
   * Send a test reminder to your verified test number.

---

## 12. How to Activate Scheduled Class Reminders

To send class reminders to all parents of students having classes today:

1. Run the management command manually:
   ```bash
   python manage.py send_class_reminders
   ```
2. Or use the manual button:
   * Go to **Class Schedule** (`/sessions/`).
   * Find today's session and click **Send WhatsApp Reminder**.
3. **Automating with a background scheduler:**
   * On Linux/Ubuntu: Set up a daily cron job at 8:00 AM:
     ```cron
     0 8 * * * cd /path/to/NEWAS && /path/to/venv/bin/python manage.py send_class_reminders >> /var/log/taal_reminders.log 2>&1
     ```
   * On Windows: Create a Scheduled Task in Windows Task Scheduler to run `manage.py send_class_reminders` every morning at 8:00 AM.

---

## 13. How to Activate Payment Receipt Delivery

Payment receipt delivery is available immediately:
1. Whenever a fee payment is recorded in **Fees & Payments** (`/fees/payments/add/`), click on the receipt.
2. Click **Send via WhatsApp**.
3. The electronic receipt with receipt number, student name, amount received, and outstanding balance is dispatched directly to the parent's verified WhatsApp number.
4. Idempotency is enforced: sending multiple times will not duplicate payments or spam parents.

---

## 14. Background Worker, Scheduler, and Hosting Configuration

To ensure reminders continue running even when your personal laptop is turned off:
1. Deploy the Django project to a 24/7 cloud server (such as a DigitalOcean Droplet, Hetzner, AWS EC2, or PythonAnywhere).
2. Configure **Systemd** or **Cron** on the server to run `python manage.py send_class_reminders` every morning at 8:00 AM.
3. Configure `python manage.py generate_sessions --days 60` to run once a week to keep the timetable filled 60 days in advance.

---

## 15. How to Check Delivery Logs and Troubleshoot

1. In the academy system, click **WhatsApp Center** on the navigation menu (`/whatsapp/`).
2. You will see:
   * **Recipient Phone & Student Name**
   * **Message Type** (Class Reminder, Payment Receipt, Chatbot Reply)
   * **Status** (`Sent`, `Delivered`, `Failed`, or `Simulated`)
   * **Provider Message ID** or **Error Details**
3. If a message fails, common reasons and solutions:
   * *Error: (#131030) Recipient phone number not in allowed list:* (In Meta development mode, you must add the recipient's number to the test number list until you publish the app).
   * *Error: (#190) Invalid OAuth access token:* Generate a fresh permanent System User token.
   * *Error: (#132000) Template does not exist:* Ensure the template name in Meta matches `class_reminder_v1`.
4. Click **Retry** next to any failed message to re-attempt delivery without re-creating records.

---

## 16. How to Switch from Test Mode to Production Mode Safely

1. **Verify your Business** in Meta Business Manager (`business.facebook.com/settings/info`).
2. Add your official academy payment method (credit/debit card) in Meta Business Manager.
3. Register your real academy phone number and complete SMS OTP verification.
4. Set in your `.env` file:
   ```env
   WHATSAPP_TEST_MODE=False
   WHATSAPP_PHONE_NUMBER_ID=<your-real-phone-number-id>
   WHATSAPP_ACCESS_TOKEN=<your-permanent-system-user-token>
   ```
5. Restart your Django server.

---

## 17. Costs, Usage Limits, and Provider Charges

* **Meta Free Tier:** Meta grants **1,000 free service conversations per month** for every WhatsApp Business Account.
* **Utility Conversations (Reminders & Receipts):** In India, utility conversations outside the free tier cost approximately ₹0.12 to ₹0.35 per conversation.
* **Customer Service Inquiries:** Replies to incoming parent messages within a 24-hour window are completely free.
* **Daily Messaging Limit:** New unverified accounts start with a limit of 250 business-initiated conversations per 24 hours, which automatically scales up to 1,000, 10,000, and unlimited as your account quality rating remains high.
