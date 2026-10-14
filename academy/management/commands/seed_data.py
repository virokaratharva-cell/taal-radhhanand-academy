from datetime import date, time, timedelta
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from academy.models import (
    AcademySettings, Student, Batch, BatchEnrollment,
    ClassSession, Attendance, FeePlan, PaymentRecord
)
from academy.services import seed_foundational_taals_and_compositions, record_session_attendance


class Command(BaseCommand):
    help = 'Seeds foundational Indian classical Taals, compositions, default settings, and sample demo records.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--create-teacher',
            action='store_true',
            help='Creates a default teacher account (username: teacher, password: teacher123)',
        )
        parser.add_argument(
            '--with-samples',
            action='store_true',
            help='Populates sample batches, students, sessions, and attendance for immediate demonstration',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Initializing TAAL system data..."))

        # 1. Academy Settings
        settings_obj = AcademySettings.get_settings()
        self.stdout.write(self.style.SUCCESS(f"Academy Settings verified: '{settings_obj.academy_name}'"))

        # 2. Seed Taals & Compositions
        count = seed_foundational_taals_and_compositions()
        self.stdout.write(self.style.SUCCESS(f"Foundational Taals & Compositions verified ({count} taals)."))

        # 3. Optional Teacher User
        if options['create_teacher']:
            if not User.objects.filter(username='teacher').exists():
                User.objects.create_superuser('teacher', 'teacher@taalacademy.com', 'teacher123', first_name='Pt.', last_name='Suresh Sharma')
                self.stdout.write(self.style.SUCCESS("Created teacher superuser account: username='teacher', password='teacher123'"))
            else:
                self.stdout.write(self.style.WARNING("Teacher user 'teacher' already exists."))

        # 4. Optional Sample Data
        if options['with_samples']:
            today = timezone.now().date()

            # Batch 1: Beginner
            batch1, _ = Batch.objects.get_or_create(
                batch_id='BAT-BEG-01',
                defaults={
                    'name': 'Beginner Riyaz Batch (Delhi Gharana)',
                    'description': 'Foundational bols: Dha, Ge, Na, Ti, TeTe. Teentaal Kaydas.',
                    'level': 'beginner',
                    'teacher_name': settings_obj.teacher_name,
                    'regular_day': 'Saturday',
                    'start_time': time(9, 0),
                    'end_time': time(10, 0),
                    'start_date': today - timedelta(days=60),
                    'is_active': True
                }
            )

            # Batch 2: Intermediate
            batch2, _ = Batch.objects.get_or_create(
                batch_id='BAT-INT-01',
                defaults={
                    'name': 'Intermediate Jhaptaal & Ektaal Workshop',
                    'description': 'Khanda and Rupak layakari, Relas and Farrukhabad Tukdas.',
                    'level': 'intermediate',
                    'teacher_name': settings_obj.teacher_name,
                    'regular_day': 'Sunday',
                    'start_time': time(10, 30),
                    'end_time': time(11, 45),
                    'start_date': today - timedelta(days=45),
                    'is_active': True
                }
            )

            # Sample Students
            s1, _ = Student.objects.get_or_create(
                student_id='TAL-2026-001',
                defaults={
                    'first_name': 'Aarav',
                    'last_name': 'Kulkarni',
                    'phone': '9876543210',
                    'email': 'aarav.k@example.com',
                    'guardian_name': 'Ramesh Kulkarni',
                    'guardian_phone': '9876543211',
                    'enrollment_date': today - timedelta(days=60),
                    'level': 'beginner',
                    'status': 'active',
                    'notes': 'Attentive student. Good Daya clarity.'
                }
            )

            s2, _ = Student.objects.get_or_create(
                student_id='TAL-2026-002',
                defaults={
                    'first_name': 'Meera',
                    'last_name': 'Deshmukh',
                    'phone': '9822012345',
                    'email': 'meera.d@example.com',
                    'guardian_name': 'Anjali Deshmukh',
                    'guardian_phone': '9822012346',
                    'enrollment_date': today - timedelta(days=50),
                    'level': 'beginner',
                    'status': 'active',
                    'notes': 'Fast learning curve in basic TeTe bols.'
                }
            )

            s3, _ = Student.objects.get_or_create(
                student_id='TAL-2026-003',
                defaults={
                    'first_name': 'Rohan',
                    'last_name': 'Patel',
                    'phone': '9811098765',
                    'email': 'rohan.p@example.com',
                    'enrollment_date': today - timedelta(days=40),
                    'level': 'intermediate',
                    'status': 'active',
                    'notes': 'Preparing for Gandharva Praveshika examination.'
                }
            )

            # Enrollments
            BatchEnrollment.objects.get_or_create(student=s1, batch=batch1, defaults={'enrolled_date': s1.enrollment_date})
            BatchEnrollment.objects.get_or_create(student=s2, batch=batch1, defaults={'enrolled_date': s2.enrollment_date})
            BatchEnrollment.objects.get_or_create(student=s3, batch=batch2, defaults={'enrolled_date': s3.enrollment_date})

            # Fee plans
            plan_monthly, _ = FeePlan.objects.get_or_create(
                name='Monthly Regular (4 Sessions)',
                defaults={'amount': 2500.00, 'billing_frequency': 'monthly', 'description': 'Standard monthly tuition'}
            )

            PaymentRecord.objects.get_or_create(
                student=s1,
                billing_period=today.strftime('%B %Y'),
                defaults={
                    'fee_plan': plan_monthly,
                    'amount_due': 2500.00,
                    'amount_paid': 2500.00,
                    'due_date': today - timedelta(days=5),
                    'payment_date': today - timedelta(days=6),
                    'payment_method': 'upi',
                    'receipt_number': 'REC-2026-001'
                }
            )

            # Sample conducted sessions and attendance
            session1_date = today - timedelta(days=14)
            sess1, _ = ClassSession.objects.get_or_create(
                batch=batch1,
                date=session1_date,
                start_time=batch1.start_time,
                defaults={
                    'end_time': batch1.end_time,
                    'status': 'conducted',
                    'lesson_topic': 'Introduction to Delhi Kayda theme & first palta'
                }
            )
            record_session_attendance(sess1, {
                s1.id: {'status': 'present', 'remarks': 'Crisp Nikas'},
                s2.id: {'status': 'present', 'remarks': 'Good steady hand'}
            })

            session2_date = today - timedelta(days=7)
            sess2, _ = ClassSession.objects.get_or_create(
                batch=batch1,
                date=session2_date,
                start_time=batch1.start_time,
                defaults={
                    'end_time': batch1.end_time,
                    'status': 'conducted',
                    'lesson_topic': 'Kayda Palte 2 & 3 with Tihai calculations'
                }
            )
            record_session_attendance(sess2, {
                s1.id: {'status': 'present', 'remarks': 'On tempo'},
                s2.id: {'status': 'absent', 'remarks': 'Informed beforehand'}
            })

            # Today scheduled session
            ClassSession.objects.get_or_create(
                batch=batch1,
                date=today,
                start_time=batch1.start_time,
                defaults={
                    'end_time': batch1.end_time,
                    'status': 'scheduled',
                    'lesson_topic': 'Dhire Dhire Rela speed transition'
                }
            )

            self.stdout.write(self.style.SUCCESS("Sample batches, students, sessions, and attendance populated successfully!"))

        self.stdout.write(self.style.SUCCESS("TAAL initialization complete!"))
