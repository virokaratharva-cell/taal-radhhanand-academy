from django.contrib import admin
from .models import (
    AcademySettings, Student, Batch, BatchEnrollment, BatchRecurringSchedule,
    ClassSession, Attendance, AttendanceAuditLog,
    Taal, Composition, Lesson, PracticeAssignment,
    StudentProgress, PerformanceRecord, ExaminationRecord,
    FeePlan, PaymentRecord, AcademyAlert, WhatsAppMessageLog, ChatbotVerificationCode
)


@admin.register(AcademySettings)
class AcademySettingsAdmin(admin.ModelAdmin):
    list_display = ('academy_name', 'teacher_name', 'attendance_threshold', 'enable_fees')


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ('student_id', 'full_name', 'level', 'status', 'enrollment_date', 'phone', 'guardian_whatsapp')
    search_fields = ('student_id', 'first_name', 'last_name', 'phone', 'email', 'guardian_whatsapp')
    list_filter = ('status', 'level', 'is_archived')


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ('batch_id', 'name', 'course', 'capacity', 'level', 'regular_day', 'start_time', 'end_time', 'is_active', 'is_archived')
    list_filter = ('is_active', 'is_archived', 'regular_day', 'level')


@admin.register(BatchRecurringSchedule)
class BatchRecurringScheduleAdmin(admin.ModelAdmin):
    list_display = ('batch', 'day_of_week', 'start_time', 'end_time', 'duration_minutes', 'is_active')
    list_filter = ('day_of_week', 'is_active')


@admin.register(BatchEnrollment)
class BatchEnrollmentAdmin(admin.ModelAdmin):
    list_display = ('student', 'batch', 'enrolled_date', 'left_date', 'is_active')
    list_filter = ('is_active', 'batch')


@admin.register(ClassSession)
class ClassSessionAdmin(admin.ModelAdmin):
    list_display = ('batch', 'date', 'start_time', 'status', 'is_rescheduled', 'lesson_topic')
    list_filter = ('status', 'is_rescheduled', 'batch', 'date')


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ('student', 'session', 'status', 'marked_by', 'created_at')
    list_filter = ('status', 'session__batch', 'session__date')


@admin.register(AttendanceAuditLog)
class AttendanceAuditLogAdmin(admin.ModelAdmin):
    list_display = ('student', 'session', 'old_status', 'new_status', 'changed_by', 'changed_at')
    list_filter = ('changed_at',)


@admin.register(Taal)
class TaalAdmin(admin.ModelAdmin):
    list_display = ('name', 'matras', 'vibhag_structure', 'level')
    search_fields = ('name',)


@admin.register(Composition)
class CompositionAdmin(admin.ModelAdmin):
    list_display = ('title', 'taal', 'category', 'difficulty')
    list_filter = ('taal', 'category', 'difficulty')


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ('topic', 'batch', 'date', 'taal')
    list_filter = ('batch', 'taal', 'date')


@admin.register(PracticeAssignment)
class PracticeAssignmentAdmin(admin.ModelAdmin):
    list_display = ('title', 'batch', 'student', 'due_date', 'status')
    list_filter = ('status', 'due_date')


@admin.register(StudentProgress)
class StudentProgressAdmin(admin.ModelAdmin):
    list_display = ('student', 'date', 'current_level')


@admin.register(PerformanceRecord)
class PerformanceRecordAdmin(admin.ModelAdmin):
    list_display = ('event_name', 'student', 'batch', 'event_date', 'venue')


@admin.register(ExaminationRecord)
class ExaminationRecordAdmin(admin.ModelAdmin):
    list_display = ('student', 'exam_name', 'exam_date', 'mock_result')


@admin.register(FeePlan)
class FeePlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'amount', 'billing_frequency', 'is_active')


@admin.register(PaymentRecord)
class PaymentRecordAdmin(admin.ModelAdmin):
    list_display = ('receipt_number', 'student', 'billing_period', 'amount_due', 'amount_paid', 'payment_date', 'payment_method', 'is_reversed')
    list_filter = ('payment_method', 'payment_date', 'is_reversed')
    search_fields = ('receipt_number', 'student__first_name', 'student__last_name', 'transaction_reference')


@admin.register(AcademyAlert)
class AcademyAlertAdmin(admin.ModelAdmin):
    list_display = ('title', 'alert_type', 'severity', 'is_dismissed', 'created_at')
    list_filter = ('severity', 'is_dismissed', 'alert_type')


@admin.register(WhatsAppMessageLog)
class WhatsAppMessageLogAdmin(admin.ModelAdmin):
    list_display = ('recipient_phone', 'message_type', 'status', 'created_at', 'provider_message_id')
    list_filter = ('message_type', 'status', 'created_at')
    search_fields = ('recipient_phone', 'recipient_name', 'message_text')


@admin.register(ChatbotVerificationCode)
class ChatbotVerificationCodeAdmin(admin.ModelAdmin):
    list_display = ('phone_number', 'code', 'is_verified', 'created_at', 'expires_at', 'attempts')
    list_filter = ('is_verified',)
    search_fields = ('phone_number',)

