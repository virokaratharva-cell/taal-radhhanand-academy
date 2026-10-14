from datetime import time, timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from academy.models import Batch, BatchRecurringSchedule, ClassSession, Attendance
from academy.services import generate_future_sessions


class Command(BaseCommand):
    help = "Configures the exact 9 default batch schedules for Radhhanand Sangeet Vidyalaya safely."

    def handle(self, *args, **options):
        self.stdout.write("Checking and configuring default academy timetable...")

        # Exact required schedules:
        # Tuesday: Batch 1 (17-18), Batch 2 (18-19), Batch 3 (19-20)
        # Thursday: Batch 1 (17-18), Batch 2 (18-19), Batch 3 (19-20)
        # Saturday: Batch 1 (17-18), Batch 2 (18-19), Batch 3 (19-20)
        # Sunday: Batch 1 (08-09), Batch 2 (09-11)
        
        day_map = {
            'Monday': 0, 'Tuesday': 1, 'Wednesday': 2, 'Thursday': 3,
            'Friday': 4, 'Saturday': 5, 'Sunday': 6
        }

        # 1. Tuesday Batches
        tue_schedules = [
            ("TUESDAY BATCH 1 (5 TO 6)", "Tuesday", time(17, 0), time(18, 0)),
            ("TUESDAY BATCH 2 (6 TO 7)", "Tuesday", time(18, 0), time(19, 0)),
            ("TUESDAY BATCH 3 (7 TO 8)", "Tuesday", time(19, 0), time(20, 0)),
        ]
        # 2. Thursday Batches
        thu_schedules = [
            ("THURSDAY BATCH 1 (5 TO 6)", "Thursday", time(17, 0), time(18, 0)),
            ("THURSDAY BATCH 2 (6 TO 7)", "Thursday", time(18, 0), time(19, 0)),
            ("THURSDAY BATCH 3 (7 TO 8)", "Thursday", time(19, 0), time(20, 0)),
        ]
        # 3. Saturday Batches
        sat_schedules = [
            ("SATURDAY BATCH 1 (5 TO 6)", "Saturday", time(17, 0), time(18, 0)),
            ("SATURDAY BATCH 2 (6 TO 7)", "Saturday", time(18, 0), time(19, 0)),
            ("SATURDAY BATCH 3 (7 TO 8)", "Saturday", time(19, 0), time(20, 0)),
        ]
        # 4. Sunday Batches
        sun_schedules = [
            ("SUNDAY BATCH 1 (8 TO 9)", "Sunday", time(8, 0), time(9, 0)),
            ("SUNDAY BATCH 2 (9 TO 11)", "Sunday", time(9, 0), time(11, 0)),
        ]

        all_target_schedules = tue_schedules + thu_schedules + sat_schedules + sun_schedules

        # Check existing Batch 1 conflict:
        b1 = Batch.objects.filter(id=1).first()
        if b1 and b1.regular_day == 'Saturday' and (b1.start_time != time(17, 0) or b1.end_time != time(18, 0)):
            self.stdout.write(self.style.WARNING(
                f"Conflict detected for Batch 1 '{b1.name}': configured at {b1.start_time}-{b1.end_time}. "
                f"Deliberately aligning schedule to Saturday 5:00 PM - 6:00 PM while preserving all historical attendance and student enrollments."
            ))
            b1.name = "SATURDAY BATCH 1 (5 TO 6)"
            b1.start_time = time(17, 0)
            b1.end_time = time(18, 0)
            b1.regular_day = "Saturday"
            b1.save()
            rule1 = BatchRecurringSchedule.objects.filter(batch=b1).first()
            if rule1:
                rule1.day_of_week = 5
                rule1.start_time = time(17, 0)
                rule1.end_time = time(18, 0)
                rule1.duration_minutes = 60
                rule1.is_active = True
                rule1.save()
            else:
                BatchRecurringSchedule.objects.create(
                    batch=b1, day_of_week=5, start_time=time(17, 0), end_time=time(18, 0), duration_minutes=60, is_active=True
                )

        # Check existing Batch 2 conflict:
        b2 = Batch.objects.filter(id=2).first()
        if b2 and b2.regular_day == 'Sunday' and (b2.start_time != time(9, 0) or b2.end_time != time(11, 0)):
            self.stdout.write(self.style.WARNING(
                f"Conflict detected for Batch 2 '{b2.name}': configured at {b2.start_time}-{b2.end_time}. "
                f"Deliberately aligning schedule to Sunday 9:00 AM - 11:00 AM while preserving all student records."
            ))
            b2.name = "SUNDAY BATCH 2 (9 TO 11)"
            b2.start_time = time(9, 0)
            b2.end_time = time(11, 0)
            b2.regular_day = "Sunday"
            b2.save()
            rule2 = BatchRecurringSchedule.objects.filter(batch=b2).first()
            if rule2:
                rule2.day_of_week = 6
                rule2.start_time = time(9, 0)
                rule2.end_time = time(11, 0)
                rule2.duration_minutes = 120
                rule2.is_active = True
                rule2.save()
            else:
                BatchRecurringSchedule.objects.create(
                    batch=b2, day_of_week=6, start_time=time(9, 0), end_time=time(11, 0), duration_minutes=120, is_active=True
                )

        # For all target schedules, ensure batch and recurring rule exist without duplicates:
        for name, day, start, end in all_target_schedules:
            day_num = day_map[day]
            dur = int((end.hour * 60 + end.minute) - (start.hour * 60 + start.minute))

            # Look for existing batch matching day and start_time
            batch = Batch.objects.filter(regular_day=day, start_time=start).first()
            if not batch:
                # Look by name (ignoring spaces/case)
                batch = Batch.objects.filter(name__iexact=name).first()

            if not batch:
                batch = Batch.objects.create(
                    batch_id=Batch.generate_batch_id('BEG'),
                    name=name,
                    course='Tabla',
                    regular_day=day,
                    start_time=start,
                    end_time=end,
                    level='beginner',
                    is_active=True,
                    is_archived=False
                )
                self.stdout.write(self.style.SUCCESS(f"Created missing default batch: {name}"))
            else:
                # Ensure active and not archived
                if batch.is_archived:
                    batch.is_archived = False
                batch.is_active = True
                batch.regular_day = day
                batch.start_time = start
                batch.end_time = end
                batch.save()
                self.stdout.write(f"Verified existing default batch: {batch.name}")

            # Ensure recurring rule
            rule = BatchRecurringSchedule.objects.filter(batch=batch, day_of_week=day_num, start_time=start).first()
            if not rule:
                rule = BatchRecurringSchedule.objects.create(
                    batch=batch,
                    day_of_week=day_num,
                    start_time=start,
                    end_time=end,
                    duration_minutes=dur,
                    is_active=True
                )
                self.stdout.write(self.style.SUCCESS(f"Created recurring schedule rule for {batch.name}: {rule}"))
            else:
                rule.end_time = end
                rule.duration_minutes = dur
                rule.is_active = True
                rule.save()

        # Idempotently generate upcoming sessions
        self.stdout.write("Generating upcoming sessions for default timetable...")
        res = generate_future_sessions(horizon_days=30)
        self.stdout.write(self.style.SUCCESS(
            f"Default timetable configured successfully! New sessions: {res['created_count']}, Skipped existing: {res['skipped_count']}."
        ))
