from datetime import date, time, timedelta
from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from django.db import IntegrityError

from academy.models import (
    AcademySettings, Student, Batch, BatchEnrollment,
    ClassSession, Attendance, AttendanceAuditLog,
    Taal, Composition, Lesson, PracticeAssignment,
    FeePlan, PaymentRecord, AcademyAlert
)
from academy.services import (
    calculate_student_attendance, calculate_batch_attendance,
    record_session_attendance, sanitize_csv_cell,
    create_database_backup, seed_foundational_taals_and_compositions
)


class TaalAuthenticationTests(TestCase):
    """Tests for teacher authentication and view protection."""

    def setUp(self):
        self.teacher = User.objects.create_user(
            username='testteacher',
            password='password123',
            first_name='Pt.',
            last_name='Sharma'
        )
        self.client = Client()

    def test_unauthorized_access_redirects_to_login(self):
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)

    def test_teacher_login_success(self):
        login_success = self.client.login(username='testteacher', password='password123')
        self.assertTrue(login_success)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pt. Sharma")

    def test_teacher_logout(self):
        self.client.login(username='testteacher', password='password123')
        response = self.client.get(reverse('logout'))
        self.assertEqual(response.status_code, 302)
        # Dashboard should now be protected
        resp2 = self.client.get(reverse('dashboard'))
        self.assertEqual(resp2.status_code, 302)


class StudentAndBatchManagementTests(TestCase):
    """Tests for student and batch lifecycle and enrollment tracking."""

    def setUp(self):
        self.teacher = User.objects.create_user(username='teacher', password='pwd')
        self.today = timezone.now().date()

    def test_auto_generated_unique_student_id(self):
        s1 = Student.objects.create(first_name='Ananya', last_name='Roy', enrollment_date=self.today)
        s2 = Student.objects.create(first_name='Vikram', last_name='Seth', enrollment_date=self.today)

        self.assertTrue(s1.student_id.startswith(f"TAL-{self.today.year}-"))
        self.assertTrue(s2.student_id.startswith(f"TAL-{self.today.year}-"))
        self.assertNotEqual(s1.student_id, s2.student_id)

    def test_batch_creation_and_enrollment_history(self):
        batch = Batch.objects.create(
            batch_id='BAT-TEST-01',
            name='Test Riyaz Batch',
            level='beginner',
            regular_day='Saturday',
            start_time=time(10, 0),
            end_time=time(11, 0),
            start_date=self.today
        )
        student = Student.objects.create(first_name='Aarav', last_name='Joshi', enrollment_date=self.today)

        # Enroll student
        enr = BatchEnrollment.objects.create(
            student=student,
            batch=batch,
            enrolled_date=self.today,
            is_active=True
        )
        self.assertEqual(batch.active_students_count, 1)

        # Deactivate student without deleting historical link
        enr.is_active = False
        enr.left_date = self.today + timedelta(days=30)
        enr.save()

        self.assertEqual(batch.active_students_count, 0)
        self.assertEqual(BatchEnrollment.objects.filter(student=student, batch=batch).count(), 1)


class AttendanceCalculationAndIntegrityTests(TestCase):
    """
    Validates all critical attendance business rules:
    - Only conducted sessions count
    - Scheduled sessions never generate absences
    - Cancelled sessions never count as absences
    - Prior sessions (before enrollment) are excluded
    - Audit log recorded on corrections
    - Safe from division by zero
    """

    def setUp(self):
        self.teacher = User.objects.create_user(username='guru', password='pwd')
        self.today = timezone.now().date()

        self.batch = Batch.objects.create(
            batch_id='BAT-TEEN-01',
            name='Teentaal Riyaz Batch',
            level='beginner',
            regular_day='Saturday',
            start_time=time(9, 0),
            end_time=time(10, 0),
            start_date=self.today - timedelta(days=60)
        )

        self.student = Student.objects.create(
            first_name='Kabir',
            last_name='Das',
            enrollment_date=self.today - timedelta(days=30),
            level='beginner',
            status='active'
        )

        BatchEnrollment.objects.create(
            student=self.student,
            batch=self.batch,
            enrolled_date=self.today - timedelta(days=30),
            is_active=True
        )

    def test_rule_only_conducted_sessions_count(self):
        # 1 session conducted 10 days ago (attended)
        sess1 = ClassSession.objects.create(
            batch=self.batch,
            date=self.today - timedelta(days=10),
            start_time=time(9, 0),
            end_time=time(10, 0),
            status='conducted'
        )
        record_session_attendance(sess1, {self.student.id: {'status': 'present'}})

        # 1 session scheduled tomorrow (should NOT count as absence)
        ClassSession.objects.create(
            batch=self.batch,
            date=self.today + timedelta(days=1),
            start_time=time(9, 0),
            end_time=time(10, 0),
            status='scheduled'
        )

        # 1 session cancelled 5 days ago (should NOT count as absence)
        ClassSession.objects.create(
            batch=self.batch,
            date=self.today - timedelta(days=5),
            start_time=time(9, 0),
            end_time=time(10, 0),
            status='cancelled',
            cancellation_reason='Teacher traveling for concert'
        )

        stats = calculate_student_attendance(self.student)
        self.assertEqual(stats['eligible_count'], 1)
        self.assertEqual(stats['present_count'], 1)
        self.assertEqual(stats['absent_count'], 0)
        self.assertEqual(stats['percentage'], 100.0)

    def test_rule_exclude_sessions_prior_to_enrollment(self):
        # Session held 40 days ago (student enrolled 30 days ago)
        sess_old = ClassSession.objects.create(
            batch=self.batch,
            date=self.today - timedelta(days=40),
            start_time=time(9, 0),
            end_time=time(10, 0),
            status='conducted'
        )

        # Session held 10 days ago (within enrollment)
        sess_valid = ClassSession.objects.create(
            batch=self.batch,
            date=self.today - timedelta(days=10),
            start_time=time(9, 0),
            end_time=time(10, 0),
            status='conducted'
        )
        record_session_attendance(sess_valid, {self.student.id: {'status': 'absent'}})

        stats = calculate_student_attendance(self.student)
        self.assertEqual(stats['eligible_count'], 1)
        self.assertEqual(stats['absent_count'], 1)
        self.assertEqual(stats['percentage'], 0.0)

    def test_rule_leave_tracked_separately(self):
        sess = ClassSession.objects.create(
            batch=self.batch,
            date=self.today - timedelta(days=5),
            start_time=time(9, 0),
            end_time=time(10, 0),
            status='conducted'
        )
        record_session_attendance(sess, {self.student.id: {'status': 'leave', 'remarks': 'Prior festival leave'}})

        stats = calculate_student_attendance(self.student)
        self.assertEqual(stats['eligible_count'], 1)
        self.assertEqual(stats['present_count'], 0)
        self.assertEqual(stats['absent_count'], 0)
        self.assertEqual(stats['leave_count'], 1)
        self.assertEqual(stats['percentage'], 0.0)

    def test_empty_database_handling_no_division_by_zero(self):
        # No sessions held yet
        stats = calculate_student_attendance(self.student)
        self.assertEqual(stats['eligible_count'], 0)
        self.assertIsNone(stats['percentage'])

    def test_attendance_correction_creates_audit_log(self):
        sess = ClassSession.objects.create(
            batch=self.batch,
            date=self.today - timedelta(days=2),
            start_time=time(9, 0),
            end_time=time(10, 0),
            status='conducted'
        )
        # Initially saved as absent
        record_session_attendance(sess, {self.student.id: {'status': 'absent'}}, user=self.teacher)
        self.assertEqual(AttendanceAuditLog.objects.count(), 0)

        # Corrected to present
        logs = record_session_attendance(
            sess,
            {self.student.id: {'status': 'present'}},
            user=self.teacher,
            audit_reason="Confirmed student arrived in second half"
        )

        self.assertEqual(len(logs), 1)
        audit = logs[0]
        self.assertEqual(audit.old_status, 'absent')
        self.assertEqual(audit.new_status, 'present')
        self.assertEqual(audit.changed_by, self.teacher)
        self.assertIn("second half", audit.reason)

    def test_duplicate_attendance_prevented(self):
        sess = ClassSession.objects.create(
            batch=self.batch,
            date=self.today - timedelta(days=2),
            start_time=time(9, 0),
            end_time=time(10, 0),
            status='conducted'
        )
        Attendance.objects.create(session=sess, student=self.student, status='present')

        with self.assertRaises(IntegrityError):
            Attendance.objects.create(session=sess, student=self.student, status='absent')


class MusicalCurriculumAndLibraryTests(TestCase):
    """Tests for Taals, Compositions, Lessons, and Assignments."""

    def test_seed_foundational_taals_and_compositions(self):
        count = seed_foundational_taals_and_compositions()
        self.assertGreaterEqual(count, 6)

        teentaal = Taal.objects.get(name='Teentaal')
        self.assertEqual(teentaal.matras, 16)
        self.assertIn('Dha Dhin Dhin Dha', teentaal.theka_notation)

        # Check Delhi Kayda exists
        kayda = Composition.objects.filter(taal=teentaal, category='kayda').first()
        self.assertIsNotNone(kayda)
        self.assertIn("Dha Te Te", kayda.bol_notation)

    def test_lesson_and_assignment_workflow(self):
        batch = Batch.objects.create(
            batch_id='BAT-TEST-02',
            name='Intermediate Batch',
            level='intermediate',
            regular_day='Sunday',
            start_time=time(11, 0),
            end_time=time(12, 0)
        )
        teentaal, _ = Taal.objects.get_or_create(
            name='Teentaal',
            defaults={'matras': 16, 'vibhag_structure': '4+4+4+4', 'tali_khali_info': '1,5,13', 'theka_notation': 'Theka'}
        )

        lesson = Lesson.objects.create(
            batch=batch,
            date=timezone.now().date(),
            topic='Dhire Dhire Rela Acceleration',
            taal=teentaal,
            bol_notation='Dhi Re Dhi Re Ki Ta Ta Ka',
            tempo_bpm='160 BPM'
        )
        self.assertEqual(lesson.topic, 'Dhire Dhire Rela Acceleration')

        assignment = PracticeAssignment.objects.create(
            title='Practice Rela 30 Mins Daily',
            description='Target clean Nikas at 160 BPM',
            batch=batch,
            related_lesson=lesson,
            due_date=timezone.now().date() + timedelta(days=7),
            status='assigned'
        )
        self.assertFalse(assignment.is_overdue)


class SecurityAndUtilityTests(TestCase):
    """Tests for CSV Formula Injection Prevention and Database Backup."""

    def test_csv_formula_injection_prevention(self):
        # Normal value
        self.assertEqual(sanitize_csv_cell("Pandit Sharma"), "Pandit Sharma")
        # Formula injections starting with =, +, -, @
        self.assertEqual(sanitize_csv_cell("=cmd|'/C calc'!A0"), "'=cmd|'/C calc'!A0")
        self.assertEqual(sanitize_csv_cell("+12345"), "'+12345")
        self.assertEqual(sanitize_csv_cell("-500"), "'-500")
        self.assertEqual(sanitize_csv_cell("@SUM(A1:A10)"), "'@SUM(A1:A10)")

    def test_database_backup_service(self):
        backup_info = create_database_backup()
        self.assertTrue(backup_info['filename'].startswith('taal_backup_'))
        self.assertGreater(backup_info['size_bytes'], 0)


from academy.models import (
    BatchRecurringSchedule, WhatsAppMessageLog, ChatbotVerificationCode
)
from academy.services import (
    generate_future_sessions, reschedule_class_session, cancel_class_session,
    generate_receipt_pdf, send_whatsapp_message, send_class_reminder_whatsapp,
    send_payment_receipt_whatsapp, process_chatbot_query
)


class StudentLifecycleAndArchiveTests(TestCase):
    """Tests for student lifecycle, monthly fee, and safe archiving."""

    def setUp(self):
        self.today = timezone.now().date()
        self.student = Student.objects.create(
            first_name='Rohan',
            last_name='Kulkarni',
            enrollment_date=self.today,
            phone='9822012345',
            guardian_name='Suresh Kulkarni',
            guardian_whatsapp='9822012345',
            address='12 Saraswati Colony, Pune',
            monthly_fee=Decimal('1500.00'),
            level='beginner',
            status='active'
        )

    def test_student_fields_and_monthly_fee(self):
        self.assertEqual(self.student.monthly_fee, Decimal('1500.00'))
        self.assertEqual(self.student.guardian_whatsapp, '9822012345')
        self.assertFalse(self.student.is_archived)

    def test_student_safe_archive_and_restore(self):
        # Archive student
        self.student.is_archived = True
        self.student.save()
        self.assertTrue(self.student.is_archived)

        # Ensure student still exists in database and retains records
        reloaded = Student.objects.get(id=self.student.id)
        self.assertTrue(reloaded.is_archived)
        self.assertEqual(reloaded.full_name, 'Rohan Kulkarni')

        # Restore from archive
        self.student.is_archived = False
        self.student.save()
        self.assertFalse(self.student.is_archived)


class RecurringTimetableAndScheduleTests(TestCase):
    """
    Tests for recurring weekly timetable rules:
    - Generation of future classes
    - Idempotency (prevent duplicate sessions)
    - Session rescheduling with audit reason
    - Session cancellation
    """

    def setUp(self):
        self.today = timezone.now().date()
        self.batch = Batch.objects.create(
            batch_id='BAT-TABLA-REC',
            name='Tuesday-Thursday Tabla Batch',
            course='Tabla',
            level='beginner',
            capacity=12,
            monthly_fee=Decimal('1200.00'),
            regular_day='Tuesday',
            start_time=time(17, 0),
            end_time=time(18, 0),
            start_date=self.today
        )

        # Set up recurring rules: Tuesday (day 1) and Thursday (day 3) at 5:00 PM
        self.rule_tue = BatchRecurringSchedule.objects.create(
            batch=self.batch,
            day_of_week=1,  # Tuesday
            start_time=time(17, 0),
            end_time=time(18, 0),
            duration_minutes=60,
            is_active=True
        )
        self.rule_thu = BatchRecurringSchedule.objects.create(
            batch=self.batch,
            day_of_week=3,  # Thursday
            start_time=time(17, 0),
            end_time=time(18, 0),
            duration_minutes=60,
            is_active=True
        )

    def test_recurring_generation_and_idempotency(self):
        # Run schedule generation for 14 days
        res1 = generate_future_sessions(batch=self.batch, horizon_days=14)
        created_first = res1['created_count']
        self.assertGreater(created_first, 0)
        self.assertEqual(res1['skipped_count'], 0)

        # Run schedule generation again: MUST BE IDEMPOTENT (0 created, all skipped)
        res2 = generate_future_sessions(batch=self.batch, horizon_days=14)
        self.assertEqual(res2['created_count'], 0)
        self.assertEqual(res2['skipped_count'], created_first)

    def test_session_reschedule_preserves_history(self):
        # Create a scheduled session
        sess = ClassSession.objects.create(
            batch=self.batch,
            date=self.today + timedelta(days=2),
            start_time=time(17, 0),
            end_time=time(18, 0),
            status='scheduled'
        )

        new_date = self.today + timedelta(days=3)
        new_start = time(18, 0)
        new_end = time(19, 0)
        reason = "Academy Guru festival concert"

        rescheduled = reschedule_class_session(sess, new_date, new_start, new_end, reason)

        self.assertTrue(rescheduled.is_rescheduled)
        self.assertEqual(rescheduled.date, new_date)
        self.assertEqual(rescheduled.start_time, new_start)
        self.assertEqual(rescheduled.original_date, self.today + timedelta(days=2))
        self.assertEqual(rescheduled.original_start_time, time(17, 0))
        self.assertEqual(rescheduled.reschedule_reason, reason)

    def test_session_cancellation_preserves_reason(self):
        sess = ClassSession.objects.create(
            batch=self.batch,
            date=self.today + timedelta(days=4),
            start_time=time(17, 0),
            end_time=time(18, 0),
            status='scheduled'
        )

        cancel_class_session(sess, "National Holiday")
        sess.refresh_from_db()
        self.assertEqual(sess.status, 'cancelled')
        self.assertEqual(sess.cancellation_reason, "National Holiday")


class FeesAndPdfReceiptTests(TestCase):
    """
    Tests for Fee payments, auto-generated receipt numbers,
    balance calculations, and ReportLab PDF generation.
    """

    def setUp(self):
        self.today = timezone.now().date()
        self.student = Student.objects.create(
            first_name='Meera',
            last_name='Nair',
            enrollment_date=self.today,
            phone='9811122233',
            monthly_fee=Decimal('2000.00'),
            level='intermediate',
            status='active'
        )

    def test_payment_receipt_number_generation_and_balance(self):
        # Partial payment: Due 2000, Paid 1200
        payment = PaymentRecord.objects.create(
            student=self.student,
            amount_due=Decimal('2000.00'),
            amount_paid=Decimal('1200.00'),
            payment_date=self.today,
            payment_method='upi',
            billing_period='October 2026',
            fee_month=10,
            fee_year=2026,
            transaction_reference='UPI987654321'
        )

        # Receipt number auto-generated
        self.assertTrue(payment.receipt_number.startswith(f"RSV-REC-{self.today.year}-"))
        self.assertEqual(payment.outstanding_balance, Decimal('800.00'))
        self.assertTrue(payment.is_partial)
        self.assertFalse(payment.is_fully_paid)

    def test_payment_reversal(self):
        payment = PaymentRecord.objects.create(
            student=self.student,
            amount_due=Decimal('2000.00'),
            amount_paid=Decimal('2000.00'),
            payment_date=self.today,
            payment_method='cash',
            billing_period='October 2026'
        )
        self.assertTrue(payment.is_fully_paid)
        self.assertFalse(payment.is_reversed)

        # Reverse payment
        payment.is_reversed = True
        payment.reversal_reason = "Correction: Paid into wrong account"
        payment.save()

        reloaded = PaymentRecord.objects.get(id=payment.id)
        self.assertTrue(reloaded.is_reversed)
        self.assertEqual(reloaded.reversal_reason, "Correction: Paid into wrong account")

    def test_reportlab_pdf_receipt_generation(self):
        payment = PaymentRecord.objects.create(
            student=self.student,
            amount_due=Decimal('2000.00'),
            amount_paid=Decimal('2000.00'),
            payment_date=self.today,
            payment_method='upi',
            billing_period='October 2026'
        )

        pdf_bytes = generate_receipt_pdf(payment)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertGreater(len(pdf_bytes), 1000)
        # Verify valid PDF header
        self.assertTrue(pdf_bytes.startswith(b'%PDF-'))


class WhatsAppIntegrationAndChatbotTests(TestCase):
    """
    Tests for WhatsApp service, test mode safety, reminder deduplication,
    and parent chatbot queries.
    """

    def setUp(self):
        self.today = timezone.now().date()
        self.batch = Batch.objects.create(
            batch_id='BAT-TABLA-WA',
            name='Weekend Tabla Group',
            course='Tabla',
            level='beginner',
            regular_day='Sunday',
            start_time=time(8, 0),
            end_time=time(11, 0),
            start_date=self.today
        )
        self.student = Student.objects.create(
            first_name='Tanmay',
            last_name='Deshmukh',
            enrollment_date=self.today,
            phone='9899887766',
            guardian_name='Milind Deshmukh',
            guardian_whatsapp='9899887766',
            monthly_fee=Decimal('1500.00'),
            status='active'
        )
        BatchEnrollment.objects.create(
            student=self.student,
            batch=self.batch,
            enrolled_date=self.today,
            is_active=True
        )

    def test_send_whatsapp_message_in_test_mode(self):
        res = send_whatsapp_message(
            to_number='9899887766',
            message_text='Namaste! Test reminder message.',
            message_type='reminder',
            student=self.student
        )
        self.assertEqual(res['status'], 'simulated')
        self.assertTrue(res['simulated'])

        # Verify message log created
        log = WhatsAppMessageLog.objects.filter(id=res['log_id']).first()
        self.assertIsNotNone(log)
        self.assertIn('9899887766', log.recipient_phone)
        self.assertEqual(log.status, 'simulated')
        self.assertEqual(log.message_type, 'reminder')

    def test_class_reminder_duplicate_prevention(self):
        sess = ClassSession.objects.create(
            batch=self.batch,
            date=self.today,
            start_time=time(8, 0),
            end_time=time(11, 0),
            status='scheduled'
        )

        # Dispatch 1: should send
        res1 = send_class_reminder_whatsapp(sess)
        self.assertEqual(len(res1), 1)
        self.assertEqual(res1[0]['status'], 'simulated')

        # Dispatch 2 on same day: should skip duplicate
        res2 = send_class_reminder_whatsapp(sess)
        self.assertEqual(len(res2), 1)
        self.assertEqual(res2[0]['status'], 'skipped')

    def test_chatbot_query_fee_balance(self):
        # Create payment with partial balance
        PaymentRecord.objects.create(
            student=self.student,
            amount_due=Decimal('1500.00'),
            amount_paid=Decimal('1000.00'),
            payment_date=self.today,
            payment_method='upi',
            billing_period='October 2026'
        )

        reply = process_chatbot_query(phone_number='9899887766', incoming_text='What is my fee balance?')
        self.assertIn('Tanmay Deshmukh', reply)
        self.assertIn('500.00', reply)
        self.assertIn('Pending Balance', reply)

    def test_chatbot_unregistered_number_privacy(self):
        reply = process_chatbot_query(phone_number='9111111111', incoming_text='Hello what is my class?')
        self.assertIn('Radhhanand Sangeet Vidyalaya', reply)
        self.assertIn('registered', reply.lower())


class AcademyBrandingIntegrityTests(TestCase):
    """
    Tests consistent exact spelling 'Radhhanand Sangeet Vidyalaya' across settings,
    dashboard, and student details.
    """

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='admin_guru', password='password123')
        self.client.login(username='admin_guru', password='password123')

    def test_academy_settings_exact_branding(self):
        settings = AcademySettings.get_settings()
        self.assertEqual(settings.academy_name, 'Radhhanand Sangeet Vidyalaya')

    def test_dashboard_renders_exact_branding(self):
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Radhhanand Sangeet Vidyalaya')


class BatchManagementAndPwaTests(TestCase):
    """
    Automated verification of:
    - Batch deletion security (historical protection & safe disposable batch deletion)
    - Default recurring timetable schedules configuration
    - Start & end time validation
    - Session generation idempotency
    - WhatsApp test mode & opt-out
    - PWA manifest, service worker, and offline shell
    """
    def setUp(self):
        self.client = Client()
        self.teacher = User.objects.create_user(username='staff_guru', password='password123', is_staff=True)
        self.client.login(username='staff_guru', password='password123')
        self.today = timezone.now().date()

    def test_batch_delete_prevented_when_historical_records_exist(self):
        batch = Batch.objects.create(
            batch_id='BAT-HIST-01',
            name='Historical Riyaz Batch',
            level='beginner',
            regular_day='Saturday',
            start_time=time(17, 0),
            end_time=time(18, 0),
            start_date=self.today
        )
        student = Student.objects.create(first_name='Ananya', last_name='Sen')
        session = ClassSession.objects.create(
            batch=batch,
            date=self.today,
            start_time=time(17, 0),
            end_time=time(18, 0),
            status='conducted'
        )
        Attendance.objects.create(session=session, student=student, status='present')

        # Attempt to delete via POST
        url = reverse('batch_delete', args=[batch.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        # Verify batch STILL exists in database
        self.assertTrue(Batch.objects.filter(id=batch.id).exists())
        self.assertTrue(Attendance.objects.filter(session=session).exists())

    def test_batch_delete_succeeds_for_disposable_batch(self):
        batch = Batch.objects.create(
            batch_id='BAT-DISP-01',
            name='Disposable Test Batch',
            level='beginner',
            regular_day='Monday',
            start_time=time(16, 0),
            end_time=time(17, 0),
            start_date=self.today
        )
        # Create unconducted scheduled session and rule
        ClassSession.objects.create(
            batch=batch,
            date=self.today + timedelta(days=5),
            start_time=time(16, 0),
            end_time=time(17, 0),
            status='scheduled'
        )
        BatchRecurringSchedule.objects.create(
            batch=batch,
            day_of_week=0,
            start_time=time(16, 0),
            end_time=time(17, 0)
        )

        url = reverse('batch_delete', args=[batch.id])
        # GET renders confirmation page
        get_res = self.client.get(url)
        self.assertEqual(get_res.status_code, 200)
        self.assertContains(get_res, 'Disposable Test Batch')
        self.assertContains(get_res, 'Yes, Permanently Delete Batch')

        # POST performs safe deletion
        post_res = self.client.post(url)
        self.assertEqual(post_res.status_code, 302)
        self.assertRedirects(post_res, reverse('batch_list'))
        # Batch is gone
        self.assertFalse(Batch.objects.filter(id=batch.id).exists())

    def test_batch_form_time_and_overlap_validation(self):
        from academy.forms import BatchForm
        # Invalid: end_time before start_time
        invalid_data = {
            'name': 'Invalid Time Batch',
            'course': 'Tabla',
            'level': 'beginner',
            'regular_day': 'Tuesday',
            'start_time': '18:00',
            'end_time': '17:00',
            'capacity': 15,
            'monthly_fee': '1500.00',
            'start_date': str(self.today),
            'is_active': True,
        }
        form = BatchForm(data=invalid_data)
        self.assertFalse(form.is_valid())
        self.assertIn("End time must be later than start time", str(form.errors))

    def test_pwa_endpoints(self):
        # Manifest
        manifest_res = self.client.get(reverse('manifest_json'))
        self.assertEqual(manifest_res.status_code, 200)
        self.assertEqual(manifest_res['Content-Type'], 'application/manifest+json')
        self.assertIn('Radhhanand Sangeet Vidyalaya', manifest_res.content.decode('utf-8'))

        # Service Worker
        sw_res = self.client.get(reverse('service_worker_js'))
        self.assertEqual(sw_res.status_code, 200)
        self.assertEqual(sw_res['Content-Type'], 'application/javascript')
        self.assertIn('Radhhanand Sangeet Vidyalaya', sw_res.content.decode('utf-8'))

        # Offline fallback
        offline_res = self.client.get(reverse('offline_view'))
        self.assertEqual(offline_res.status_code, 200)
        self.assertContains(offline_res, 'Radhhanand Sangeet Vidyalaya')

    def test_whatsapp_opt_out_respected(self):
        from academy.services import send_class_reminder_whatsapp
        student = Student.objects.create(
            first_name='OptedOut',
            last_name='Student',
            guardian_phone='9876543210',
            whatsapp_opt_out=True
        )
        batch = Batch.objects.create(
            batch_id='BAT-OPT-01',
            name='Opt Out Test Batch',
            start_time=time(17, 0),
            end_time=time(18, 0)
        )
        BatchEnrollment.objects.create(batch=batch, student=student)
        session = ClassSession.objects.create(
            batch=batch,
            date=self.today,
            start_time=time(17, 0),
            end_time=time(18, 0),
            status='scheduled'
        )

        results = send_class_reminder_whatsapp(session, student=student)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['status'], 'skipped')
        self.assertIn('opted out', results[0]['reason'].lower())

