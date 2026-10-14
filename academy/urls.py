from django.urls import path
from . import views

urlpatterns = [
    # Dashboard and Auth
    path('', views.dashboard_view, name='dashboard'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # Student Management
    path('students/', views.student_list, name='student_list'),
    path('students/add/', views.student_create, name='student_create'),
    path('students/<int:student_id>/', views.student_detail, name='student_detail'),
    path('students/<int:student_id>/edit/', views.student_edit, name='student_edit'),
    path('students/<int:student_id>/archive/', views.student_archive_toggle, name='student_archive_toggle'),
    path('students/<int:student_id>/print/', views.student_print, name='student_print'),
    path('students/export/csv/', views.export_students_csv, name='export_students_csv'),

    # Batch Management
    path('batches/', views.batch_list, name='batch_list'),
    path('batches/add/', views.batch_create, name='batch_create'),
    path('batches/<int:batch_id>/', views.batch_detail, name='batch_detail'),
    path('batches/<int:batch_id>/edit/', views.batch_edit, name='batch_edit'),
    path('batches/<int:batch_id>/delete/', views.batch_delete, name='batch_delete'),
    path('batches/<int:batch_id>/archive/', views.batch_archive_toggle, name='batch_archive_toggle'),
    path('batches/<int:batch_id>/assign/', views.batch_assign_student, name='batch_assign_student'),
    path('batches/<int:batch_id>/remove/<int:student_id>/', views.batch_remove_student, name='batch_remove_student'),
    path('batches/<int:batch_id>/schedules/add/', views.batch_schedule_add, name='batch_schedule_add'),
    path('batches/schedules/<int:rule_id>/delete/', views.batch_schedule_delete, name='batch_schedule_delete'),

    # Class Scheduling & Automatic Timetable
    path('sessions/', views.session_list, name='session_list'),
    path('sessions/generate/', views.sessions_generate_view, name='sessions_generate'),
    path('sessions/add/', views.session_create, name='session_create'),
    path('sessions/<int:session_id>/edit/', views.session_edit, name='session_edit'),
    path('sessions/<int:session_id>/reschedule/', views.session_reschedule, name='session_reschedule'),
    path('sessions/<int:session_id>/conduct/', views.session_mark_conducted, name='session_mark_conducted'),
    path('sessions/<int:session_id>/cancel/', views.session_cancel, name='session_cancel'),

    # Daily Attendance Management
    path('attendance/', views.attendance_hub, name='attendance_hub'),
    path('attendance/mark/<int:session_id>/', views.attendance_mark, name='attendance_mark'),
    path('attendance/history/', views.attendance_history, name='attendance_history'),
    path('attendance/audits/', views.attendance_audit_list, name='attendance_audit_list'),
    path('attendance/export/csv/', views.export_attendance_csv, name='export_attendance_csv'),
    path('attendance/export/monthly-csv/', views.export_monthly_attendance_csv, name='export_monthly_attendance_csv'),

    # Fees & Payments Management
    path('fees/', views.fee_dashboard, name='fee_dashboard'),
    path('fees/payments/add/', views.payment_create, name='payment_create'),
    path('fees/plans/add/', views.fee_plan_create, name='fee_plan_create'),
    path('fees/receipts/<int:payment_id>/', views.receipt_view, name='receipt_view'),
    path('fees/receipts/<int:payment_id>/pdf/', views.receipt_download_pdf, name='receipt_download_pdf'),
    path('fees/receipts/<int:payment_id>/whatsapp/', views.receipt_send_whatsapp, name='receipt_send_whatsapp'),
    path('fees/payments/<int:payment_id>/reverse/', views.payment_reverse_view, name='payment_reverse'),
    path('fees/export/csv/', views.export_fees_csv, name='export_fees_csv'),

    # Reports & Analytics
    path('reports/', views.attendance_reports, name='attendance_reports'),
    path('reports/attendance/', views.attendance_reports, name='reports_attendance'),
    path('reports/fees/', views.fees_reports, name='fees_reports'),
    path('reports/timetable/', views.timetable_reports, name='timetable_reports'),

    # WhatsApp Business & Chatbot Integration
    path('whatsapp/', views.whatsapp_hub, name='whatsapp_hub'),
    path('whatsapp/send-reminder/<int:session_id>/', views.whatsapp_send_reminder, name='whatsapp_send_reminder'),
    path('whatsapp/retry/<int:log_id>/', views.whatsapp_retry_log, name='whatsapp_retry_log'),
    path('whatsapp/simulator/', views.whatsapp_simulator, name='whatsapp_simulator'),
    path('whatsapp/webhook/', views.whatsapp_webhook, name='whatsapp_webhook'),

    # Lesson Diary
    path('lessons/', views.lesson_list, name='lesson_list'),
    path('lessons/add/', views.lesson_create, name='lesson_create'),
    path('lessons/<int:lesson_id>/', views.lesson_detail, name='lesson_detail'),
    path('lessons/<int:lesson_id>/edit/', views.lesson_edit, name='lesson_edit'),

    # Practice Assignments
    path('assignments/', views.assignment_list, name='assignment_list'),
    path('assignments/add/', views.assignment_create, name='assignment_create'),
    path('assignments/<int:assignment_id>/edit/', views.assignment_edit, name='assignment_edit'),

    # Bol & Taal Library
    path('library/taals/', views.taal_list, name='taal_list'),
    path('library/taals/add/', views.taal_create, name='taal_create'),
    path('library/taals/<int:taal_id>/', views.taal_detail, name='taal_detail'),
    path('library/taals/<int:taal_id>/edit/', views.taal_edit, name='taal_edit'),
    path('library/compositions/', views.composition_list, name='composition_list'),
    path('library/compositions/add/', views.composition_create, name='composition_create'),
    path('library/compositions/<int:composition_id>/edit/', views.composition_edit, name='composition_edit'),

    # Student Progress
    path('progress/', views.progress_list, name='progress_list'),
    path('progress/add/', views.progress_create, name='progress_create'),

    # Performances & Examinations
    path('performances/', views.performance_list, name='performance_list'),
    path('performances/add/', views.performance_create, name='performance_create'),
    path('examinations/', views.exam_list, name='exam_list'),
    path('examinations/add/', views.exam_create, name='exam_create'),

    # Internal Alerts & Notifications
    path('alerts/', views.alert_list, name='alert_list'),
    path('alerts/<int:alert_id>/dismiss/', views.alert_dismiss, name='alert_dismiss'),

    # Backup & Data Management
    path('backups/', views.backup_hub, name='backup_hub'),
    path('backups/create/', views.backup_create_view, name='backup_create'),
    path('backups/download/<str:filename>/', views.backup_download_view, name='backup_download'),

    # Academy Settings
    path('settings/', views.settings_view, name='settings'),

    # PWA (Progressive Web App) & Mobile Shell
    path('manifest.json', views.manifest_view, name='manifest_json'),
    path('sw.js', views.service_worker_view, name='service_worker_js'),
    path('offline/', views.offline_view, name='offline_view'),
]

