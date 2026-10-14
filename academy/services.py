import csv
import io
import shutil
import os
import requests
from datetime import date, datetime, timedelta
from decimal import Decimal
from django.conf import settings
from django.db import transaction
from django.db.models import Q, Sum, Count
from django.utils import timezone
from .models import (
    AcademySettings, Student, Batch, BatchEnrollment, BatchRecurringSchedule,
    ClassSession, Attendance, AttendanceAuditLog,
    Taal, Composition, Lesson, PracticeAssignment,
    PaymentRecord, AcademyAlert, WhatsAppMessageLog, ChatbotVerificationCode
)



# ==============================================================================
# ATTENDANCE CALCULATION SERVICE
# ==============================================================================

def get_student_eligible_sessions(student, start_date=None, end_date=None, batch=None):
    """
    Returns QuerySet of conducted class sessions for which the student was eligible.
    Eligibility Rules:
    1. Session status must be 'conducted'. (Scheduled and Cancelled are NEVER counted)
    2. Session date must be >= student.enrollment_date.
    3. Session date must be <= current date (future sessions never counted).
    4. Student must have had an enrollment in the session's batch covering the session date:
       enrolled_date <= session.date and (left_date is None or left_date >= session.date).
    5. Respect optional date filters and batch filter.
    """
    today = timezone.now().date()

    # Get active/past enrollments for student
    enrollments_qs = BatchEnrollment.objects.filter(student=student)
    if batch:
        enrollments_qs = enrollments_qs.filter(batch=batch)

    # Base conducted sessions
    sessions_qs = ClassSession.objects.filter(
        status='conducted',
        date__gte=student.enrollment_date,
        date__lte=today
    )

    if start_date:
        sessions_qs = sessions_qs.filter(date__gte=start_date)
    if end_date:
        sessions_qs = sessions_qs.filter(date__lte=end_date)
    if batch:
        sessions_qs = sessions_qs.filter(batch=batch)

    # Filter sessions where an enrollment was valid on that session's date
    eligible_session_ids = []
    for s in sessions_qs.select_related('batch'):
        is_enrolled_on_date = enrollments_qs.filter(
            batch=s.batch,
            enrolled_date__lte=s.date
        ).filter(
            Q(left_date__isnull=True) | Q(left_date__gte=s.date)
        ).exists()
        if is_enrolled_on_date:
            eligible_session_ids.append(s.id)

    return ClassSession.objects.filter(id__in=eligible_session_ids).order_by('-date', '-start_time')


def calculate_student_attendance(student, start_date=None, end_date=None, batch=None):
    """
    Calculates detailed and summary attendance metrics for an individual student.
    Formula: Attendance % = (Present Sessions / Eligible Conducted Sessions) * 100
    If Late status is enabled, Late counts towards present or separate per settings.
    """
    academy_settings = AcademySettings.get_settings()
    eligible_sessions = get_student_eligible_sessions(student, start_date, end_date, batch)
    eligible_count = eligible_sessions.count()

    attendances = Attendance.objects.filter(
        student=student,
        session__in=eligible_sessions
    ).select_related('session', 'session__batch')

    att_map = {att.session_id: att for att in attendances}

    present_count = 0
    absent_count = 0
    leave_count = 0
    late_count = 0

    session_records = []
    # Loop ordered chronologically or reverse
    for session in eligible_sessions:
        att = att_map.get(session.id)
        status = att.status if att else 'absent'  # conducted with no record defaults to absent
        remarks = att.remarks if att else ''

        if status == 'present':
            present_count += 1
        elif status == 'absent':
            absent_count += 1
        elif status == 'leave':
            leave_count += 1
        elif status == 'late':
            late_count += 1
            if not academy_settings.enable_late_status:
                # If late is not enabled, treat as present
                present_count += 1

        session_records.append({
            'session': session,
            'status': status,
            'remarks': remarks,
            'attendance': att
        })

    # Attendance percentage
    if eligible_count > 0:
        # If late is enabled, late counts as partial or present depending on academy rule
        effective_present = present_count + (late_count if academy_settings.enable_late_status else 0)
        percentage = round((effective_present / eligible_count) * 100, 1)
    else:
        percentage = None  # No eligible sessions

    # Calculate consecutive absences from most recent conducted sessions backwards
    consecutive_absences = 0
    for record in session_records:
        if record['status'] == 'absent':
            consecutive_absences += 1
        else:
            break

    return {
        'student': student,
        'eligible_count': eligible_count,
        'present_count': present_count,
        'absent_count': absent_count,
        'leave_count': leave_count,
        'late_count': late_count,
        'percentage': percentage,
        'consecutive_absences': consecutive_absences,
        'records': session_records,
    }


def calculate_batch_attendance(batch, start_date=None, end_date=None):
    """
    Computes overall attendance statistics for a batch and breakdown for each enrolled student.
    """
    today = timezone.now().date()
    sessions = batch.sessions.filter(status='conducted', date__lte=today)
    if start_date:
        sessions = sessions.filter(date__gte=start_date)
    if end_date:
        sessions = sessions.filter(date__lte=end_date)

    conducted_count = sessions.count()
    enrollments = batch.enrollments.filter(is_active=True).select_related('student')

    student_summaries = []
    total_eligible_slots = 0
    total_present_slots = 0

    for enr in enrollments:
        student = enr.student
        stats = calculate_student_attendance(student, start_date, end_date, batch=batch)
        student_summaries.append(stats)
        total_eligible_slots += stats['eligible_count']
        total_present_slots += stats['present_count']

    batch_percentage = (
        round((total_present_slots / total_eligible_slots) * 100, 1)
        if total_eligible_slots > 0 else None
    )

    return {
        'batch': batch,
        'conducted_sessions_count': conducted_count,
        'enrolled_students_count': enrollments.count(),
        'total_eligible_slots': total_eligible_slots,
        'total_present_slots': total_present_slots,
        'batch_percentage': batch_percentage,
        'student_summaries': student_summaries,
    }


# ==============================================================================
# AUDIT AND ATTENDANCE RECORDING
# ==============================================================================

@transaction.atomic
def record_session_attendance(session, attendance_data, user=None, audit_reason=""):
    """
    Saves or updates attendance for a session while creating audit logs for any modified statuses.
    attendance_data format: dict mapping student_id (int) -> {'status': str, 'remarks': str}
    """
    logs_created = []
    for student_id, data in attendance_data.items():
        status = data.get('status', 'present')
        remarks = data.get('remarks', '').strip()

        try:
            student = Student.objects.get(id=student_id)
        except Student.DoesNotExist:
            continue

        existing_att = Attendance.objects.filter(session=session, student=student).first()

        if existing_att:
            old_status = existing_att.status
            if old_status != status or existing_att.remarks != remarks:
                # Create Audit record if status changed
                if old_status != status:
                    log = AttendanceAuditLog.objects.create(
                        session=session,
                        student=student,
                        old_status=old_status,
                        new_status=status,
                        changed_by=user,
                        reason=audit_reason or "Attendance updated by teacher"
                    )
                    logs_created.append(log)
                existing_att.status = status
                existing_att.remarks = remarks
                existing_att.marked_by = user
                existing_att.save()
        else:
            Attendance.objects.create(
                session=session,
                student=student,
                status=status,
                remarks=remarks,
                marked_by=user
            )

    return logs_created


# ==============================================================================
# ALERTS & NOTIFICATIONS ENGINE
# ==============================================================================

def refresh_academy_alerts():
    """
    Scans data and populates internal academy alerts for the teacher dashboard.
    Clears obsolete non-dismissed alerts and adds fresh flags.
    """
    settings_obj = AcademySettings.get_settings()
    today = timezone.now().date()

    # 1. Unrecorded conducted sessions (conducted sessions with zero saved attendance)
    conducted_unrecorded = ClassSession.objects.filter(
        status='conducted',
        date__lte=today,
        attendances__isnull=True
    ).distinct()

    for s in conducted_unrecorded:
        title = f"Attendance pending for {s.batch.name} on {s.date}"
        if not AcademyAlert.objects.filter(alert_type='unrecorded_session', title=title, is_dismissed=False).exists():
            AcademyAlert.objects.create(
                alert_type='unrecorded_session',
                title=title,
                message=f"Session for batch '{s.batch.name}' held on {s.date} is marked conducted but attendance has not been saved.",
                severity='warning',
                link=f"/attendance/mark/{s.id}/"
            )

    # 2. Check active students for low attendance or consecutive absences
    active_students = Student.objects.filter(status='active')
    for student in active_students:
        stats = calculate_student_attendance(student)

        # Low attendance alert
        if stats['percentage'] is not None and stats['percentage'] < settings_obj.attendance_threshold:
            title = f"Low Attendance: {student.full_name} ({stats['percentage']}%)"
            if not AcademyAlert.objects.filter(alert_type='attendance_low', title=title, is_dismissed=False).exists():
                AcademyAlert.objects.create(
                    alert_type='attendance_low',
                    title=title,
                    message=f"{student.full_name} has attended {stats['present_count']} of {stats['eligible_count']} eligible conducted classes ({stats['percentage']}%), falling below your threshold of {settings_obj.attendance_threshold}%.",
                    severity='warning',
                    link=f"/students/{student.id}/"
                )

        # Consecutive absences alert
        if stats['consecutive_absences'] >= settings_obj.consecutive_absence_threshold:
            title = f"{student.full_name}: {stats['consecutive_absences']} Consecutive Absences"
            if not AcademyAlert.objects.filter(alert_type='consecutive_absence', title=title, is_dismissed=False).exists():
                AcademyAlert.objects.create(
                    alert_type='consecutive_absence',
                    title=title,
                    message=f"{student.full_name} has missed {stats['consecutive_absences']} consecutive conducted classes.",
                    severity='danger',
                    link=f"/students/{student.id}/"
                )

    # 3. Overdue practice assignments
    overdue_assignments = PracticeAssignment.objects.filter(
        status__in=['assigned', 'needs_practice'],
        due_date__lt=today
    )
    for pa in overdue_assignments[:10]:
        title = f"Overdue Homework: {pa.title}"
        if not AcademyAlert.objects.filter(alert_type='overdue_assignment', title=title, is_dismissed=False).exists():
            AcademyAlert.objects.create(
                alert_type='overdue_assignment',
                title=title,
                message=f"Assignment '{pa.title}' was due on {pa.due_date}.",
                severity='info',
                link=f"/assignments/{pa.id}/edit/"
            )


# ==============================================================================
# SECURE CSV EXPORT WITH FORMULA INJECTION PREVENTION
# ==============================================================================

def sanitize_csv_cell(value):
    """
    Prevents CSV Formula Injection (CWE-1236).
    If a cell starts with '=', '+', '-', or '@', prepend with a single quote.
    """
    if value is None:
        return ""
    str_val = str(value)
    if str_val and str_val[0] in ('=', '+', '-', '@', '\t', '\r'):
        return f"'{str_val}"
    return str_val


def generate_safe_csv_response(filename_prefix, headers, data_rows):
    """
    Generates a safe CSV file response object with formula injection protections.
    """
    from django.http import HttpResponse

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    today_str = timezone.now().strftime('%Y%m%d')
    filename = f"{filename_prefix}_{today_str}.csv"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    writer.writerow([sanitize_csv_cell(h) for h in headers])

    for row in data_rows:
        writer.writerow([sanitize_csv_cell(cell) for cell in row])

    return response


# ==============================================================================
# SAFE DATABASE BACKUP MANAGEMENT
# ==============================================================================

def create_database_backup():
    """
    Creates a timestamped copy of the active SQLite database file in the configured BACKUPS_DIR.
    Returns metadata dict on success or raises an exception.
    """
    db_path = settings.DATABASES['default']['NAME']
    backups_dir = settings.BACKUPS_DIR
    os.makedirs(backups_dir, exist_ok=True)

    timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
    backup_filename = f"taal_backup_{timestamp}.sqlite3"
    backup_filepath = os.path.join(backups_dir, backup_filename)

    # If physical file exists on disk, copy it directly
    if isinstance(db_path, (str, os.PathLike)) and os.path.exists(db_path):
        shutil.copy2(db_path, backup_filepath)
    else:
        # For in-memory test databases, export via sqlite3 iterdump
        from django.db import connection
        with open(backup_filepath, 'w', encoding='utf-8') as f:
            for line in connection.connection.iterdump():
                f.write(f"{line}\n")

    file_size_bytes = os.path.getsize(backup_filepath)

    return {
        'filename': backup_filename,
        'filepath': backup_filepath,
        'size_bytes': file_size_bytes,
        'size_kb': round(file_size_bytes / 1024, 2),
        'created_at': timezone.now(),
    }



def list_database_backups():
    """
    Returns list of all available backups in the backups directory sorted by creation time descending.
    """
    backups_dir = settings.BACKUPS_DIR
    if not os.path.exists(backups_dir):
        return []

    backups = []
    for fname in os.listdir(backups_dir):
        if fname.endswith('.sqlite3') or fname.endswith('.db'):
            fpath = os.path.join(backups_dir, fname)
            stat = os.stat(fpath)
            backups.append({
                'filename': fname,
                'size_kb': round(stat.st_size / 1024, 2),
                'modified_time': datetime.fromtimestamp(stat.st_mtime, tz=timezone.get_current_timezone()),
            })

    backups.sort(key=lambda x: x['modified_time'], reverse=True)
    return backups


# ==============================================================================
# PREPOPULATE FOUNDATIONAL TABLA DATA (TAALS & COMPOSITIONS)
# ==============================================================================

def seed_foundational_taals_and_compositions():
    """
    Seeds essential traditional Indian classical Taals and foundational compositions.
    Idempotent: skips existing entries by name.
    """
    taals_data = [
        {
            'name': 'Teentaal',
            'matras': 16,
            'vibhag_structure': '4 + 4 + 4 + 4',
            'tali_khali_info': 'Tali on 1 (Sam), 5, 13; Khali on 9',
            'theka_notation': 'Dha Dhin Dhin Dha | Dha Dhin Dhin Dha | Dha Tin Tin Ta | Ta Dhin Dhin Dha',
            'level': 'beginner',
            'notes': 'The king of rhythmic cycles in North Indian classical music (Hindustani sangeet). Foundational for Riyaz and solo presentations.'
        },
        {
            'name': 'Jhaptaal',
            'matras': 10,
            'vibhag_structure': '2 + 3 + 2 + 3',
            'tali_khali_info': 'Tali on 1 (Sam), 3, 8; Khali on 6',
            'theka_notation': 'Dhi Na | Dhi Dhi Na | Ti Na | Dhi Dhi Na',
            'level': 'intermediate',
            'notes': 'Prominent 10-beat cycle with Khanda chhanda. Extensively used in vocal Khyal and classical solo.'
        },
        {
            'name': 'Ektaal',
            'matras': 12,
            'vibhag_structure': '2 + 2 + 2 + 2 + 2 + 2',
            'tali_khali_info': 'Tali on 1, 5, 9, 11; Khali on 3, 7',
            'theka_notation': 'Dhin Dhin | DhaGe Tirakita | Tu Na | Kat Ta | DhaGe Tirakita | Dhi Na',
            'level': 'intermediate',
            'notes': 'Symmetrical 12-beat taal popular for Vilambit (slow) and Drut (fast) khyal accompaniment as well as solo.'
        },
        {
            'name': 'Rupak',
            'matras': 7,
            'vibhag_structure': '3 + 2 + 2',
            'tali_khali_info': 'Khali on 1 (Sam treated as Khali/Tali convention); Tali on 4, 6',
            'theka_notation': 'Tin Tin Na | Dhi Na | Dhi Na',
            'level': 'intermediate',
            'notes': 'Unique cycle starting on Khali. Essential for vocal, sitar/sarod, and semi-classical accompaniment.'
        },
        {
            'name': 'Keharwa',
            'matras': 8,
            'vibhag_structure': '4 + 4',
            'tali_khali_info': 'Tali on 1 (Sam); Khali on 5',
            'theka_notation': 'Dha Ge Na Ti | Na Ka Dhi Na',
            'level': 'beginner',
            'notes': 'Very popular 8-beat taal for Bhajans, Ghazals, Folk music, and light classical accompaniment.'
        },
        {
            'name': 'Dadra',
            'matras': 6,
            'vibhag_structure': '3 + 3',
            'tali_khali_info': 'Tali on 1 (Sam); Khali on 4',
            'theka_notation': 'Dha Dhi Na | Dha Tu Na',
            'level': 'beginner',
            'notes': 'Lively 6-beat cycle common in Thumri, Dadra, and devotional music.'
        },
    ]

    created_taals = {}
    for td in taals_data:
        taal_obj, _ = Taal.objects.get_or_create(
            name=td['name'],
            defaults=td
        )
        created_taals[td['name']] = taal_obj

    # Seed basic compositions
    teentaal = created_taals.get('Teentaal')
    if teentaal and not Composition.objects.filter(taal=teentaal).exists():
        compositions_data = [
            {
                'title': 'Dha TeTe Dha TeTe DhaGeNaTi Basic Kayda (Delhi Gharana)',
                'taal': teentaal,
                'category': 'kayda',
                'difficulty': 'beginner',
                'recommended_tempo': 'Vilambit to Madhya (80 - 120 BPM)',
                'bol_notation': (
                    "Theme (Mukh): \n"
                    "Dha Te Te Dha Te Te | Dha Ge Na Ti Ta Ke |\n"
                    "Ta Te Te Ta Te Te | Dha Ge Na Ti Dha Dha ||\n\n"
                    "Palta 1 (Double Dha TeTe):\n"
                    "Dha Te Te Dha Te Te | Dha Te Te Dha Te Te |\n"
                    "Dha Te Te Dha Te Te | Dha Ge Na Ti Ta Ke |\n"
                    "Ta Te Te Ta Te Te | Ta Te Te Ta Te Te |\n"
                    "Dha Te Te Dha Te Te | Dha Ge Na Ti Dha Dha ||\n\n"
                    "Tihai:\n"
                    "Dha Te Te Dha Ge Na Ti | Dha - S - S |\n"
                    "Dha Te Te Dha Ge Na Ti | Dha - S - S |\n"
                    "Dha Te Te Dha Ge Na Ti | Dha (Sam) ||"
                ),
                'practice_instructions': 'Ensure clear separation between Daya (Chanti) and Baya (Dagga). Keep TeTe crisp with middle and index finger.'
            },
            {
                'title': 'Dhire Dhire Kitataka Delhi Rela',
                'taal': teentaal,
                'category': 'rela',
                'difficulty': 'intermediate',
                'recommended_tempo': 'Madhya to Drut (160 - 240 BPM)',
                'bol_notation': (
                    "Dhi Re Dhi Re Ki Ta Ta Ka | Dhi Re Dhi Re Ki Ta Ta Ka |\n"
                    "Ti Re Ti Re Ki Ta Ta Ka | Dhi Re Dhi Re Ki Ta Ta Ka ||"
                ),
                'practice_instructions': 'Focus on wrist balance and steady stamina. Gradually accelerate by 10 BPM increments.'
            },
            {
                'title': 'Traditional Farrukhabad Tukda',
                'taal': teentaal,
                'category': 'tukda',
                'difficulty': 'intermediate',
                'recommended_tempo': 'Madhya Laya (120 BPM)',
                'bol_notation': (
                    "DhaGeTirakita DhaGeNaTi | KatTa GadiGhene Dha - |\n"
                    "KatTa GadiGhene Dha - | KatTa GadiGhene Dha || (Sam)"
                ),
                'practice_instructions': 'Crisp Nikas on GadiGhene with distinct open bayan resonance.'
            },
            {
                'title': 'Damdar Tihai in Teentaal',
                'taal': teentaal,
                'category': 'tihai',
                'difficulty': 'beginner',
                'recommended_tempo': 'Madhya Laya',
                'bol_notation': (
                    "Dha Tit Ki Ta Tak Dha (S) | Dha Tit Ki Ta Tak Dha (S) | Dha Tit Ki Ta Tak Dha (Sam) ||"
                ),
                'practice_instructions': 'Maintain exact rest (Dam) of 1 matra between the three phrases.'
            }
        ]
        for comp in compositions_data:
            Composition.objects.get_or_create(
                title=comp['title'],
                taal=comp['taal'],
                defaults=comp
            )

    return len(created_taals)


# ==============================================================================
# AUTOMATIC RECURRING TIMETABLE GENERATION
# ==============================================================================

def generate_future_sessions(batch=None, start_date=None, end_date=None, horizon_days=60):
    """
    Generates future class sessions automatically from BatchRecurringSchedule rules.
    - Idempotent: repeated runs never create duplicate sessions.
    - Safe: completed/conducted, cancelled, and customized sessions are NEVER overwritten.
    - Horizon: generates from start_date (default today) through end_date (default start_date + horizon_days).
    - Conflict check: returns list of warnings if time conflicts exist.
    """
    today = timezone.now().date()
    if not start_date:
        start_date = today
    if not end_date:
        end_date = start_date + timedelta(days=horizon_days)

    batches = [batch] if batch else Batch.objects.filter(is_active=True, is_archived=False)

    created_sessions = []
    skipped_existing_count = 0
    conflicts = []

    # Map weekday integer (0=Mon, 1=Tue, ..., 6=Sun)
    for b in batches:
        rules = b.recurring_schedules.filter(is_active=True)
        if not rules.exists():
            # If no recurring schedule rules, check if regular_day exists
            day_map = {'Monday': 0, 'Tuesday': 1, 'Wednesday': 2, 'Thursday': 3, 'Friday': 4, 'Saturday': 5, 'Sunday': 6}
            if b.regular_day in day_map:
                dur = int((b.end_time.hour * 60 + b.end_time.minute) - (b.start_time.hour * 60 + b.start_time.minute))
                if dur <= 0:
                    dur = 60
                rule, _ = BatchRecurringSchedule.objects.get_or_create(
                    batch=b,
                    day_of_week=day_map[b.regular_day],
                    start_time=b.start_time,
                    defaults={'end_time': b.end_time, 'duration_minutes': dur, 'is_active': True}
                )
                rules = [rule]

        for rule in rules:
            cur_date = start_date
            while cur_date <= end_date:
                if cur_date.weekday() == rule.day_of_week:
                    # Check if session exists on this date & start_time
                    existing = ClassSession.objects.filter(
                        batch=b,
                        date=cur_date,
                        start_time=rule.start_time
                    ).first()

                    if existing:
                        skipped_existing_count += 1
                    else:
                        # Conflict check: does another batch have a session at the exact same date & start_time?
                        other_session = ClassSession.objects.filter(
                            date=cur_date,
                            start_time=rule.start_time
                        ).exclude(batch=b).first()
                        if other_session:
                            conflicts.append(
                                f"Notice: On {cur_date.strftime('%d %b %Y')}, {b.name} and {other_session.batch.name} both have sessions at {rule.start_time.strftime('%I:%M %p')}."
                            )

                        new_session = ClassSession.objects.create(
                            batch=b,
                            schedule_rule=rule,
                            date=cur_date,
                            start_time=rule.start_time,
                            end_time=rule.end_time,
                            status='scheduled'
                        )
                        created_sessions.append(new_session)

                cur_date += timedelta(days=1)

    return {
        'created_count': len(created_sessions),
        'skipped_count': skipped_existing_count,
        'conflicts': list(set(conflicts)),
        'start_date': start_date,
        'end_date': end_date,
    }


def reschedule_class_session(session, new_date, new_start_time, new_end_time, reason=""):
    """
    Safely reschedules an individual class session, preserving original audit history.
    """
    if not session.is_rescheduled:
        session.original_date = session.date
        session.original_start_time = session.start_time

    session.date = new_date
    session.start_time = new_start_time
    session.end_time = new_end_time
    session.is_rescheduled = True
    session.reschedule_reason = reason
    session.status = 'scheduled'
    session.save()
    return session


def cancel_class_session(session, reason):
    """
    Safely cancels a class session with a recorded reason without deleting historical records.
    """
    session.status = 'cancelled'
    session.cancellation_reason = reason
    session.save()
    return session


# ==============================================================================
# PROFESSIONAL PDF RECEIPT GENERATOR (ReportLab)
# ==============================================================================

def generate_receipt_pdf(payment):
    """
    Generates a high-quality professional PDF e-receipt for Radhhanand Sangeet Vidyalaya.
    Includes academy branding, receipt number, student info, amount received in ₹,
    remaining balance, payment method, and signature block.
    Returns bytes.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib import colors

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4  # 595.27 x 841.89 points

    settings_obj = AcademySettings.get_settings()
    academy_name = "Radhhanand Sangeet Vidyalaya"
    teacher_name = settings_obj.teacher_name or "Guru Ji"
    contact_phone = settings_obj.phone or "+91 98765 43210"
    contact_email = settings_obj.email or "contact@radhhanand.org"
    academy_address = settings_obj.address or "Radhhanand Sangeet Vidyalaya, India"

    # Decorative Maroon border
    maroon = colors.HexColor("#7A1C2C")
    gold = colors.HexColor("#C69214")
    dark = colors.HexColor("#27211E")
    ivory_bg = colors.HexColor("#FDFBF7")
    light_gray = colors.HexColor("#F2EFE9")

    # Outer border
    p.setStrokeColor(maroon)
    p.setLineWidth(2.5)
    p.rect(25, 25, width - 50, height - 50)
    p.setStrokeColor(gold)
    p.setLineWidth(1)
    p.rect(29, 29, width - 58, height - 58)

    # Top Header Background banner
    p.setFillColor(maroon)
    p.rect(30, height - 125, width - 60, 94, fill=1, stroke=0)

    # Academy Title in Header
    p.setFillColor(colors.white)
    p.setFont("Helvetica-Bold", 22)
    p.drawCentredString(width / 2, height - 62, academy_name)

    p.setFont("Helvetica-Oblique", 11)
    p.drawCentredString(width / 2, height - 80, "Tabla Class & Indian Classical Music Academy")

    p.setFont("Helvetica", 9)
    p.drawCentredString(width / 2, height - 98, f"Phone: {contact_phone}  |  Email: {contact_email}")
    p.drawCentredString(width / 2, height - 112, academy_address)

    # Receipt Title Box
    p.setFillColor(gold)
    p.rect(width / 2 - 120, height - 155, 240, 24, fill=1, stroke=0)
    p.setFillColor(dark)
    p.setFont("Helvetica-Bold", 12)
    p.drawCentredString(width / 2, height - 148, "OFFICIAL FEE E-RECEIPT")

    # Metadata Grid (Receipt No & Date)
    y = height - 190
    p.setFont("Helvetica-Bold", 10)
    p.setFillColor(dark)
    p.drawString(45, y, "Receipt No:")
    p.setFont("Helvetica-Bold", 11)
    p.setFillColor(maroon)
    p.drawString(120, y, payment.receipt_number or "RSV-REC-TEMP")

    p.setFont("Helvetica-Bold", 10)
    p.setFillColor(dark)
    p.drawString(380, y, "Payment Date:")
    p.setFont("Helvetica", 10)
    pay_date_str = payment.payment_date.strftime('%d %B %Y') if payment.payment_date else timezone.now().strftime('%d %B %Y')
    p.drawString(470, y, pay_date_str)

    y -= 10
    p.setStrokeColor(colors.HexColor("#D5CEC5"))
    p.setLineWidth(0.8)
    p.line(45, y, width - 45, y)

    # Student Details Section
    y -= 25
    p.setFillColor(light_gray)
    p.rect(45, y - 55, width - 90, 70, fill=1, stroke=0)

    p.setFillColor(dark)
    p.setFont("Helvetica-Bold", 10)
    p.drawString(55, y, "Student Name:")
    p.setFont("Helvetica-Bold", 11)
    p.drawString(150, y, payment.student.full_name)

    p.setFont("Helvetica-Bold", 10)
    p.drawString(380, y, "Student ID:")
    p.setFont("Helvetica", 10)
    p.drawString(450, y, payment.student.student_id)

    y -= 20
    active_batch = payment.student.enrollments.filter(is_active=True).first()
    batch_name = active_batch.batch.name if active_batch else "Regular Tabla Batch"
    p.setFont("Helvetica-Bold", 10)
    p.drawString(55, y, "Course / Batch:")
    p.setFont("Helvetica", 10)
    p.drawString(150, y, batch_name[:38])

    p.setFont("Helvetica-Bold", 10)
    p.drawString(380, y, "Guardian:")
    p.setFont("Helvetica", 10)
    p.drawString(450, y, (payment.student.guardian_name or "Parent")[:20])

    y -= 20
    p.setFont("Helvetica-Bold", 10)
    p.drawString(55, y, "Fee Period:")
    p.setFont("Helvetica", 10)
    p.drawString(150, y, payment.billing_period or "Current Term")

    p.setFont("Helvetica-Bold", 10)
    p.drawString(380, y, "Payment Mode:")
    p.setFont("Helvetica", 10)
    p.drawString(465, y, payment.get_payment_method_display())

    # Payment Breakdown Table
    y -= 45
    p.setFillColor(maroon)
    p.rect(45, y, width - 90, 22, fill=1, stroke=0)
    p.setFillColor(colors.white)
    p.setFont("Helvetica-Bold", 10)
    p.drawString(55, y + 6, "Fee Particulars / Description")
    p.drawRightString(width - 55, y + 6, "Amount (INR)")

    # Row 1: Amount Due
    y -= 25
    p.setFillColor(dark)
    p.setFont("Helvetica", 10)
    p.drawString(55, y + 5, f"Tuition Fee for {payment.billing_period or 'Selected Period'}")
    p.setFont("Helvetica-Bold", 10)
    p.drawRightString(width - 55, y + 5, f"₹ {payment.amount_due:,.2f}")
    p.setStrokeColor(colors.HexColor("#E5E0D8"))
    p.line(45, y, width - 45, y)

    # Row 2: Amount Received
    y -= 25
    p.setFillColor(colors.HexColor("#1A6B35"))
    p.setFont("Helvetica-Bold", 11)
    p.drawString(55, y + 5, "AMOUNT RECEIVED")
    p.drawRightString(width - 55, y + 5, f"₹ {payment.amount_paid:,.2f}")
    p.setStrokeColor(maroon)
    p.setLineWidth(1)
    p.line(45, y, width - 45, y)

    # Row 3: Outstanding Balance
    y -= 25
    balance = payment.outstanding_balance
    p.setFillColor(colors.HexColor("#B3261E") if balance > 0 else colors.HexColor("#1A6B35"))
    p.setFont("Helvetica-Bold", 10)
    p.drawString(55, y + 5, "Remaining Dues / Balance Payable")
    p.drawRightString(width - 55, y + 5, f"₹ {balance:,.2f}")
    p.setStrokeColor(colors.HexColor("#E5E0D8"))
    p.line(45, y, width - 45, y)

    # Transaction Reference & Notes
    y -= 30
    if payment.transaction_reference:
        p.setFont("Helvetica-Bold", 9)
        p.setFillColor(dark)
        p.drawString(45, y, f"Transaction Reference / UTR: {payment.transaction_reference}")
        y -= 16

    if payment.notes:
        p.setFont("Helvetica", 9)
        p.setFillColor(colors.HexColor("#555555"))
        p.drawString(45, y, f"Remarks: {payment.notes}")
        y -= 16

    # Payment Status Badge
    y -= 15
    p.setLineWidth(1)
    if payment.is_fully_paid:
        p.setStrokeColor(colors.HexColor("#1A6B35"))
        p.setFillColor(colors.HexColor("#E8F5E9"))
        p.rect(45, y - 5, 130, 22, fill=1, stroke=1)
        p.setFillColor(colors.HexColor("#1A6B35"))
        p.setFont("Helvetica-Bold", 10)
        p.drawCentredString(110, y + 1, "✓ PAID IN FULL")
    elif payment.is_partial:
        p.setStrokeColor(colors.HexColor("#D95D00"))
        p.setFillColor(colors.HexColor("#FFF3E0"))
        p.rect(45, y - 5, 140, 22, fill=1, stroke=1)
        p.setFillColor(colors.HexColor("#D95D00"))
        p.setFont("Helvetica-Bold", 9)
        p.drawCentredString(115, y + 1, "PARTIALLY PAID")
    else:
        p.setStrokeColor(maroon)
        p.setFillColor(colors.HexColor("#FFEBEE"))
        p.rect(45, y - 5, 130, 22, fill=1, stroke=1)
        p.setFillColor(maroon)
        p.setFont("Helvetica-Bold", 10)
        p.drawCentredString(110, y + 1, "PENDING / DUE")

    # Signature Block
    sig_y = 120
    p.setStrokeColor(dark)
    p.setLineWidth(0.8)
    p.line(width - 200, sig_y + 35, width - 50, sig_y + 35)

    p.setFillColor(dark)
    p.setFont("Helvetica-Bold", 10)
    p.drawCentredString(width - 125, sig_y + 20, teacher_name)
    p.setFont("Helvetica", 9)
    p.drawCentredString(width - 125, sig_y + 8, "Authorized Signatory")
    p.drawCentredString(width - 125, sig_y - 4, academy_name)

    # Bottom Footer Note
    p.setFont("Helvetica-Oblique", 8)
    p.setFillColor(colors.HexColor("#666666"))
    p.drawCentredString(width / 2, 48, "This is a computer-generated official e-receipt from Radhhanand Sangeet Vidyalaya.")
    p.drawCentredString(width / 2, 38, "For fee inquiries or corrections, please present this receipt number.")

    p.showPage()
    p.save()

    buffer.seek(0)
    return buffer.getvalue()


# ==============================================================================
# OFFICIAL WHATSAPP INTEGRATION & CHATBOT SERVICE
# ==============================================================================

def send_whatsapp_message(to_number, message_text, message_type='manual_alert', student=None, session=None, payment=None):
    """
    Sends a WhatsApp message using Meta Cloud API if credentials are configured;
    otherwise safely records in WhatsAppMessageLog under 'simulated' Test Mode.
    Returns dict: {'status': str, 'simulated': bool, 'log_id': int, 'error': str}
    """
    clean_phone = ''.join(c for c in str(to_number) if c.isdigit())
    if clean_phone.startswith('0'):
        clean_phone = clean_phone[1:]
    if len(clean_phone) == 10:
        clean_phone = '91' + clean_phone  # Add India country code default

    access_token = getattr(settings, 'WHATSAPP_ACCESS_TOKEN', '')
    phone_number_id = getattr(settings, 'WHATSAPP_PHONE_NUMBER_ID', '')
    api_version = getattr(settings, 'WHATSAPP_API_VERSION', 'v21.0')
    test_mode = getattr(settings, 'WHATSAPP_TEST_MODE', True)

    recipient_name = student.full_name if student else ""

    # Check if credentials are valid and live mode active
    if not test_mode and access_token and phone_number_id and access_token != 'YOUR_TOKEN':
        try:
            url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": clean_phone,
                "type": "text",
                "text": {"preview_url": False, "body": message_text}
            }
            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            data = resp.json()

            if resp.status_code == 200 and 'messages' in data:
                msg_id = data['messages'][0].get('id', '')
                log = WhatsAppMessageLog.objects.create(
                    student=student,
                    session=session,
                    payment=payment,
                    recipient_phone=clean_phone,
                    recipient_name=recipient_name,
                    message_type=message_type,
                    message_text=message_text,
                    provider_message_id=msg_id,
                    status='sent'
                )
                return {'status': 'sent', 'simulated': False, 'log_id': log.id, 'error': ''}
            else:
                err_msg = str(data.get('error', {}).get('message', resp.text))
                log = WhatsAppMessageLog.objects.create(
                    student=student,
                    session=session,
                    payment=payment,
                    recipient_phone=clean_phone,
                    recipient_name=recipient_name,
                    message_type=message_type,
                    message_text=message_text,
                    status='failed',
                    error_details=err_msg
                )
                return {'status': 'failed', 'simulated': False, 'log_id': log.id, 'error': err_msg}
        except Exception as e:
            log = WhatsAppMessageLog.objects.create(
                student=student,
                session=session,
                payment=payment,
                recipient_phone=clean_phone,
                recipient_name=recipient_name,
                message_type=message_type,
                message_text=message_text,
                status='failed',
                error_details=str(e)
            )
            return {'status': 'failed', 'simulated': False, 'log_id': log.id, 'error': str(e)}

    # Simulated / Test Mode
    log = WhatsAppMessageLog.objects.create(
        student=student,
        session=session,
        payment=payment,
        recipient_phone=clean_phone,
        recipient_name=recipient_name,
        message_type=message_type,
        message_text=message_text,
        provider_message_id=f"sim_{timezone.now().strftime('%Y%m%d%H%M%S')}_{clean_phone[-4:]}",
        status='simulated',
        error_details="Logged in Test Mode (WhatsApp API credentials unconfigured or test mode active)"
    )
    return {'status': 'simulated', 'simulated': True, 'log_id': log.id, 'error': ''}


def send_class_reminder_whatsapp(session, student=None):
    """
    Sends WhatsApp class reminder to student's parent/guardian before class.
    - Uses exact class date and time.
    - Prevents duplicate reminders for same student & session.
    - Never sends for cancelled classes.
    """
    if session.status == 'cancelled':
        return {'status': 'cancelled', 'error': 'Cannot send reminder for cancelled class session'}

    students = [student] if student else [
        enr.student for enr in session.batch.enrollments.filter(is_active=True, student__status='active')
    ]

    results = []
    time_str = session.start_time.strftime('%I:%M %p')
    date_str = session.date.strftime('%d %B %Y')

    for st in students:
        if getattr(st, 'whatsapp_opt_out', False):
            results.append({'student': st.full_name, 'status': 'skipped', 'reason': 'Parent opted out of WhatsApp messages'})
            continue

        phone = st.guardian_whatsapp or st.guardian_phone or st.phone
        if not phone:
            results.append({'student': st.full_name, 'status': 'skipped', 'reason': 'No contact number'})
            continue

        # Prevent duplicate reminder for this student and session
        already_sent = WhatsAppMessageLog.objects.filter(
            student=st,
            session=session,
            message_type='class_reminder'
        ).exists()
        if already_sent:
            results.append({'student': st.full_name, 'status': 'skipped', 'reason': 'Reminder already sent'})
            continue

        msg = (
            f"Hello! This is Radhhanand Sangeet Vidyalaya.\n\n"
            f"Reminder: Your child's {session.batch.name} Tabla class is scheduled for today ({date_str}) at {time_str}.\n\n"
            f"Please ensure regular riyaz before class. Contact the academy if you need any assistance.\n\n"
            f"Thank you!"
        )

        res = send_whatsapp_message(
            to_number=phone,
            message_text=msg,
            message_type='class_reminder',
            student=st,
            session=session
        )
        results.append({'student': st.full_name, 'phone': phone, 'status': res['status'], 'simulated': res.get('simulated', False)})

    return results


def send_payment_receipt_whatsapp(payment):
    """
    Sends an electronic receipt message to parent/guardian via WhatsApp after successful payment.
    Does not expose receipts to unrelated recipients.
    """
    student = payment.student
    if getattr(student, 'whatsapp_opt_out', False):
        return {'status': 'skipped', 'error': 'Parent has opted out of WhatsApp notifications'}

    phone = student.guardian_whatsapp or student.guardian_phone or student.phone
    if not phone:
        return {'status': 'skipped', 'error': 'No contact number available for parent/guardian'}

    msg = (
        f"Hello! This is Radhhanand Sangeet Vidyalaya.\n\n"
        f"Fee Payment Confirmed:\n"
        f"• Receipt No: {payment.receipt_number}\n"
        f"• Student: {student.full_name} ({student.student_id})\n"
        f"• Fee Period: {payment.billing_period}\n"
        f"• Amount Received: ₹{payment.amount_paid:,.2f}\n"
        f"• Remaining Balance: ₹{payment.outstanding_balance:,.2f}\n"
        f"• Payment Date: {payment.payment_date.strftime('%d %b %Y') if payment.payment_date else 'Today'}\n\n"
        f"You can view and download your official PDF receipt anytime from the academy portal.\n\n"
        f"Thank you!"
    )

    return send_whatsapp_message(
        to_number=phone,
        message_text=msg,
        message_type='fee_receipt',
        student=student,
        payment=payment
    )


def process_chatbot_query(sender_phone=None, incoming_text='', phone_number=None):
    if phone_number and not sender_phone:
        sender_phone = phone_number
    sender_phone = str(sender_phone or '')
    """
    Handles parent queries via WhatsApp chatbot with privacy verification.
    Supported queries:
    - Today's class time
    - Next class schedule
    - Fee status & balance
    - Receipt request
    - Academy contact info & Guru Ji details
    """
    settings_obj = AcademySettings.get_settings()
    academy_name = "Radhhanand Sangeet Vidyalaya"
    today = timezone.now().date()

    # Normalize phone
    digits_only = ''.join(c for c in sender_phone if c.isdigit())
    last_10 = digits_only[-10:] if len(digits_only) >= 10 else digits_only

    # Look up student linked to this phone
    linked_students = Student.objects.filter(
        Q(guardian_whatsapp__endswith=last_10) |
        Q(guardian_phone__endswith=last_10) |
        Q(phone__endswith=last_10)
    ).distinct()

    text_lower = incoming_text.lower().strip()

    # 1. Contact / General Info Query (Publicly safe)
    if any(k in text_lower for k in ['contact', 'address', 'location', 'phone', 'email', 'guru', 'where', 'teacher']):
        return (
            f"Namaste! Here is the official contact information for {academy_name}:\n\n"
            f"• Guru Ji / Primary Instructor: {settings_obj.teacher_name}\n"
            f"• Phone: {settings_obj.phone or '+91 98765 43210'}\n"
            f"• Email: {settings_obj.email or 'contact@radhhanand.org'}\n"
            f"• Address: {settings_obj.address or 'Radhhanand Sangeet Vidyalaya, India'}\n\n"
            f"Classes are conducted Tuesday, Thursday, Saturday (5-8 PM) and Sunday (8-11 AM)."
        )

    # If sender number not recognized
    if not linked_students.exists():
        return (
            f"Namaste! Welcome to {academy_name}.\n\n"
            f"We could not find an enrolled student registered with this phone number (+{digits_only}).\n\n"
            f"For new admissions or account assistance, please contact the academy office directly at "
            f"{settings_obj.phone or '+91 98765 43210'}."
        )

    student = linked_students.first()

    # 2. Today's Class Query
    if any(k in text_lower for k in ['today', 'today class', 'time today', 'todays class', 'timing']):
        today_session = ClassSession.objects.filter(
            batch__enrollments__student=student,
            batch__enrollments__is_active=True,
            date=today
        ).first()

        if today_session:
            if today_session.status == 'cancelled':
                reason = f" (Reason: {today_session.cancellation_reason})" if today_session.cancellation_reason else ""
                return f"Notice for {student.full_name}: Today's class for {today_session.batch.name} is CANCELLED{reason}."
            return (
                f"Namaste! Today's class for {student.full_name}:\n"
                f"• Batch: {today_session.batch.name}\n"
                f"• Time: {today_session.start_time.strftime('%I:%M %p')} to {today_session.end_time.strftime('%I:%M %p')}\n"
                f"• Status: {today_session.get_status_display()}"
            )
        else:
            # Find next upcoming session
            next_session = ClassSession.objects.filter(
                batch__enrollments__student=student,
                batch__enrollments__is_active=True,
                date__gt=today,
                status='scheduled'
            ).order_by('date', 'start_time').first()
            if next_session:
                return (
                    f"No class scheduled for today ({today.strftime('%d %b')}).\n"
                    f"Next class for {student.full_name} is on {next_session.date.strftime('%A, %d %B')} "
                    f"at {next_session.start_time.strftime('%I:%M %p')} ({next_session.batch.name})."
                )
            return f"No class scheduled for today ({today.strftime('%d %b')}). Please check with your teacher."

    # 3. Next Class Query
    if any(k in text_lower for k in ['next', 'upcoming', 'when is class', 'schedule']):
        next_session = ClassSession.objects.filter(
            batch__enrollments__student=student,
            batch__enrollments__is_active=True,
            date__gte=today,
            status='scheduled'
        ).order_by('date', 'start_time').first()

        if next_session:
            return (
                f"Upcoming class for {student.full_name}:\n"
                f"• Date: {next_session.date.strftime('%A, %d %B %Y')}\n"
                f"• Time: {next_session.start_time.strftime('%I:%M %p')} - {next_session.end_time.strftime('%I:%M %p')}\n"
                f"• Batch: {next_session.batch.name}"
            )
        return f"No upcoming sessions scheduled in the immediate timetable for {student.full_name}."

    # 4. Fee Status / Remaining Balance
    if any(k in text_lower for k in ['fee', 'fees', 'balance', 'due', 'paid', 'dues', 'receipt', 'bill']):
        latest_payment = PaymentRecord.objects.filter(student=student, is_reversed=False).order_by('-payment_date', '-id').first()
        total_due = PaymentRecord.objects.filter(student=student, is_reversed=False).aggregate(s=Sum('amount_due'))['s'] or Decimal('0.00')
        total_paid = PaymentRecord.objects.filter(student=student, is_reversed=False).aggregate(s=Sum('amount_paid'))['s'] or Decimal('0.00')
        balance = max(Decimal('0.00'), total_due - total_paid)

        if latest_payment:
            return (
                f"Fee Statement for {student.full_name} ({academy_name}):\n\n"
                f"• Latest Period: {latest_payment.billing_period}\n"
                f"• Last Paid: ₹{latest_payment.amount_paid:,.2f} on {latest_payment.payment_date.strftime('%d %b %Y') if latest_payment.payment_date else 'N/A'}\n"
                f"• Receipt No: {latest_payment.receipt_number}\n"
                f"• Total Outstanding Balance: ₹{balance:,.2f}\n"
                f"• Status: {'Fully Paid' if balance == 0 else 'Pending Balance'}\n\n"
                f"You can request receipt copies by contacting academy staff."
            )
        return (
            f"No payment records currently found for {student.full_name}.\n"
            f"Monthly fee applicable: ₹{student.monthly_fee:,.2f}.\n"
            f"Please contact academy staff to record your fee payment."
        )

    # 5. Default Friendly Fallback
    return (
        f"Namaste! This is the automated assistant for {academy_name}.\n\n"
        f"You can ask me:\n"
        f"1. What time is today's class?\n"
        f"2. When is my child's next class?\n"
        f"3. What is our fee status and remaining balance?\n"
        f"4. Academy contact info\n\n"
        f"For custom queries, our Guru Ji and staff are available at {settings_obj.phone or '+91 98765 43210'}."
    )


# ==============================================================================
# REPORTING ENGINE & SUMMARIES
# ==============================================================================

def get_attendance_report_data(start_date=None, end_date=None, batch_id=None):
    """
    Computes daily, weekly, monthly, and batch-wise attendance metrics.
    """
    today = timezone.now().date()
    if not start_date:
        start_date = today.replace(day=1)  # start of this month
    if not end_date:
        end_date = today

    sessions = ClassSession.objects.filter(
        status='conducted',
        date__gte=start_date,
        date__lte=end_date
    )
    if batch_id:
        sessions = sessions.filter(batch_id=batch_id)

    total_conducted = sessions.count()
    attendances = Attendance.objects.filter(session__in=sessions)
    total_present = attendances.filter(status='present').count()
    total_absent = attendances.filter(status='absent').count()
    total_leave = attendances.filter(status='leave').count()
    total_late = attendances.filter(status='late').count()
    total_recorded = attendances.count()

    overall_pct = round((total_present / total_recorded * 100), 1) if total_recorded > 0 else 0.0

    # Batch-wise breakdown
    batches = Batch.objects.filter(is_active=True)
    if batch_id:
        batches = batches.filter(id=batch_id)

    batch_rows = []
    for b in batches:
        b_sessions = sessions.filter(batch=b)
        b_att = attendances.filter(session__in=b_sessions)
        b_present = b_att.filter(status='present').count()
        b_total = b_att.count()
        b_pct = round((b_present / b_total * 100), 1) if b_total > 0 else None
        batch_rows.append({
            'batch': b,
            'sessions_count': b_sessions.count(),
            'present_count': b_present,
            'total_slots': b_total,
            'percentage': b_pct
        })

    # Student-wise attendance register
    settings_obj = AcademySettings.get_settings()
    students_qs = Student.objects.filter(status__in=['active', 'paused'], is_archived=False)
    if batch_id:
        students_qs = students_qs.filter(enrollments__batch_id=batch_id, enrollments__is_active=True)

    student_rows = []
    low_attendance_students = []
    for s in students_qs.distinct():
        b_filter = Batch.objects.filter(id=batch_id).first() if batch_id else None
        stats = calculate_student_attendance(s, start_date=start_date, end_date=end_date, batch=b_filter)
        student_rows.append(stats)
        if stats['percentage'] is not None and stats['percentage'] < settings_obj.attendance_threshold:
            low_attendance_students.append(stats)

    return {
        'start_date': start_date,
        'end_date': end_date,
        'total_conducted': total_conducted,
        'total_present': total_present,
        'total_absent': total_absent,
        'total_leave': total_leave,
        'total_late': total_late,
        'overall_pct': overall_pct,
        'batch_rows': batch_rows,
        'student_rows': student_rows,
        'low_attendance_students': low_attendance_students,
        'threshold': settings_obj.attendance_threshold,
    }


def get_fees_report_data(start_date=None, end_date=None, batch_id=None, status_filter=None):
    """
    Computes financial collections, outstanding dues, and breakdown by payment method.
    """
    today = timezone.now().date()
    if not start_date:
        start_date = today.replace(day=1)
    if not end_date:
        end_date = today

    payments_qs = PaymentRecord.objects.filter(
        payment_date__gte=start_date,
        payment_date__lte=end_date,
        is_reversed=False
    ).select_related('student')

    if batch_id:
        payments_qs = payments_qs.filter(student__enrollments__batch_id=batch_id, student__enrollments__is_active=True)

    total_collected = payments_qs.aggregate(s=Sum('amount_paid'))['s'] or Decimal('0.00')
    total_due = payments_qs.aggregate(s=Sum('amount_due'))['s'] or Decimal('0.00')
    total_outstanding = max(Decimal('0.00'), total_due - total_collected)

    # Method breakdown
    method_counts = {}
    for p in payments_qs:
        m = p.get_payment_method_display()
        method_counts[m] = method_counts.get(m, Decimal('0.00')) + p.amount_paid

    # All active students fee balance check
    students = Student.objects.filter(status='active', is_archived=False)
    if batch_id:
        students = students.filter(enrollments__batch_id=batch_id, enrollments__is_active=True)

    paid_students = []
    partial_students = []
    due_students = []

    for s in students:
        s_payments = PaymentRecord.objects.filter(student=s, is_reversed=False)
        s_due = s_payments.aggregate(s=Sum('amount_due'))['s'] or Decimal('0.00')
        s_paid = s_payments.aggregate(s=Sum('amount_paid'))['s'] or Decimal('0.00')
        s_bal = max(Decimal('0.00'), s_due - s_paid)

        info = {'student': s, 'due': s_due, 'paid': s_paid, 'balance': s_bal}
        if s_bal == 0 and s_due > 0:
            paid_students.append(info)
        elif 0 < s_paid < s_due:
            partial_students.append(info)
        elif s_due > 0 and s_paid == 0:
            due_students.append(info)

    return {
        'start_date': start_date,
        'end_date': end_date,
        'total_collected': total_collected,
        'total_due': total_due,
        'total_outstanding': total_outstanding,
        'payments': payments_qs,
        'method_counts': method_counts,
        'paid_students': paid_students,
        'partial_students': partial_students,
        'due_students': due_students,
    }


def get_timetable_report_data(start_date=None, end_date=None, batch_id=None):
    """
    Computes session schedule metrics (conducted, scheduled, cancelled, rescheduled).
    """
    today = timezone.now().date()
    if not start_date:
        start_date = today - timedelta(days=7)
    if not end_date:
        end_date = today + timedelta(days=21)

    sessions = ClassSession.objects.filter(
        date__gte=start_date,
        date__lte=end_date
    ).select_related('batch')

    if batch_id:
        sessions = sessions.filter(batch_id=batch_id)

    conducted = sessions.filter(status='conducted')
    scheduled = sessions.filter(status='scheduled')
    cancelled = sessions.filter(status='cancelled')
    rescheduled = sessions.filter(is_rescheduled=True)

    return {
        'start_date': start_date,
        'end_date': end_date,
        'total_sessions': sessions.count(),
        'conducted_count': conducted.count(),
        'scheduled_count': scheduled.count(),
        'cancelled_count': cancelled.count(),
        'rescheduled_count': rescheduled.count(),
        'sessions': sessions.order_by('date', 'start_time'),
    }
