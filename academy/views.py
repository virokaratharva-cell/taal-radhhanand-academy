import os
import uuid
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Sum, Count
from django.http import HttpResponse, Http404, FileResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.conf import settings

from .models import (
    AcademySettings, Student, Batch, BatchEnrollment, BatchRecurringSchedule,
    ClassSession, Attendance, AttendanceAuditLog,
    Taal, Composition, Lesson, PracticeAssignment,
    StudentProgress, PerformanceRecord, ExaminationRecord,
    FeePlan, PaymentRecord, AcademyAlert, WhatsAppMessageLog, ChatbotVerificationCode
)
from .forms import (
    StudentForm, BatchForm, BatchEnrollmentForm, ClassSessionForm,
    BatchRecurringScheduleForm, ClassSessionRescheduleForm, ClassSessionCancelForm,
    LessonForm, PracticeAssignmentForm, TaalForm, CompositionForm,
    StudentProgressForm, PerformanceRecordForm, ExaminationRecordForm,
    FeePlanForm, PaymentRecordForm, AcademySettingsForm
)
from .services import (
    calculate_student_attendance, calculate_batch_attendance,
    record_session_attendance, refresh_academy_alerts,
    generate_safe_csv_response, create_database_backup, list_database_backups,
    seed_foundational_taals_and_compositions, generate_future_sessions,
    reschedule_class_session, cancel_class_session, generate_receipt_pdf,
    send_whatsapp_message, send_class_reminder_whatsapp, send_payment_receipt_whatsapp,
    process_chatbot_query, get_attendance_report_data, get_fees_report_data,
    get_timetable_report_data
)



# ==============================================================================
# AUTHENTICATION VIEWS
# ==============================================================================

def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, f"Welcome back, {user.first_name or user.username}!")
            next_url = request.GET.get('next')
            return redirect(next_url if next_url else 'dashboard')
        else:
            messages.error(request, "Invalid username or password. Please check your credentials.")
    else:
        form = AuthenticationForm(request)

    return render(request, 'academy/login.html', {'form': form})


@login_required
def logout_view(request):
    logout(request)
    messages.info(request, "You have been logged out successfully.")
    return redirect('login')


# ==============================================================================
# DASHBOARD
# ==============================================================================

@login_required
def dashboard_view(request):
    refresh_academy_alerts()
    academy_settings = AcademySettings.get_settings()
    today = timezone.now().date()
    month_start = today.replace(day=1)

    # Summary Statistics
    total_active_students = Student.objects.filter(status='active').count()
    total_active_batches = Batch.objects.filter(is_active=True).count()
    classes_today = ClassSession.objects.filter(date=today)
    classes_scheduled_today_count = classes_today.count()
    classes_conducted_month_count = ClassSession.objects.filter(
        status='conducted',
        date__gte=month_start,
        date__lte=today
    ).count()

    # Today's attendance counts
    today_sessions = ClassSession.objects.filter(date=today, status='conducted')
    today_attendances = Attendance.objects.filter(session__in=today_sessions)
    today_present = today_attendances.filter(status='present').count()
    today_absent = today_attendances.filter(status='absent').count()
    today_leave = today_attendances.filter(status='leave').count()

    # Students requiring follow-up (low attendance or repeated absence)
    flagged_students = []
    active_students = Student.objects.filter(status='active').prefetch_related('enrollments__batch')
    for st in active_students:
        stats = calculate_student_attendance(st)
        if (stats['percentage'] is not None and stats['percentage'] < academy_settings.attendance_threshold) or \
           (stats['consecutive_absences'] >= academy_settings.consecutive_absence_threshold):
            flagged_students.append({
                'student': st,
                'percentage': stats['percentage'],
                'consecutive_absences': stats['consecutive_absences'],
                'eligible_count': stats['eligible_count'],
            })

    # Fee summary
    outstanding_fees_total = Decimal('0.00')
    monthly_fees_collected = Decimal('0.00')
    if academy_settings.enable_fees:
        active_payments = PaymentRecord.objects.filter(is_reversed=False)
        total_due_all = active_payments.aggregate(s=Sum('amount_due'))['s'] or Decimal('0.00')
        total_paid_all = active_payments.aggregate(s=Sum('amount_paid'))['s'] or Decimal('0.00')
        outstanding_fees_total = max(Decimal('0.00'), total_due_all - total_paid_all)

        monthly_fees_collected = active_payments.filter(
            payment_date__gte=month_start,
            payment_date__lte=today
        ).aggregate(s=Sum('amount_paid'))['s'] or Decimal('0.00')

    # Recent payments
    recent_payments = PaymentRecord.objects.filter(is_reversed=False).select_related('student').order_by('-payment_date', '-id')[:5]

    # Recent items
    recent_students = Student.objects.all().order_by('-created_at')[:5]
    upcoming_classes = ClassSession.objects.filter(
        date__gte=today,
        status='scheduled'
    ).order_by('date', 'start_time')[:5]
    recent_lessons = Lesson.objects.all().order_by('-date', '-created_at')[:4]
    due_assignments = PracticeAssignment.objects.filter(
        status__in=['assigned', 'needs_practice'],
        due_date__gte=today
    ).order_by('due_date')[:5]

    # Active alerts
    active_alerts = AcademyAlert.objects.filter(is_dismissed=False)[:5]

    # Chart data: Monthly attendance over last 6 months
    chart_months = []
    chart_present_rates = []
    for i in range(5, -1, -1):
        # Calculate date for month i months ago
        year = today.year
        month = today.month - i
        while month <= 0:
            month += 12
            year -= 1
        m_start = date(year, month, 1)
        # last day of month
        if month == 12:
            m_end = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            m_end = date(year, month + 1, 1) - timedelta(days=1)

        m_sessions = ClassSession.objects.filter(status='conducted', date__gte=m_start, date__lte=m_end)
        m_attendances = Attendance.objects.filter(session__in=m_sessions)
        total_att = m_attendances.count()
        pres_att = m_attendances.filter(status='present').count()
        rate = round((pres_att / total_att * 100), 1) if total_att > 0 else 0

        chart_months.append(m_start.strftime('%b %Y'))
        chart_present_rates.append(rate)

    # Batch attendance breakdown
    batch_breakdowns = []
    for b in Batch.objects.filter(is_active=True)[:6]:
        b_stats = calculate_batch_attendance(b)
        batch_breakdowns.append({
            'name': b.name,
            'percentage': b_stats['batch_percentage'] if b_stats['batch_percentage'] is not None else 0,
            'conducted': b_stats['conducted_sessions_count'],
            'students': b_stats['enrolled_students_count'],
        })

    context = {
        'total_active_students': total_active_students,
        'total_active_batches': total_active_batches,
        'classes_scheduled_today_count': classes_scheduled_today_count,
        'classes_conducted_month_count': classes_conducted_month_count,
        'today_present': today_present,
        'today_absent': today_absent,
        'today_leave': today_leave,
        'flagged_students_count': len(flagged_students),
        'flagged_students': flagged_students[:5],
        'monthly_fees_collected': monthly_fees_collected,
        'outstanding_fees_total': outstanding_fees_total,
        'recent_payments': recent_payments,
        'classes_today': classes_today,
        'recent_students': recent_students,
        'upcoming_classes': upcoming_classes,
        'recent_lessons': recent_lessons,
        'due_assignments': due_assignments,
        'active_alerts': active_alerts,
        'chart_months': chart_months,
        'chart_present_rates': chart_present_rates,
        'batch_breakdowns': batch_breakdowns,
        'today': today,
    }
    return render(request, 'academy/dashboard.html', context)



# ==============================================================================
# STUDENT MANAGEMENT
# ==============================================================================

@login_required
def student_list(request):
    query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '')
    batch_filter = request.GET.get('batch', '')
    level_filter = request.GET.get('level', '')
    archived_filter = request.GET.get('archived', '0')
    sort_by = request.GET.get('sort', 'student_id')

    students_qs = Student.objects.all()

    if archived_filter == '1':
        students_qs = students_qs.filter(is_archived=True)
    elif archived_filter != 'all':
        students_qs = students_qs.filter(is_archived=False)

    if query:
        students_qs = students_qs.filter(
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(student_id__icontains=query) |
            Q(phone__icontains=query) |
            Q(guardian_phone__icontains=query) |
            Q(guardian_whatsapp__icontains=query) |
            Q(guardian_name__icontains=query) |
            Q(email__icontains=query) |
            Q(enrollments__batch__name__icontains=query)
        )

    if status_filter:
        students_qs = students_qs.filter(status=status_filter)

    if batch_filter:
        students_qs = students_qs.filter(enrollments__batch_id=batch_filter, enrollments__is_active=True)

    if level_filter:
        students_qs = students_qs.filter(level=level_filter)

    valid_sorts = ['student_id', '-student_id', 'first_name', '-first_name', 'enrollment_date', '-enrollment_date']
    if sort_by in valid_sorts:
        students_qs = students_qs.order_by(sort_by)
    else:
        students_qs = students_qs.order_by('student_id')

    paginator = Paginator(students_qs.distinct(), 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    batches = Batch.objects.filter(is_active=True, is_archived=False)

    context = {
        'page_obj': page_obj,
        'query': query,
        'status_filter': status_filter,
        'batch_filter': batch_filter,
        'level_filter': level_filter,
        'archived_filter': archived_filter,
        'sort_by': sort_by,
        'batches': batches,
        'status_choices': Student.STATUS_CHOICES,
        'level_choices': Student.LEVEL_CHOICES,
        'total_count': Student.objects.count(),
        'active_count': Student.objects.filter(status='active', is_archived=False).count(),
        'archived_count': Student.objects.filter(is_archived=True).count(),
    }
    return render(request, 'academy/students/student_list.html', context)


@login_required
def student_create(request):
    if request.method == 'POST':
        form = StudentForm(request.POST)
        if form.is_valid():
            student = form.save()
            initial_batch = form.cleaned_data.get('initial_batch')
            if initial_batch:
                BatchEnrollment.objects.create(
                    student=student,
                    batch=initial_batch,
                    enrolled_date=student.enrollment_date,
                    is_active=True
                )
            messages.success(request, f"Student {student.full_name} ({student.student_id}) created successfully.")
            return redirect('student_detail', student_id=student.id)
    else:
        form = StudentForm()

    return render(request, 'academy/students/student_form.html', {'form': form, 'title': 'Add New Student'})


@login_required
def student_edit(request, student_id):
    student = get_object_or_404(Student, id=student_id)
    if request.method == 'POST':
        form = StudentForm(request.POST, instance=student)
        if form.is_valid():
            form.save()
            messages.success(request, f"Student {student.full_name} updated successfully.")
            return redirect('student_detail', student_id=student.id)
    else:
        form = StudentForm(instance=student)

    return render(request, 'academy/students/student_form.html', {'form': form, 'student': student, 'title': f'Edit Student: {student.full_name}'})


@login_required
def student_archive_toggle(request, student_id):
    """
    Safely archives or unarchives a student without deleting historical records.
    """
    student = get_object_or_404(Student, id=student_id)
    student.is_archived = not student.is_archived
    student.save()
    action = "archived" if student.is_archived else "restored from archive"
    messages.success(request, f"Student {student.full_name} ({student.student_id}) has been {action}. All historical attendance, payments, and notes are preserved.")
    return redirect('student_detail', student_id=student.id)


@login_required
def student_detail(request, student_id):
    student = get_object_or_404(Student, id=student_id)
    attendance_stats = calculate_student_attendance(student)

    enrollments = student.enrollments.select_related('batch').order_by('-enrolled_date')
    assignments = student.assignments.all().order_by('-due_date')[:10]
    progress_records = student.progress_records.all().order_by('-date')[:5]
    performances = student.performances.all().order_by('-event_date')[:5]
    examinations = student.examinations.all().order_by('-exam_date')[:5]
    payments = student.payments.filter(is_reversed=False).order_by('-payment_date', '-created_at')

    # Fee totals
    total_fee_due = payments.aggregate(s=Sum('amount_due'))['s'] or Decimal('0.00')
    total_fee_paid = payments.aggregate(s=Sum('amount_paid'))['s'] or Decimal('0.00')
    outstanding_balance = max(Decimal('0.00'), total_fee_due - total_fee_paid)

    # Upcoming classes
    today = timezone.now().date()
    upcoming_classes = ClassSession.objects.filter(
        batch__enrollments__student=student,
        batch__enrollments__is_active=True,
        date__gte=today,
        status='scheduled'
    ).order_by('date', 'start_time')[:5]

    available_batches = Batch.objects.filter(is_active=True, is_archived=False).exclude(
        enrollments__student=student, enrollments__is_active=True
    )

    context = {
        'student': student,
        'attendance_stats': attendance_stats,
        'enrollments': enrollments,
        'assignments': assignments,
        'progress_records': progress_records,
        'performances': performances,
        'examinations': examinations,
        'payments': payments[:10],
        'total_fee_due': total_fee_due,
        'total_fee_paid': total_fee_paid,
        'outstanding_balance': outstanding_balance,
        'upcoming_classes': upcoming_classes,
        'available_batches': available_batches,
    }
    return render(request, 'academy/students/student_detail.html', context)


@login_required
def student_print(request, student_id):
    student = get_object_or_404(Student, id=student_id)
    attendance_stats = calculate_student_attendance(student)
    enrollments = student.enrollments.select_related('batch').filter(is_active=True)
    progress_records = student.progress_records.all().order_by('-date')[:5]


    context = {
        'student': student,
        'attendance_stats': attendance_stats,
        'enrollments': enrollments,
        'progress_records': progress_records,
    }
    return render(request, 'academy/students/student_print.html', context)


# ==============================================================================
# BATCH MANAGEMENT
# ==============================================================================

@login_required
def batch_list(request):
    query = request.GET.get('q', '').strip()
    day_filter = request.GET.get('day', '').strip()
    status_filter = request.GET.get('status', 'active').strip()

    batches = Batch.objects.all().prefetch_related('enrollments', 'recurring_schedules')

    if status_filter == 'active':
        batches = batches.filter(is_archived=False)
    elif status_filter == 'archived':
        batches = batches.filter(is_archived=True)

    if day_filter:
        day_map = {
            'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
            'friday': 4, 'saturday': 5, 'sunday': 6
        }
        day_idx = day_map.get(day_filter.lower())
        if day_idx is not None:
            batches = batches.filter(
                Q(regular_day__iexact=day_filter) |
                Q(recurring_schedules__day_of_week=day_idx)
            ).distinct()
        else:
            batches = batches.filter(regular_day__iexact=day_filter)

    if query:
        batches = batches.filter(
            Q(name__icontains=query) |
            Q(batch_id__icontains=query) |
            Q(course__icontains=query) |
            Q(teacher_name__icontains=query) |
            Q(regular_day__icontains=query)
        ).distinct()

    context = {
        'batches': batches,
        'query': query,
        'day_filter': day_filter,
        'status_filter': status_filter,
        'day_choices': [d[0] for d in Batch.DAY_CHOICES],
    }
    return render(request, 'academy/batches/batch_list.html', context)


@login_required
def batch_create(request):
    if request.method == 'POST':
        form = BatchForm(request.POST)
        if form.is_valid():
            batch = form.save(commit=False)
            if not batch.batch_id:
                batch.batch_id = Batch.generate_batch_id(batch.level)
            batch.save()

            # Automatically establish the initial recurring schedule entry for this batch's chosen day & time
            day_map = {'Monday': 0, 'Tuesday': 1, 'Wednesday': 2, 'Thursday': 3, 'Friday': 4, 'Saturday': 5, 'Sunday': 6}
            if batch.regular_day in day_map and batch.start_time and batch.end_time:
                dur = int((batch.end_time.hour * 60 + batch.end_time.minute) - (batch.start_time.hour * 60 + batch.start_time.minute))
                if dur <= 0:
                    dur = 60
                BatchRecurringSchedule.objects.get_or_create(
                    batch=batch,
                    day_of_week=day_map[batch.regular_day],
                    start_time=batch.start_time,
                    defaults={'end_time': batch.end_time, 'duration_minutes': dur, 'is_active': True}
                )
                generate_future_sessions(batch=batch, horizon_days=60)

            messages.success(request, f"Batch '{batch.name}' created successfully with recurring schedule.")
            return redirect('batch_detail', batch_id=batch.id)
    else:
        initial_id = Batch.generate_batch_id('BEG')
        form = BatchForm(initial={'batch_id': initial_id})

    return render(request, 'academy/batches/batch_form.html', {'form': form, 'title': 'Create New Batch'})


@login_required
def batch_edit(request, batch_id):
    batch = get_object_or_404(Batch, id=batch_id)
    if request.method == 'POST':
        form = BatchForm(request.POST, instance=batch)
        if form.is_valid():
            form.save()
            messages.success(request, f"Batch '{batch.name}' updated successfully.")
            return redirect('batch_detail', batch_id=batch.id)
    else:
        form = BatchForm(instance=batch)

    return render(request, 'academy/batches/batch_form.html', {'form': form, 'batch': batch, 'title': f'Edit Batch: {batch.name}'})


@login_required
def batch_delete(request, batch_id):
    """
    Safely deletes a batch if no historical records (attendance, conducted sessions, lessons) exist.
    If historical records exist, direct permanent deletion is blocked to prevent data corruption,
    and safe archiving is offered.
    Enforces POST with CSRF for actual deletion.
    """
    batch = get_object_or_404(Batch, id=batch_id)

    # Inspect foreign-key relationships and historical data:
    conducted_sessions = batch.sessions.filter(status='conducted')
    conducted_count = conducted_sessions.count()
    attendance_count = Attendance.objects.filter(session__batch=batch).count()
    lessons_count = batch.lessons.count()
    active_enrollments_count = batch.enrollments.filter(is_active=True).count()
    all_enrollments_count = batch.enrollments.count()
    scheduled_sessions_count = batch.sessions.filter(status='scheduled').count()
    cancelled_sessions_count = batch.sessions.filter(status='cancelled').count()
    recurring_rules_count = batch.recurring_schedules.count()
    assignments_count = batch.assignments.count()

    has_historical_records = (conducted_count > 0 or attendance_count > 0 or lessons_count > 0)

    if request.method == 'POST':
        # Hard barrier: never silently delete or corrupt historical records
        if has_historical_records:
            messages.error(
                request,
                f"Cannot delete batch '{batch.name}' because it contains historical records "
                f"({conducted_count} conducted class(es), {attendance_count} attendance record(s), {lessons_count} lesson(s)). "
                f"Permanent deletion is blocked to protect student history. Please archive the batch instead."
            )
            return redirect('batch_detail', batch_id=batch.id)

        batch_name = batch.name
        try:
            # Safely clean up unconducted future sessions, recurring timetable rules, and assignments
            batch.sessions.all().delete()
            batch.recurring_schedules.all().delete()
            batch.enrollments.all().delete()
            batch.assignments.all().delete()
            batch.delete()
            messages.success(request, f"Batch '{batch_name}' was successfully deleted.")
            return redirect('batch_list')
        except Exception as e:
            messages.error(request, f"Unable to delete batch '{batch_name}': {str(e)}")
            return redirect('batch_detail', batch_id=batch.id)

    context = {
        'batch': batch,
        'has_historical_records': has_historical_records,
        'conducted_count': conducted_count,
        'attendance_count': attendance_count,
        'lessons_count': lessons_count,
        'active_enrollments_count': active_enrollments_count,
        'all_enrollments_count': all_enrollments_count,
        'scheduled_sessions_count': scheduled_sessions_count,
        'cancelled_sessions_count': cancelled_sessions_count,
        'recurring_rules_count': recurring_rules_count,
        'assignments_count': assignments_count,
    }
    return render(request, 'academy/batches/batch_confirm_delete.html', context)


@login_required
def batch_archive_toggle(request, batch_id):
    """
    Safely archives or unarchives a batch without deleting historical records.
    """
    batch = get_object_or_404(Batch, id=batch_id)
    batch.is_archived = not batch.is_archived
    batch.save()
    action = "archived" if batch.is_archived else "restored from archive"
    messages.success(request, f"Batch '{batch.name}' has been {action}. All student enrollments and past class records are preserved.")
    return redirect('batch_detail', batch_id=batch.id)


@login_required
def batch_detail(request, batch_id):
    batch = get_object_or_404(Batch, id=batch_id)
    active_enrollments = batch.enrollments.filter(is_active=True).select_related('student')
    past_enrollments = batch.enrollments.filter(is_active=False).select_related('student')

    recent_sessions = batch.sessions.all().order_by('-date', '-start_time')[:10]
    attendance_stats = calculate_batch_attendance(batch)

    # Recurring schedules
    recurring_schedules = batch.recurring_schedules.all().order_by('day_of_week', 'start_time')
    schedule_form = BatchRecurringScheduleForm(initial={'batch': batch, 'start_time': batch.start_time, 'end_time': batch.end_time})

    # Students eligible to be added
    enrolled_student_ids = active_enrollments.values_list('student_id', flat=True)
    unassigned_students = Student.objects.filter(status='active', is_archived=False).exclude(id__in=enrolled_student_ids)

    context = {
        'batch': batch,
        'active_enrollments': active_enrollments,
        'past_enrollments': past_enrollments,
        'recent_sessions': recent_sessions,
        'attendance_stats': attendance_stats,
        'unassigned_students': unassigned_students,
        'recurring_schedules': recurring_schedules,
        'schedule_form': schedule_form,
    }
    return render(request, 'academy/batches/batch_detail.html', context)


@login_required
def batch_schedule_add(request, batch_id):
    batch = get_object_or_404(Batch, id=batch_id)
    if request.method == 'POST':
        form = BatchRecurringScheduleForm(request.POST)
        if form.is_valid():
            rule = form.save(commit=False)
            rule.batch = batch
            rule.save()
            # Idempotently generate upcoming classes
            generate_future_sessions(batch=batch, horizon_days=60)
            messages.success(request, f"Recurring timetable rule added: {rule}. Upcoming sessions updated.")
        else:
            for error in form.non_field_errors():
                messages.error(request, error)
            for field, errs in form.errors.items():
                for err in errs:
                    messages.error(request, f"{field.title()}: {err}")
    return redirect('batch_detail', batch_id=batch.id)


@login_required
def batch_schedule_delete(request, rule_id):
    rule = get_object_or_404(BatchRecurringSchedule, id=rule_id)
    batch_id = rule.batch.id
    rule.delete()
    messages.info(request, "Recurring schedule rule removed. Historical sessions remain intact.")
    return redirect('batch_detail', batch_id=batch_id)



@login_required
def batch_assign_student(request, batch_id):
    batch = get_object_or_404(Batch, id=batch_id)
    if request.method == 'POST':
        student_id = request.POST.get('student_id')
        student = get_object_or_404(Student, id=student_id)

        # Check existing active enrollment
        existing = BatchEnrollment.objects.filter(student=student, batch=batch, is_active=True).first()
        if existing:
            messages.warning(request, f"{student.full_name} is already active in {batch.name}.")
        else:
            BatchEnrollment.objects.create(
                student=student,
                batch=batch,
                enrolled_date=timezone.now().date(),
                is_active=True
            )
            messages.success(request, f"{student.full_name} assigned to {batch.name}.")
    return redirect('batch_detail', batch_id=batch.id)


@login_required
def batch_remove_student(request, batch_id, student_id):
    """
    Deactivates a student from a batch without deleting historical records.
    """
    batch = get_object_or_404(Batch, id=batch_id)
    student = get_object_or_404(Student, id=student_id)

    enrollment = BatchEnrollment.objects.filter(student=student, batch=batch, is_active=True).first()
    if enrollment:
        enrollment.is_active = False
        enrollment.left_date = timezone.now().date()
        enrollment.save()
        messages.info(request, f"{student.full_name} removed from future participation in {batch.name}. Historical attendance remains intact.")
    return redirect('batch_detail', batch_id=batch.id)


# ==============================================================================
# CLASS SCHEDULING AND CALENDAR
# ==============================================================================

@login_required
def session_list(request):
    today = timezone.now().date()
    batch_filter = request.GET.get('batch', '')
    status_filter = request.GET.get('status', '')
    month_filter = request.GET.get('month', today.strftime('%Y-%m'))

    sessions_qs = ClassSession.objects.all().select_related('batch')

    if batch_filter:
        sessions_qs = sessions_qs.filter(batch_id=batch_filter)

    if status_filter:
        sessions_qs = sessions_qs.filter(status=status_filter)

    if month_filter:
        try:
            yr, mo = [int(x) for x in month_filter.split('-')]
            sessions_qs = sessions_qs.filter(date__year=yr, date__month=mo)
        except ValueError:
            pass

    sessions_qs = sessions_qs.order_by('-date', '-start_time')

    paginator = Paginator(sessions_qs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    batches = Batch.objects.filter(is_active=True)

    context = {
        'page_obj': page_obj,
        'batches': batches,
        'batch_filter': batch_filter,
        'status_filter': status_filter,
        'month_filter': month_filter,
        'today': today,
    }
    return render(request, 'academy/sessions/session_list.html', context)


@login_required
def session_create(request):
    batch_id = request.GET.get('batch')
    initial_data = {}
    if batch_id:
        batch = get_object_or_404(Batch, id=batch_id)
        initial_data = {
            'batch': batch,
            'start_time': batch.start_time,
            'end_time': batch.end_time,
            'date': timezone.now().date()
        }

    if request.method == 'POST':
        form = ClassSessionForm(request.POST)
        if form.is_valid():
            session = form.save()
            messages.success(request, f"Class session scheduled for {session.batch.name} on {session.date}.")
            return redirect('session_list')
    else:
        form = ClassSessionForm(initial=initial_data)

    return render(request, 'academy/sessions/session_form.html', {'form': form, 'title': 'Schedule New Class Session'})


@login_required
def session_edit(request, session_id):
    session = get_object_or_404(ClassSession, id=session_id)
    if request.method == 'POST':
        form = ClassSessionForm(request.POST, instance=session)
        if form.is_valid():
            # If session is marked cancelled and has attendance, alert teacher
            was_cancelled = form.cleaned_data.get('status') == 'cancelled'
            if was_cancelled and session.attendances.exists():
                messages.warning(request, "Note: This session has recorded attendance. Because it is cancelled, it will not count towards attendance percentages.")
            form.save()
            messages.success(request, "Class session updated successfully.")
            return redirect('session_list')
    else:
        form = ClassSessionForm(instance=session)

    return render(request, 'academy/sessions/session_form.html', {'form': form, 'session': session, 'title': f'Edit Class Session: {session.batch.name} on {session.date}'})


@login_required
def session_mark_conducted(request, session_id):
    """Quick transition of session status to Conducted."""
    session = get_object_or_404(ClassSession, id=session_id)
    session.status = 'conducted'
    session.save()
    messages.success(request, f"Session for {session.batch.name} on {session.date} marked as Conducted. Now you can save attendance.")
    return redirect('attendance_mark', session_id=session.id)


@login_required
def session_cancel(request, session_id):
    session = get_object_or_404(ClassSession, id=session_id)
    if request.method == 'POST':
        reason = request.POST.get('cancellation_reason', '').strip()
        if not reason:
            messages.error(request, "Please state the reason for cancelling this session.")
            return redirect('session_list')
        cancel_class_session(session, reason)
        messages.info(request, f"Session cancelled: {session.batch.name} on {session.date}. Reason recorded.")
    return redirect('session_list')


@login_required
def session_reschedule(request, session_id):
    session = get_object_or_404(ClassSession, id=session_id)
    if request.method == 'POST':
        form = ClassSessionRescheduleForm(request.POST, instance=session)
        if form.is_valid():
            new_date = form.cleaned_data['date']
            new_start = form.cleaned_data['start_time']
            new_end = form.cleaned_data['end_time']
            reason = form.cleaned_data['reschedule_reason']
            reschedule_class_session(session, new_date, new_start, new_end, reason)
            messages.success(request, f"Class session successfully rescheduled to {new_date.strftime('%d %B %Y')} at {new_start.strftime('%I:%M %p')}.")
            return redirect('session_list')
    else:
        form = ClassSessionRescheduleForm(instance=session)

    return render(request, 'academy/sessions/session_reschedule.html', {
        'form': form,
        'session': session,
        'title': f'Reschedule Class: {session.batch.name}'
    })


@login_required
def sessions_generate_view(request):
    """
    Triggers automatic, idempotent recurring timetable generation.
    """
    if request.method == 'POST':
        batch_id = request.POST.get('batch_id')
        try:
            days = int(request.POST.get('days', 60))
        except ValueError:
            days = 60

        batch = Batch.objects.filter(id=batch_id).first() if batch_id else None
        res = generate_future_sessions(batch=batch, horizon_days=days)

        messages.success(
            request,
            f"Timetable generation complete: {res['created_count']} new future session(s) scheduled. "
            f"{res['skipped_count']} existing session(s) safely preserved."
        )
        if res['conflicts']:
            for c in res['conflicts']:
                messages.warning(request, c)

    return redirect('session_list')



# ==============================================================================
# ATTENDANCE WORKFLOW & HISTORY
# ==============================================================================

@login_required
def attendance_hub(request):
    """Central hub for launching attendance marking or reviewing history."""
    today = timezone.now().date()
    today_sessions = ClassSession.objects.filter(date=today).select_related('batch')
    recent_conducted = ClassSession.objects.filter(status='conducted').order_by('-date')[:10]
    batches = Batch.objects.filter(is_active=True)

    return render(request, 'academy/attendance/attendance_hub.html', {
        'today_sessions': today_sessions,
        'recent_conducted': recent_conducted,
        'batches': batches,
        'today': today,
    })


@login_required
def attendance_mark(request, session_id):
    """
    Core attendance marking page:
    1. Loads eligible students based on BatchEnrollment on session date.
    2. Displays Mark All Present / Mark All Absent controls.
    3. Saves attendance and logs audits for any corrections.
    """
    session = get_object_or_404(ClassSession, id=session_id)
    academy_settings = AcademySettings.get_settings()

    # Find eligible students enrolled on session date
    enrollments = BatchEnrollment.objects.filter(
        batch=session.batch,
        enrolled_date__lte=session.date
    ).filter(
        Q(left_date__isnull=True) | Q(left_date__gte=session.date)
    ).select_related('student')

    eligible_students = [enr.student for enr in enrollments if enr.student.status != 'discontinued' or enr.student.enrollment_date <= session.date]

    # Existing attendance records for this session
    existing_records = {att.student_id: att for att in session.attendances.all()}

    if request.method == 'POST':
        # Auto-mark session as conducted if still scheduled
        if session.status == 'scheduled':
            session.status = 'conducted'
            session.save()

        audit_reason = request.POST.get('audit_reason', '').strip()
        attendance_payload = {}

        for student in eligible_students:
            status_val = request.POST.get(f'status_{student.id}', 'present')
            remarks_val = request.POST.get(f'remarks_{student.id}', '').strip()
            attendance_payload[student.id] = {
                'status': status_val,
                'remarks': remarks_val
            }

        logs = record_session_attendance(
            session=session,
            attendance_data=attendance_payload,
            user=request.user,
            audit_reason=audit_reason
        )

        if logs:
            messages.success(request, f"Attendance saved! {len(logs)} correction(s) were logged in the audit trail.")
        else:
            messages.success(request, f"Attendance saved successfully for {len(eligible_students)} student(s).")

        return redirect('attendance_mark', session_id=session.id)

    # Prepare student rows for template
    student_rows = []
    for student in eligible_students:
        att = existing_records.get(student.id)
        current_status = att.status if att else 'present'
        current_remarks = att.remarks if att else ''
        student_rows.append({
            'student': student,
            'status': current_status,
            'remarks': current_remarks,
            'has_existing': bool(att)
        })

    # Recent audit logs for this session
    audit_logs = session.audit_logs.select_related('student', 'changed_by').order_by('-changed_at')[:10]

    context = {
        'session': session,
        'student_rows': student_rows,
        'audit_logs': audit_logs,
        'is_saved': session.is_attendance_saved,
        'enable_late': academy_settings.enable_late_status,
    }
    return render(request, 'academy/attendance/attendance_mark.html', context)


@login_required
def attendance_history(request):
    """
    Searchable and filterable attendance register view.
    """
    batch_filter = request.GET.get('batch', '')
    student_filter = request.GET.get('student', '')
    status_filter = request.GET.get('status', '')
    date_filter = request.GET.get('date', '')
    month_filter = request.GET.get('month', '')

    attendance_qs = Attendance.objects.all().select_related('session', 'session__batch', 'student')

    if batch_filter:
        attendance_qs = attendance_qs.filter(session__batch_id=batch_filter)
    if student_filter:
        attendance_qs = attendance_qs.filter(student_id=student_filter)
    if status_filter:
        attendance_qs = attendance_qs.filter(status=status_filter)
    if date_filter:
        attendance_qs = attendance_qs.filter(session__date=date_filter)
    if month_filter:
        try:
            yr, mo = [int(x) for x in month_filter.split('-')]
            attendance_qs = attendance_qs.filter(session__date__year=yr, session__date__month=mo)
        except ValueError:
            pass

    attendance_qs = attendance_qs.order_by('-session__date', 'student__first_name')

    paginator = Paginator(attendance_qs, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    batches = Batch.objects.filter(is_active=True)
    students = Student.objects.filter(status='active').order_by('first_name')

    context = {
        'page_obj': page_obj,
        'batches': batches,
        'students': students,
        'batch_filter': batch_filter,
        'student_filter': student_filter,
        'status_filter': status_filter,
        'date_filter': date_filter,
        'month_filter': month_filter,
    }
    return render(request, 'academy/attendance/attendance_history.html', context)


@login_required
def attendance_audit_list(request):
    """Lists recent attendance modification audit entries."""
    logs_qs = AttendanceAuditLog.objects.all().select_related('session', 'session__batch', 'student', 'changed_by').order_by('-changed_at')
    paginator = Paginator(logs_qs, 30)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'academy/attendance/attendance_audit_list.html', {'page_obj': page_obj})


# ==============================================================================
# REPORTS & ANALYTICS
# ==============================================================================

@login_required
def attendance_reports(request):
    """
    Detailed analytical reports:
    - Monthly Academy Attendance Register
    - Individual Student Attendance Breakdown
    - Batch Performance Summary
    """
    academy_settings = AcademySettings.get_settings()
    today = timezone.now().date()
    selected_month = request.GET.get('month', today.strftime('%Y-%m'))
    selected_batch_id = request.GET.get('batch', '')

    try:
        yr, mo = [int(x) for x in selected_month.split('-')]
    except ValueError:
        yr, mo = today.year, today.month

    m_start = date(yr, mo, 1)
    if mo == 12:
        m_end = date(yr + 1, 1, 1) - timedelta(days=1)
    else:
        m_end = date(yr, mo + 1, 1) - timedelta(days=1)

    batches = Batch.objects.filter(is_active=True)
    students_qs = Student.objects.filter(status__in=['active', 'paused'])

    if selected_batch_id:
        students_qs = students_qs.filter(enrollments__batch_id=selected_batch_id, enrollments__is_active=True)

    report_rows = []
    for st in students_qs.distinct():
        b_filter = Batch.objects.get(id=selected_batch_id) if selected_batch_id else None
        stats = calculate_student_attendance(st, start_date=m_start, end_date=m_end, batch=b_filter)
        report_rows.append(stats)

    context = {
        'report_rows': report_rows,
        'selected_month': selected_month,
        'selected_batch_id': selected_batch_id,
        'batches': batches,
        'threshold': academy_settings.attendance_threshold,
        'month_name': m_start.strftime('%B %Y'),
    }
    return render(request, 'academy/reports/attendance_reports.html', context)


# ==============================================================================
# LESSON DIARY
# ==============================================================================

@login_required
def lesson_list(request):
    batch_filter = request.GET.get('batch', '')
    taal_filter = request.GET.get('taal', '')
    query = request.GET.get('q', '').strip()

    lessons_qs = Lesson.objects.all().select_related('batch', 'taal', 'session')

    if batch_filter:
        lessons_qs = lessons_qs.filter(batch_id=batch_filter)
    if taal_filter:
        lessons_qs = lessons_qs.filter(taal_id=taal_filter)
    if query:
        lessons_qs = lessons_qs.filter(
            Q(topic__icontains=query) |
            Q(bol_notation__icontains=query) |
            Q(summary__icontains=query)
        )

    lessons_qs = lessons_qs.order_by('-date', '-created_at')

    paginator = Paginator(lessons_qs, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    batches = Batch.objects.filter(is_active=True)
    taals = Taal.objects.all()

    return render(request, 'academy/lessons/lesson_list.html', {
        'page_obj': page_obj,
        'batches': batches,
        'taals': taals,
        'batch_filter': batch_filter,
        'taal_filter': taal_filter,
        'query': query,
    })


@login_required
def lesson_create(request):
    session_id = request.GET.get('session')
    batch_id = request.GET.get('batch')
    initial = {}
    if session_id:
        session = get_object_or_404(ClassSession, id=session_id)
        initial['session'] = session
        initial['batch'] = session.batch
        initial['date'] = session.date
        initial['topic'] = session.lesson_topic
    elif batch_id:
        batch = get_object_or_404(Batch, id=batch_id)
        initial['batch'] = batch

    if request.method == 'POST':
        form = LessonForm(request.POST)
        if form.is_valid():
            lesson = form.save()
            messages.success(request, f"Lesson entry created for {lesson.batch.name}.")
            return redirect('lesson_detail', lesson_id=lesson.id)
    else:
        form = LessonForm(initial=initial)

    return render(request, 'academy/lessons/lesson_form.html', {'form': form, 'title': 'Record New Lesson'})


@login_required
def lesson_detail(request, lesson_id):
    lesson = get_object_or_404(Lesson, id=lesson_id)
    assignments = lesson.assignments.all()
    return render(request, 'academy/lessons/lesson_detail.html', {'lesson': lesson, 'assignments': assignments})


@login_required
def lesson_edit(request, lesson_id):
    lesson = get_object_or_404(Lesson, id=lesson_id)
    if request.method == 'POST':
        form = LessonForm(request.POST, instance=lesson)
        if form.is_valid():
            form.save()
            messages.success(request, "Lesson updated successfully.")
            return redirect('lesson_detail', lesson_id=lesson.id)
    else:
        form = LessonForm(instance=lesson)

    return render(request, 'academy/lessons/lesson_form.html', {'form': form, 'lesson': lesson, 'title': f'Edit Lesson: {lesson.topic}'})


# ==============================================================================
# PRACTICE ASSIGNMENTS
# ==============================================================================

@login_required
def assignment_list(request):
    status_filter = request.GET.get('status', '')
    batch_filter = request.GET.get('batch', '')
    student_filter = request.GET.get('student', '')

    assignments_qs = PracticeAssignment.objects.all().select_related('batch', 'student', 'taal')

    if status_filter:
        assignments_qs = assignments_qs.filter(status=status_filter)
    if batch_filter:
        assignments_qs = assignments_qs.filter(batch_id=batch_filter)
    if student_filter:
        assignments_qs = assignments_qs.filter(student_id=student_filter)

    assignments_qs = assignments_qs.order_by('due_date', '-created_at')

    paginator = Paginator(assignments_qs, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    batches = Batch.objects.filter(is_active=True)
    students = Student.objects.filter(status='active').order_by('first_name')

    return render(request, 'academy/assignments/assignment_list.html', {
        'page_obj': page_obj,
        'batches': batches,
        'students': students,
        'status_filter': status_filter,
        'batch_filter': batch_filter,
        'student_filter': student_filter,
        'today': timezone.now().date(),
    })


@login_required
def assignment_create(request):
    lesson_id = request.GET.get('lesson')
    initial = {}
    if lesson_id:
        lesson = get_object_or_404(Lesson, id=lesson_id)
        initial['related_lesson'] = lesson
        initial['batch'] = lesson.batch
        initial['taal'] = lesson.taal
        initial['composition_type'] = lesson.composition_type
        initial['due_date'] = timezone.now().date() + timedelta(days=7)

    if request.method == 'POST':
        form = PracticeAssignmentForm(request.POST)
        if form.is_valid():
            assignment = form.save()
            messages.success(request, f"Assignment '{assignment.title}' created.")
            return redirect('assignment_list')
    else:
        if not initial.get('due_date'):
            initial['due_date'] = timezone.now().date() + timedelta(days=7)
        form = PracticeAssignmentForm(initial=initial)

    return render(request, 'academy/assignments/assignment_form.html', {'form': form, 'title': 'Create Practice Assignment'})


@login_required
def assignment_edit(request, assignment_id):
    assignment = get_object_or_404(PracticeAssignment, id=assignment_id)
    if request.method == 'POST':
        form = PracticeAssignmentForm(request.POST, instance=assignment)
        if form.is_valid():
            form.save()
            messages.success(request, f"Assignment '{assignment.title}' updated.")
            return redirect('assignment_list')
    else:
        form = PracticeAssignmentForm(instance=assignment)

    return render(request, 'academy/assignments/assignment_form.html', {'form': form, 'assignment': assignment, 'title': f'Review Assignment: {assignment.title}'})


# ==============================================================================
# BOL & TAAL LIBRARY
# ==============================================================================

@login_required
def taal_list(request):
    seed_foundational_taals_and_compositions()
    taals = Taal.objects.all().prefetch_related('compositions')
    return render(request, 'academy/library/taal_list.html', {'taals': taals})


@login_required
def taal_create(request):
    if request.method == 'POST':
        form = TaalForm(request.POST)
        if form.is_valid():
            taal = form.save()
            messages.success(request, f"Taal '{taal.name}' added to library.")
            return redirect('taal_detail', taal_id=taal.id)
    else:
        form = TaalForm()
    return render(request, 'academy/library/taal_form.html', {'form': form, 'title': 'Add New Taal'})


@login_required
def taal_detail(request, taal_id):
    taal = get_object_or_404(Taal, id=taal_id)
    compositions = taal.compositions.all()
    return render(request, 'academy/library/taal_detail.html', {'taal': taal, 'compositions': compositions})


@login_required
def taal_edit(request, taal_id):
    taal = get_object_or_404(Taal, id=taal_id)
    if request.method == 'POST':
        form = TaalForm(request.POST, instance=taal)
        if form.is_valid():
            form.save()
            messages.success(request, f"Taal '{taal.name}' updated.")
            return redirect('taal_detail', taal_id=taal.id)
    else:
        form = TaalForm(instance=taal)
    return render(request, 'academy/library/taal_form.html', {'form': form, 'taal': taal, 'title': f'Edit Taal: {taal.name}'})


@login_required
def composition_list(request):
    taal_filter = request.GET.get('taal', '')
    category_filter = request.GET.get('category', '')
    difficulty_filter = request.GET.get('difficulty', '')
    query = request.GET.get('q', '').strip()

    compositions_qs = Composition.objects.all().select_related('taal')

    if taal_filter:
        compositions_qs = compositions_qs.filter(taal_id=taal_filter)
    if category_filter:
        compositions_qs = compositions_qs.filter(category=category_filter)
    if difficulty_filter:
        compositions_qs = compositions_qs.filter(difficulty=difficulty_filter)
    if query:
        compositions_qs = compositions_qs.filter(
            Q(title__icontains=query) |
            Q(bol_notation__icontains=query) |
            Q(practice_instructions__icontains=query)
        )

    compositions_qs = compositions_qs.order_by('taal', 'category', 'title')

    paginator = Paginator(compositions_qs, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    taals = Taal.objects.all()

    return render(request, 'academy/library/composition_list.html', {
        'page_obj': page_obj,
        'taals': taals,
        'category_choices': Composition.CATEGORY_CHOICES,
        'difficulty_choices': Student.LEVEL_CHOICES,
        'taal_filter': taal_filter,
        'category_filter': category_filter,
        'difficulty_filter': difficulty_filter,
        'query': query,
    })


@login_required
def composition_create(request):
    taal_id = request.GET.get('taal')
    initial = {}
    if taal_id:
        initial['taal'] = get_object_or_404(Taal, id=taal_id)

    if request.method == 'POST':
        form = CompositionForm(request.POST)
        if form.is_valid():
            composition = form.save()
            messages.success(request, f"Composition '{composition.title}' saved to library.")
            return redirect('composition_list')
    else:
        form = CompositionForm(initial=initial)

    return render(request, 'academy/library/composition_form.html', {'form': form, 'title': 'Add New Composition'})


@login_required
def composition_edit(request, composition_id):
    composition = get_object_or_404(Composition, id=composition_id)
    if request.method == 'POST':
        form = CompositionForm(request.POST, instance=composition)
        if form.is_valid():
            form.save()
            messages.success(request, f"Composition '{composition.title}' updated.")
            return redirect('composition_list')
    else:
        form = CompositionForm(instance=composition)

    return render(request, 'academy/library/composition_form.html', {'form': form, 'composition': composition, 'title': f'Edit Composition: {composition.title}'})


# ==============================================================================
# STUDENT PROGRESS
# ==============================================================================

@login_required
def progress_list(request):
    student_id = request.GET.get('student')
    progress_qs = StudentProgress.objects.all().select_related('student')

    if student_id:
        progress_qs = progress_qs.filter(student_id=student_id)

    progress_qs = progress_qs.order_by('-date', '-created_at')
    paginator = Paginator(progress_qs, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    students = Student.objects.filter(status='active').order_by('first_name')

    return render(request, 'academy/progress/progress_list.html', {
        'page_obj': page_obj,
        'students': students,
        'selected_student_id': student_id,
    })


@login_required
def progress_create(request):
    student_id = request.GET.get('student')
    initial = {}
    if student_id:
        student = get_object_or_404(Student, id=student_id)
        initial['student'] = student
        initial['current_level'] = student.level

    if request.method == 'POST':
        form = StudentProgressForm(request.POST)
        if form.is_valid():
            progress = form.save()
            messages.success(request, f"Progress milestone logged for {progress.student.full_name}.")
            return redirect('student_detail', student_id=progress.student.id)
    else:
        form = StudentProgressForm(initial=initial)

    return render(request, 'academy/progress/progress_form.html', {'form': form, 'title': 'Log Student Progress Milestone'})


# ==============================================================================
# PERFORMANCES & EXAMINATIONS
# ==============================================================================

@login_required
def performance_list(request):
    performances = PerformanceRecord.objects.all().select_related('student', 'batch').order_by('-event_date')
    return render(request, 'academy/performances/performance_list.html', {'performances': performances})


@login_required
def performance_create(request):
    if request.method == 'POST':
        form = PerformanceRecordForm(request.POST)
        if form.is_valid():
            perf = form.save()
            messages.success(request, f"Performance record '{perf.event_name}' saved.")
            return redirect('performance_list')
    else:
        form = PerformanceRecordForm()
    return render(request, 'academy/performances/performance_form.html', {'form': form, 'title': 'Record Musical Performance / Recital'})


@login_required
def exam_list(request):
    exams = ExaminationRecord.objects.all().select_related('student').order_by('-exam_date')
    return render(request, 'academy/performances/exam_list.html', {'exams': exams})


@login_required
def exam_create(request):
    if request.method == 'POST':
        form = ExaminationRecordForm(request.POST)
        if form.is_valid():
            exam = form.save()
            messages.success(request, f"Examination entry for {exam.student.full_name} saved.")
            return redirect('exam_list')
    else:
        form = ExaminationRecordForm()
    return render(request, 'academy/performances/exam_form.html', {'form': form, 'title': 'Record Board / Academy Examination'})


# ==============================================================================
# OPTIONAL FEE MANAGEMENT
# ==============================================================================

@login_required
def fee_dashboard(request):
    academy_settings = AcademySettings.get_settings()
    today = timezone.now().date()
    month_start = today.replace(day=1)
    year_start = today.replace(month=1, day=1)

    payments_qs = PaymentRecord.objects.filter(is_reversed=False).select_related('student', 'fee_plan')

    # Filters
    query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '')
    batch_filter = request.GET.get('batch', '')
    month_filter = request.GET.get('month', '')
    year_filter = request.GET.get('year', '')
    method_filter = request.GET.get('method', '')

    if query:
        payments_qs = payments_qs.filter(
            Q(student__first_name__icontains=query) |
            Q(student__last_name__icontains=query) |
            Q(student__student_id__icontains=query) |
            Q(student__guardian_name__icontains=query) |
            Q(receipt_number__icontains=query) |
            Q(transaction_reference__icontains=query)
        )

    if batch_filter:
        payments_qs = payments_qs.filter(student__enrollments__batch_id=batch_filter, student__enrollments__is_active=True)

    if month_filter:
        try:
            payments_qs = payments_qs.filter(fee_month=int(month_filter))
        except ValueError:
            pass

    if year_filter:
        try:
            payments_qs = payments_qs.filter(fee_year=int(year_filter))
        except ValueError:
            pass

    if method_filter:
        payments_qs = payments_qs.filter(payment_method=method_filter)

    # Status filter
    if status_filter == 'paid':
        payments_qs = [p for p in payments_qs if p.is_fully_paid]
    elif status_filter == 'partial':
        payments_qs = [p for p in payments_qs if p.is_partial]
    elif status_filter == 'pending':
        payments_qs = [p for p in payments_qs if p.is_pending]

    # Metrics calculated from all active (non-reversed) payments
    all_payments = PaymentRecord.objects.filter(is_reversed=False)
    collected_month = all_payments.filter(payment_date__gte=month_start, payment_date__lte=today).aggregate(s=Sum('amount_paid'))['s'] or Decimal('0.00')
    collected_year = all_payments.filter(payment_date__gte=year_start, payment_date__lte=today).aggregate(s=Sum('amount_paid'))['s'] or Decimal('0.00')
    total_due_all = all_payments.aggregate(s=Sum('amount_due'))['s'] or Decimal('0.00')
    total_paid_all = all_payments.aggregate(s=Sum('amount_paid'))['s'] or Decimal('0.00')
    outstanding_fees = max(Decimal('0.00'), total_due_all - total_paid_all)

    # Student fee status counts
    students = Student.objects.filter(status='active', is_archived=False)
    paid_count = 0
    pending_count = 0
    for s in students:
        s_p = all_payments.filter(student=s)
        s_due = s_p.aggregate(s=Sum('amount_due'))['s'] or Decimal('0.00')
        s_paid = s_p.aggregate(s=Sum('amount_paid'))['s'] or Decimal('0.00')
        if s_due > 0 and s_paid >= s_due:
            paid_count += 1
        elif s_due > s_paid:
            pending_count += 1

    # Pagination
    if isinstance(payments_qs, list):
        paginator = Paginator(payments_qs, 20)
    else:
        paginator = Paginator(payments_qs.order_by('-payment_date', '-id'), 20)

    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    batches = Batch.objects.filter(is_active=True, is_archived=False)

    return render(request, 'academy/fees/fee_dashboard.html', {
        'page_obj': page_obj,
        'collected_month': collected_month,
        'collected_year': collected_year,
        'outstanding_fees': outstanding_fees,
        'paid_count': paid_count,
        'pending_count': pending_count,
        'query': query,
        'status_filter': status_filter,
        'batch_filter': batch_filter,
        'month_filter': month_filter,
        'year_filter': year_filter,
        'method_filter': method_filter,
        'batches': batches,
        'methods': PaymentRecord.METHOD_CHOICES,
        'months': PaymentRecordForm.MONTH_CHOICES,
        'years': list(range(today.year - 2, today.year + 2)),
    })


@login_required
def payment_create(request):
    academy_settings = AcademySettings.get_settings()
    student_id = request.GET.get('student')
    initial = {
        'payment_date': timezone.now().date(),
        'fee_month': timezone.now().month,
        'fee_year': timezone.now().year,
        'idempotency_key': f"pay_{uuid.uuid4().hex[:16]}",
    }
    if student_id:
        student = get_object_or_404(Student, id=student_id)
        initial['student'] = student
        initial['amount_due'] = student.monthly_fee
        initial['amount_paid'] = student.monthly_fee

    if request.method == 'POST':
        form = PaymentRecordForm(request.POST)
        if form.is_valid():
            # Duplicate prevention check via idempotency key
            idempotency_key = form.cleaned_data.get('idempotency_key')
            if idempotency_key:
                existing_recent = PaymentRecord.objects.filter(
                    idempotency_key=idempotency_key,
                    created_at__gte=timezone.now() - timedelta(minutes=5)
                ).first()
                if existing_recent:
                    messages.warning(request, f"Duplicate submission prevented. Viewing saved receipt: {existing_recent.receipt_number}.")
                    return redirect('receipt_view', payment_id=existing_recent.id)

            payment = form.save()
            messages.success(request, f"Fee payment recorded successfully! Receipt #{payment.receipt_number} issued for {payment.student.full_name}.")
            return redirect('receipt_view', payment_id=payment.id)
    else:
        form = PaymentRecordForm(initial=initial)

    return render(request, 'academy/fees/payment_form.html', {'form': form, 'title': 'Record Fee Payment'})


@login_required
def receipt_view(request, payment_id):
    """
    Displays the official e-receipt with print, PDF download, and WhatsApp sharing options.
    """
    payment = get_object_or_404(PaymentRecord, id=payment_id)
    academy_settings = AcademySettings.get_settings()
    return render(request, 'academy/fees/receipt_detail.html', {
        'payment': payment,
        'academy_settings': academy_settings,
        'title': f'E-Receipt: {payment.receipt_number}'
    })


@login_required
def receipt_download_pdf(request, payment_id):
    """
    Streams a ReportLab PDF receipt for downloading.
    """
    payment = get_object_or_404(PaymentRecord, id=payment_id)
    pdf_bytes = generate_receipt_pdf(payment)
    filename = f"RSV_Receipt_{payment.receipt_number}.pdf"
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def receipt_send_whatsapp(request, payment_id):
    """
    Dispatches the official receipt details to the student's guardian WhatsApp number.
    """
    payment = get_object_or_404(PaymentRecord, id=payment_id)
    res = send_payment_receipt_whatsapp(payment)
    if res.get('status') in ['sent', 'simulated']:
        sim_msg = " [Simulated in Test Mode]" if res.get('simulated') else ""
        messages.success(request, f"Payment receipt sent to {payment.student.guardian_name or 'Parent'} via WhatsApp{sim_msg}!")
    else:
        messages.warning(request, f"WhatsApp delivery notice: {res.get('error', 'Could not deliver')}. PDF receipt is still available.")
    return redirect('receipt_view', payment_id=payment.id)


@login_required
def payment_reverse_view(request, payment_id):
    """
    Safely marks a payment as reversed/corrected with a recorded audit reason.
    Never silently erases a financial transaction.
    """
    payment = get_object_or_404(PaymentRecord, id=payment_id)
    if request.method == 'POST':
        reason = request.POST.get('reversal_reason', '').strip()
        if not reason:
            messages.error(request, "Please provide a reason for correcting or reversing this payment.")
            return redirect('receipt_view', payment_id=payment.id)
        payment.is_reversed = True
        payment.reversal_reason = reason
        payment.save()
        messages.warning(request, f"Payment #{payment.receipt_number} has been reversed. Audit note recorded.")
        return redirect('fee_dashboard')
    return redirect('receipt_view', payment_id=payment.id)


@login_required
def fee_plan_create(request):
    if request.method == 'POST':
        form = FeePlanForm(request.POST)
        if form.is_valid():
            plan = form.save()
            messages.success(request, f"Fee plan '{plan.name}' created.")
            return redirect('fee_dashboard')
    else:
        form = FeePlanForm()
    return render(request, 'academy/fees/fee_plan_form.html', {'form': form, 'title': 'Add Fee Structure'})


# ==============================================================================
# REPORTING & ANALYTICS VIEWS
# ==============================================================================

@login_required
def attendance_reports(request):
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    batch_id = request.GET.get('batch')

    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else None
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else None

    data = get_attendance_report_data(start_date=start_date, end_date=end_date, batch_id=batch_id)
    batches = Batch.objects.filter(is_active=True, is_archived=False)

    return render(request, 'academy/reports/attendance_reports.html', {
        'data': data,
        'batches': batches,
        'selected_batch_id': batch_id,
        'title': 'Attendance Reports'
    })


@login_required
def fees_reports(request):
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    batch_id = request.GET.get('batch')

    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else None
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else None

    data = get_fees_report_data(start_date=start_date, end_date=end_date, batch_id=batch_id)
    batches = Batch.objects.filter(is_active=True, is_archived=False)

    return render(request, 'academy/reports/fees_reports.html', {
        'data': data,
        'batches': batches,
        'selected_batch_id': batch_id,
        'title': 'Fees & Financial Reports'
    })


@login_required
def timetable_reports(request):
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    batch_id = request.GET.get('batch')

    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else None
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else None

    data = get_timetable_report_data(start_date=start_date, end_date=end_date, batch_id=batch_id)
    batches = Batch.objects.filter(is_active=True, is_archived=False)

    return render(request, 'academy/reports/timetable_reports.html', {
        'data': data,
        'batches': batches,
        'selected_batch_id': batch_id,
        'title': 'Timetable Reports'
    })


@login_required
def export_fees_csv(request):
    headers = ['Receipt No', 'Date', 'Student ID', 'Student Name', 'Billing Period', 'Amount Due (INR)', 'Amount Paid (INR)', 'Balance (INR)', 'Payment Method', 'Transaction Ref']
    rows = []
    for p in PaymentRecord.objects.filter(is_reversed=False).select_related('student').order_by('-payment_date'):
        rows.append([
            p.receipt_number,
            p.payment_date.strftime('%Y-%m-%d') if p.payment_date else '',
            p.student.student_id,
            p.student.full_name,
            p.billing_period,
            str(p.amount_due),
            str(p.amount_paid),
            str(p.outstanding_balance),
            p.get_payment_method_display(),
            p.transaction_reference or ''
        ])
    return generate_safe_csv_response('rsv_fees_register', headers, rows)


# ==============================================================================
# WHATSAPP INTEGRATION & CHATBOT VIEWS
# ==============================================================================

@login_required
def whatsapp_hub(request):
    """
    Management view for WhatsApp Business Platform integration, test mode, and message history.
    """
    test_mode = getattr(settings, 'WHATSAPP_TEST_MODE', True)
    has_token = bool(getattr(settings, 'WHATSAPP_ACCESS_TOKEN', '') and getattr(settings, 'WHATSAPP_PHONE_NUMBER_ID', ''))

    logs = WhatsAppMessageLog.objects.all().select_related('student', 'session', 'payment')
    type_filter = request.GET.get('type')
    status_filter = request.GET.get('status')
    if type_filter:
        logs = logs.filter(message_type=type_filter)
    if status_filter:
        logs = logs.filter(status=status_filter)

    paginator = Paginator(logs, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    today = timezone.now().date()
    today_sessions = ClassSession.objects.filter(date=today, status='scheduled').select_related('batch')

    return render(request, 'academy/whatsapp/whatsapp_hub.html', {
        'test_mode': test_mode,
        'has_token': has_token,
        'page_obj': page_obj,
        'today_sessions': today_sessions,
        'type_filter': type_filter,
        'status_filter': status_filter,
        'phone_number_id': getattr(settings, 'WHATSAPP_PHONE_NUMBER_ID', '') or 'Not configured',
        'api_version': getattr(settings, 'WHATSAPP_API_VERSION', 'v21.0'),
    })


@login_required
def whatsapp_send_reminder(request, session_id):
    """
    Sends WhatsApp reminders for a specific class session to all enrolled students.
    """
    session = get_object_or_404(ClassSession, id=session_id)
    results = send_class_reminder_whatsapp(session)
    sent_count = sum(1 for r in results if r.get('status') in ['sent', 'simulated'])
    skipped_count = sum(1 for r in results if r.get('status') == 'skipped')

    if sent_count > 0:
        messages.success(request, f"Dispatched {sent_count} class reminder(s) for {session.batch.name} on {session.date}.")
    if skipped_count > 0:
        messages.info(request, f"{skipped_count} reminder(s) skipped (already sent or missing phone number).")

    return redirect('whatsapp_hub')


@login_required
def whatsapp_retry_log(request, log_id):
    """
    Retries sending a previously failed WhatsApp message.
    """
    log = get_object_or_404(WhatsAppMessageLog, id=log_id)
    res = send_whatsapp_message(
        to_number=log.recipient_phone,
        message_text=log.message_text,
        message_type=log.message_type,
        student=log.student,
        session=log.session,
        payment=log.payment
    )
    if res.get('status') in ['sent', 'simulated']:
        messages.success(request, f"Retry attempt completed: Status is {res['status']}.")
    else:
        messages.error(request, f"Retry failed: {res.get('error', 'Unknown error')}")
    return redirect('whatsapp_hub')


@login_required
def whatsapp_simulator(request):
    """
    Interactive in-browser simulator for teachers to test WhatsApp chatbot parent queries.
    """
    response_text = None
    query_text = ""
    phone_number = "9876543210"

    if request.method == 'POST':
        phone_number = request.POST.get('phone_number', '').strip()
        query_text = request.POST.get('query_text', '').strip()
        if query_text:
            response_text = process_chatbot_query(phone_number, query_text)

    sample_students = Student.objects.filter(status='active')[:5]

    return render(request, 'academy/whatsapp/whatsapp_simulator.html', {
        'response_text': response_text,
        'query_text': query_text,
        'phone_number': phone_number,
        'sample_students': sample_students,
    })


@csrf_exempt
def whatsapp_webhook(request):
    """
    Official Meta WhatsApp Business Cloud API Webhook endpoint.
    GET: Handles Webhook verification challenge from Meta.
    POST: Processes incoming parent chatbot messages.
    """
    if request.method == 'GET':
        mode = request.GET.get('hub.mode')
        token = request.GET.get('hub.verify_token')
        challenge = request.GET.get('hub.challenge')
        configured_token = getattr(settings, 'WHATSAPP_VERIFY_TOKEN', '')

        if mode == 'subscribe' and token == configured_token:
            return HttpResponse(challenge, content_type='text/plain', status=200)
        return HttpResponse('Verification token mismatch', status=403)

    elif request.method == 'POST':
        try:
            body = json.loads(request.body.decode('utf-8'))
            entries = body.get('entry', [])
            for entry in entries:
                changes = entry.get('changes', [])
                for change in changes:
                    value = change.get('value', {})
                    messages_list = value.get('messages', [])
                    for msg in messages_list:
                        from_number = msg.get('from')
                        text_body = msg.get('text', {}).get('body', '')
                        if from_number and text_body:
                            # Process query and reply
                            reply_text = process_chatbot_query(from_number, text_body)
                            send_whatsapp_message(
                                to_number=from_number,
                                message_text=reply_text,
                                message_type='chatbot_reply'
                            )
            return HttpResponse('EVENT_RECEIVED', status=200)
        except Exception as e:
            return HttpResponse(str(e), status=400)

    return HttpResponse('Method not allowed', status=405)



# ==============================================================================
# ALERTS & NOTIFICATIONS
# ==============================================================================

@login_required
def alert_list(request):
    refresh_academy_alerts()
    alerts = AcademyAlert.objects.all().order_by('is_dismissed', '-created_at')
    return render(request, 'academy/alerts/alert_list.html', {'alerts': alerts})


@login_required
def alert_dismiss(request, alert_id):
    alert = get_object_or_404(AcademyAlert, id=alert_id)
    alert.is_dismissed = True
    alert.save()
    messages.info(request, "Alert marked as reviewed/dismissed.")
    return redirect('alert_list')


# ==============================================================================
# BACKUP & DATA MANAGEMENT
# ==============================================================================

@login_required
def backup_hub(request):
    backups = list_database_backups()
    db_path = settings.DATABASES['default']['NAME']
    db_size_kb = round(os.path.getsize(db_path) / 1024, 2) if os.path.exists(db_path) else 0

    return render(request, 'academy/backups/backup_hub.html', {
        'backups': backups,
        'db_size_kb': db_size_kb,
        'db_path': str(db_path),
    })


@login_required
def backup_create_view(request):
    if request.method == 'POST':
        try:
            res = create_database_backup()
            messages.success(request, f"Database backup successfully created: {res['filename']} ({res['size_kb']} KB).")
        except Exception as e:
            messages.error(request, f"Backup failed: {str(e)}")
    return redirect('backup_hub')


@login_required
def backup_download_view(request, filename):
    backups_dir = settings.BACKUPS_DIR
    safe_filename = os.path.basename(filename)
    filepath = os.path.join(backups_dir, safe_filename)

    if not os.path.exists(filepath):
        raise Http404("Backup file not found.")

    response = FileResponse(open(filepath, 'rb'), as_attachment=True, filename=safe_filename)
    return response


# ==============================================================================
# CSV EXPORT VIEWS (WITH FORMULA INJECTION PREVENTION)
# ==============================================================================

@login_required
def export_students_csv(request):
    headers = ['Student ID', 'Full Name', 'Level', 'Status', 'Phone', 'Email', 'Enrollment Date', 'Guardian Name', 'Guardian Phone']
    rows = []
    for s in Student.objects.all().order_by('student_id'):
        rows.append([
            s.student_id,
            s.full_name,
            s.get_level_display(),
            s.get_status_display(),
            s.phone,
            s.email,
            s.enrollment_date.strftime('%Y-%m-%d'),
            s.guardian_name,
            s.guardian_phone
        ])
    return generate_safe_csv_response('taal_students', headers, rows)


@login_required
def export_attendance_csv(request):
    headers = ['Date', 'Batch', 'Student ID', 'Student Name', 'Status', 'Remarks', 'Marked At']
    rows = []
    for a in Attendance.objects.select_related('session', 'session__batch', 'student').order_by('-session__date'):
        rows.append([
            a.session.date.strftime('%Y-%m-%d'),
            a.session.batch.name,
            a.student.student_id,
            a.student.full_name,
            a.get_status_display(),
            a.remarks,
            a.created_at.strftime('%Y-%m-%d %H:%M')
        ])
    return generate_safe_csv_response('taal_attendance_register', headers, rows)


@login_required
def export_monthly_attendance_csv(request):
    headers = ['Student ID', 'Student Name', 'Status', 'Eligible Conducted Classes', 'Attended (Present)', 'Absent', 'Leave', 'Attendance Percentage']
    rows = []
    for s in Student.objects.filter(status__in=['active', 'paused']):
        stats = calculate_student_attendance(s)
        pct_str = f"{stats['percentage']}%" if stats['percentage'] is not None else "N/A"
        rows.append([
            s.student_id,
            s.full_name,
            s.get_status_display(),
            stats['eligible_count'],
            stats['present_count'],
            stats['absent_count'],
            stats['leave_count'],
            pct_str
        ])
    return generate_safe_csv_response('taal_monthly_attendance_summary', headers, rows)


# ==============================================================================
# SETTINGS
# ==============================================================================

@login_required
def settings_view(request):
    settings_obj = AcademySettings.get_settings()
    if request.method == 'POST':
        form = AcademySettingsForm(request.POST, instance=settings_obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Academy settings saved successfully.")
            return redirect('settings')
    else:
        form = AcademySettingsForm(instance=settings_obj)

    return render(request, 'academy/settings/settings.html', {'form': form, 'settings_obj': settings_obj})


# ==============================================================================
# PWA (PROGRESSIVE WEB APP) & MOBILE SHELL VIEWS
# ==============================================================================

def manifest_view(request):
    """Serves the PWA Web App Manifest at root scope /manifest.json."""
    manifest_path = os.path.join(settings.BASE_DIR, 'academy', 'static', 'academy', 'manifest.json')
    try:
        with open(manifest_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return HttpResponse(content, content_type='application/manifest+json')
    except Exception:
        return HttpResponse('{}', content_type='application/manifest+json')


def service_worker_view(request):
    """Serves the Service Worker at root scope /sw.js with no-cache header."""
    sw_path = os.path.join(settings.BASE_DIR, 'academy', 'static', 'academy', 'js', 'sw.js')
    try:
        with open(sw_path, 'r', encoding='utf-8') as f:
            content = f.read()
        resp = HttpResponse(content, content_type='application/javascript')
        resp['Service-Worker-Allowed'] = '/'
        resp['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return resp
    except Exception:
        return HttpResponse('// sw unavailable', content_type='application/javascript')


def offline_view(request):
    """Friendly offline fallback page shown when user is disconnected."""
    return render(request, 'academy/offline.html')

