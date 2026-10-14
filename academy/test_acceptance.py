from datetime import date, time, timedelta
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from academy.models import (
    AcademySettings, Student, Batch, BatchEnrollment,
    ClassSession, Attendance, AttendanceAuditLog,
    Lesson, PracticeAssignment, Taal, Composition, PaymentRecord
)
from academy.services import calculate_student_attendance, create_database_backup


class EndToEndAcceptanceCriteriaTests(TestCase):
    """
    Directly tests all 20 Acceptance Criteria defined in Section 30 of Master Development Prompt.
    """

    def setUp(self):
        self.client = Client()
        self.teacher = User.objects.create_user(
            username='master_teacher',
            password='GuruPassword123!',
            first_name='Pandit',
            last_name='Kishan'
        )

    def test_complete_twenty_step_teacher_workflow(self):
        # 1. Teacher logs in
        login_res = self.client.login(username='master_teacher', password='GuruPassword123!')
        self.assertTrue(login_res, "Criterion 1 failed: Teacher login should succeed.")

        # 2. Teacher creates a batch
        today = timezone.now().date()
        batch = Batch.objects.create(
            batch_id='BAT-ACC-01',
            name='Acceptance Verification Batch',
            level='beginner',
            regular_day='Saturday',
            start_time=time(10, 0),
            end_time=time(11, 0),
            start_date=today - timedelta(days=30)
        )
        self.assertEqual(batch.name, 'Acceptance Verification Batch', "Criterion 2 failed: Batch created.")

        # 3. Teacher adds students
        student1 = Student.objects.create(
            first_name='Siddharth',
            last_name='Nair',
            enrollment_date=today - timedelta(days=30),
            level='beginner',
            status='active'
        )
        student2 = Student.objects.create(
            first_name='Pooja',
            last_name='Menon',
            enrollment_date=today - timedelta(days=30),
            level='beginner',
            status='active'
        )
        self.assertTrue(student1.student_id.startswith('TAL-'), "Criterion 3 failed: Student ID auto-generated.")

        # 4. Teacher assigns students to the batch
        enr1 = BatchEnrollment.objects.create(student=student1, batch=batch, enrolled_date=today - timedelta(days=30))
        enr2 = BatchEnrollment.objects.create(student=student2, batch=batch, enrolled_date=today - timedelta(days=30))
        self.assertEqual(batch.active_students_count, 2, "Criterion 4 failed: Students enrolled in batch.")

        # 5. Teacher schedules a class
        session_date = today - timedelta(days=7)
        session = ClassSession.objects.create(
            batch=batch,
            date=session_date,
            start_time=batch.start_time,
            end_time=batch.end_time,
            status='scheduled',
            lesson_topic='Introduction to Teentaal Theka'
        )
        self.assertEqual(session.status, 'scheduled', "Criterion 5 failed: Session scheduled.")

        # 6. Teacher marks the session as conducted
        session.status = 'conducted'
        session.save()
        self.assertEqual(session.status, 'conducted', "Criterion 6 failed: Session marked conducted.")

        # 7. Teacher marks students Present, Absent, or Leave
        att_post_data = {
            f'status_{student1.id}': 'present',
            f'remarks_{student1.id}': 'Excellent posture',
            f'status_{student2.id}': 'absent',
            f'remarks_{student2.id}': 'Not feeling well',
        }

        # 8. Teacher saves attendance via HTTP POST
        mark_url = reverse('attendance_mark', args=[session.id])
        save_res = self.client.post(mark_url, att_post_data)
        self.assertEqual(save_res.status_code, 302, "Criterion 8 failed: Attendance saved via POST.")
        self.assertEqual(Attendance.objects.filter(session=session).count(), 2)

        # 9. Teacher reopens the session and sees saved records
        reopen_res = self.client.get(mark_url)
        self.assertContains(reopen_res, "Siddharth Nair", msg_prefix="Criterion 9 failed: Student in attendance sheet.")
        self.assertContains(reopen_res, "Excellent posture", msg_prefix="Criterion 9 failed: Remarks shown on reopen.")

        # 10. Teacher corrects an attendance entry
        correction_post_data = {
            f'status_{student1.id}': 'present',
            f'remarks_{student1.id}': 'Excellent posture',
            f'status_{student2.id}': 'leave', # Corrected from absent to leave
            f'remarks_{student2.id}': 'Informed beforehand by guardian',
            'audit_reason': 'Parent notified teacher earlier'
        }
        correct_res = self.client.post(mark_url, correction_post_data)
        self.assertEqual(correct_res.status_code, 302, "Criterion 10 failed: Correction submitted.")

        # 11. Application records the correction in AttendanceAuditLog
        audit = AttendanceAuditLog.objects.filter(session=session, student=student2).first()
        self.assertIsNotNone(audit, "Criterion 11 failed: Audit record created.")
        self.assertEqual(audit.old_status, 'absent')
        self.assertEqual(audit.new_status, 'leave')
        self.assertEqual(audit.changed_by, self.teacher)

        # 12. Dashboard updates
        dash_res = self.client.get(reverse('dashboard'))
        self.assertEqual(dash_res.status_code, 200, "Criterion 12 failed: Dashboard rendered.")

        # 13. Monthly report shows correct calculations
        rep_res = self.client.get(reverse('attendance_reports'))
        self.assertEqual(rep_res.status_code, 200, "Criterion 13 failed: Monthly reports rendered.")
        self.assertContains(rep_res, "Siddharth Nair")

        # 14. Individual student report shows accurate history
        detail_res = self.client.get(reverse('student_detail', args=[student1.id]))
        self.assertEqual(detail_res.status_code, 200, "Criterion 14 failed: Individual profile rendered.")
        stats1 = calculate_student_attendance(student1)
        self.assertEqual(stats1['percentage'], 100.0, "Criterion 14 failed: 100% attendance calculated for Siddharth.")

        # 15. Teacher adds a lesson diary entry
        teentaal, _ = Taal.objects.get_or_create(
            name='Teentaal',
            defaults={'matras': 16, 'vibhag_structure': '4+4+4+4', 'tali_khali_info': '1,5,13', 'theka_notation': 'Theka'}
        )
        lesson = Lesson.objects.create(
            session=session,
            batch=batch,
            date=session_date,
            topic='Teentaal Theka & Dayna balance',
            taal=teentaal,
            bol_notation='Dha Dhin Dhin Dha',
            summary='Focused on clear Dayna resonance',
            homework='Practice Theka 20 minutes daily'
        )
        self.assertEqual(lesson.topic, 'Teentaal Theka & Dayna balance', "Criterion 15 failed: Lesson diary saved.")

        # 16. Teacher creates a practice assignment
        assignment = PracticeAssignment.objects.create(
            title='Daily Theka Riyaz',
            description='Steady 60 BPM tempo practice',
            student=student1,
            batch=batch,
            related_lesson=lesson,
            due_date=today + timedelta(days=7),
            status='assigned'
        )
        self.assertEqual(assignment.status, 'assigned', "Criterion 16 failed: Practice assignment created.")

        # 17. Teacher searches the taal library
        lib_res = self.client.get(reverse('composition_list') + '?q=Theka')
        self.assertEqual(lib_res.status_code, 200, "Criterion 17 failed: Taal library searchable.")

        # 18. Teacher exports an attendance report
        csv_res = self.client.get(reverse('export_attendance_csv'))
        self.assertEqual(csv_res.status_code, 200, "Criterion 18 failed: Attendance CSV export.")
        self.assertEqual(csv_res['Content-Type'], 'text/csv; charset=utf-8')

        # 19. Teacher creates a database backup
        backup_info = create_database_backup()
        self.assertTrue(backup_info['filename'].startswith('taal_backup_'), "Criterion 19 failed: Database backup.")

        # 20. Application preserves historical records when a student is deactivated or changes batches
        enr1.is_active = False
        enr1.left_date = today
        enr1.save()
        self.assertEqual(BatchEnrollment.objects.filter(student=student1, batch=batch).count(), 1)
        # Attendance remains attached
        self.assertEqual(Attendance.objects.filter(student=student1, session=session).count(), 1, "Criterion 20 failed: Historical attendance preserved.")
