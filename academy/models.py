import uuid
from decimal import Decimal
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.exceptions import ValidationError


class AcademySettings(models.Model):
    """Global configuration settings for the Academy."""
    academy_name = models.CharField(max_length=200, default="Radhhanand Sangeet Vidyalaya")
    tagline = models.CharField(max_length=255, default="Every Beat. Every Lesson. Every Milestone.")
    teacher_name = models.CharField(max_length=150, default="Guru Ji")
    phone = models.CharField(max_length=25, blank=True, default="+91 98765 43210", help_text="Official academy contact phone")
    email = models.EmailField(blank=True, default="contact@radhhanand.org", help_text="Official academy email")
    address = models.TextField(blank=True, default="Radhhanand Sangeet Vidyalaya, India", help_text="Academy premises address")
    whatsapp_number = models.CharField(max_length=25, blank=True, default="+91 98765 43210", help_text="Official academy WhatsApp number")
    attendance_threshold = models.FloatField(
        default=75.0,
        help_text="Attendance percentage threshold below which alerts are flagged (e.g. 75%)"
    )
    consecutive_absence_threshold = models.PositiveIntegerField(
        default=3,
        help_text="Number of consecutive conducted sessions missed before an alert triggers"
    )
    currency_symbol = models.CharField(max_length=10, default="₹")
    date_format = models.CharField(max_length=30, default="YYYY-MM-DD")
    enable_fees = models.BooleanField(default=True, help_text="Enable or disable fee management module")
    enable_late_status = models.BooleanField(default=False, help_text="Enable 'Late' as an attendance status")
    default_class_duration = models.PositiveIntegerField(default=60, help_text="Default duration in minutes")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Academy Settings"
        verbose_name_plural = "Academy Settings"

    def __str__(self):
        return self.academy_name

    @classmethod
    def get_settings(cls):
        settings_obj = cls.objects.first()
        if not settings_obj:
            settings_obj = cls.objects.create(academy_name="Radhhanand Sangeet Vidyalaya")
        elif settings_obj.academy_name != "Radhhanand Sangeet Vidyalaya":
            settings_obj.academy_name = "Radhhanand Sangeet Vidyalaya"
            settings_obj.save(update_fields=['academy_name'])
        return settings_obj



class Student(models.Model):
    """Student profile and record."""
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('paused', 'Temporarily Paused'),
        ('discontinued', 'Discontinued'),
    ]

    LEVEL_CHOICES = [
        ('beginner', 'Beginner (Prarambhik / Praveshika)'),
        ('intermediate', 'Intermediate (Madhyama Purna)'),
        ('advanced', 'Advanced (Visharad)'),
        ('mastery', 'Mastery (Alankar / Kovid)'),
    ]

    student_id = models.CharField(max_length=40, unique=True, db_index=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=25, blank=True)
    email = models.EmailField(blank=True)
    guardian_name = models.CharField(max_length=150, blank=True)
    guardian_phone = models.CharField(max_length=25, blank=True)
    guardian_whatsapp = models.CharField(max_length=25, blank=True, help_text="WhatsApp contact for class reminders & receipts")
    address = models.TextField(blank=True, help_text="Residential or correspondence address")
    monthly_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text="Monthly tuition fee (₹)")
    date_of_birth = models.DateField(null=True, blank=True)
    enrollment_date = models.DateField(default=timezone.now)
    level = models.CharField(max_length=30, choices=LEVEL_CHOICES, default='beginner')
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='active')
    is_archived = models.BooleanField(default=False, help_text="Archived student status")
    whatsapp_opt_out = models.BooleanField(default=False, help_text="Parent opted out of WhatsApp reminders & receipts")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['student_id']

    def __str__(self):
        return f"{self.student_id} - {self.full_name}"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @classmethod
    def generate_student_id(cls):
        year = timezone.now().year
        prefix = f"TAL-{year}-"
        last_student = cls.objects.filter(student_id__startswith=prefix).order_by('-student_id').first()
        if last_student:
            try:
                num = int(last_student.student_id.split('-')[-1]) + 1
            except ValueError:
                num = cls.objects.count() + 1
        else:
            num = 1
        return f"{prefix}{num:03d}"

    def save(self, *args, **kwargs):
        if not self.student_id:
            self.student_id = self.generate_student_id()
        if not self.guardian_whatsapp and self.guardian_phone:
            self.guardian_whatsapp = self.guardian_phone
        super().save(*args, **kwargs)


class Batch(models.Model):
    """Batch/Group for scheduled group lessons or individual instruction."""
    DAY_CHOICES = [
        ('Monday', 'Monday'),
        ('Tuesday', 'Tuesday'),
        ('Wednesday', 'Wednesday'),
        ('Thursday', 'Thursday'),
        ('Friday', 'Friday'),
        ('Saturday', 'Saturday'),
        ('Sunday', 'Sunday'),
    ]

    LEVEL_CHOICES = Student.LEVEL_CHOICES

    batch_id = models.CharField(max_length=40, unique=True, db_index=True)
    name = models.CharField(max_length=150)
    course = models.CharField(max_length=100, default='Tabla', help_text="Course or Instrument name")
    description = models.TextField(blank=True)
    level = models.CharField(max_length=30, choices=LEVEL_CHOICES, default='beginner')
    teacher_name = models.CharField(max_length=150, blank=True)
    regular_day = models.CharField(max_length=20, choices=DAY_CHOICES, default='Saturday')
    start_time = models.TimeField()
    end_time = models.TimeField()
    capacity = models.PositiveIntegerField(default=15, help_text="Maximum batch capacity")
    monthly_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text="Monthly tuition fee for this batch (₹)")
    start_date = models.DateField(default=timezone.now)
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_archived = models.BooleanField(default=False, help_text="Archived batch status")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Batches"
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.regular_day} {self.start_time.strftime('%H:%M')})"

    @property
    def active_students_count(self):
        return self.enrollments.filter(is_active=True, student__status='active').count()

    @property
    def is_full(self):
        return self.active_students_count >= self.capacity

    @classmethod
    def generate_batch_id(cls, level='BEG'):
        count = cls.objects.count() + 1
        return f"BAT-{level.upper()[:3]}-{count:02d}"



class BatchEnrollment(models.Model):
    """Tracks a student's enrollment in a batch across time to maintain historical accuracy."""
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='enrollments')
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name='enrollments')
    enrolled_date = models.DateField(default=timezone.now)
    left_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-enrolled_date']
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'batch', 'enrolled_date'],
                name='unique_student_batch_enrollment_date'
            )
        ]

    def __str__(self):
        return f"{self.student.full_name} -> {self.batch.name} ({'Active' if self.is_active else 'Past'})"


class BatchRecurringSchedule(models.Model):
    """Weekly recurring timetable schedule rule for a batch (e.g. Tuesday 17:00-18:00)."""
    DAY_CHOICES = [
        (0, 'Monday'),
        (1, 'Tuesday'),
        (2, 'Wednesday'),
        (3, 'Thursday'),
        (4, 'Friday'),
        (5, 'Saturday'),
        (6, 'Sunday'),
    ]
    DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name='recurring_schedules')
    day_of_week = models.IntegerField(choices=DAY_CHOICES, default=1)
    start_time = models.TimeField()
    end_time = models.TimeField()
    duration_minutes = models.PositiveIntegerField(default=60, help_text="Duration in minutes")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['day_of_week', 'start_time']
        constraints = [
            models.UniqueConstraint(
                fields=['batch', 'day_of_week', 'start_time'],
                name='unique_batch_recurring_slot'
            )
        ]

    def __str__(self):
        day_str = self.DAY_NAMES[self.day_of_week] if 0 <= self.day_of_week <= 6 else str(self.day_of_week)
        return f"{self.batch.name} - {day_str} ({self.start_time.strftime('%H:%M')} - {self.end_time.strftime('%H:%M')})"

    @property
    def day_name(self):
        return self.DAY_NAMES[self.day_of_week] if 0 <= self.day_of_week <= 6 else ''


class ClassSession(models.Model):
    """Individual class session scheduled for a batch."""
    STATUS_CHOICES = [
        ('scheduled', 'Scheduled'),
        ('conducted', 'Conducted'),
        ('cancelled', 'Cancelled'),
    ]

    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name='sessions')
    schedule_rule = models.ForeignKey(
        BatchRecurringSchedule,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='sessions',
        help_text="Recurring rule that generated this session"
    )
    date = models.DateField(default=timezone.now)
    start_time = models.TimeField()
    end_time = models.TimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='scheduled')
    cancellation_reason = models.TextField(blank=True)
    is_rescheduled = models.BooleanField(default=False)
    original_date = models.DateField(null=True, blank=True)
    original_start_time = models.TimeField(null=True, blank=True)
    reschedule_reason = models.TextField(blank=True)
    lesson_topic = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', '-start_time']
        constraints = [
            models.UniqueConstraint(
                fields=['batch', 'date', 'start_time'],
                name='unique_batch_session_time'
            )
        ]

    def __str__(self):
        return f"{self.batch.name} - {self.date} ({self.get_status_display()})"

    @property
    def attendance_count(self):
        return self.attendances.count()

    @property
    def is_attendance_saved(self):
        return self.attendances.exists()



class Attendance(models.Model):
    """Daily attendance record for a student in a session."""
    STATUS_CHOICES = [
        ('present', 'Present'),
        ('absent', 'Absent'),
        ('leave', 'Leave'),
        ('late', 'Late'),
    ]

    session = models.ForeignKey(ClassSession, on_delete=models.CASCADE, related_name='attendances')
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='attendances')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='present')
    remarks = models.CharField(max_length=255, blank=True)
    marked_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['student__first_name', 'student__last_name']
        constraints = [
            models.UniqueConstraint(
                fields=['session', 'student'],
                name='unique_session_student_attendance'
            )
        ]

    def __str__(self):
        return f"{self.student.full_name} - {self.session.date} ({self.get_status_display()})"


class AttendanceAuditLog(models.Model):
    """Audit log capturing every modification to saved attendance records."""
    session = models.ForeignKey(ClassSession, on_delete=models.CASCADE, related_name='audit_logs')
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='attendance_audits')
    old_status = models.CharField(max_length=20)
    new_status = models.CharField(max_length=20)
    changed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    changed_at = models.DateTimeField(auto_now_add=True)
    reason = models.TextField(blank=True)

    class Meta:
        ordering = ['-changed_at']

    def __str__(self):
        return f"Audit: {self.student.full_name} ({self.old_status} -> {self.new_status}) on {self.changed_at.strftime('%Y-%m-%d %H:%M')}"


class Taal(models.Model):
    """Core Indian Classical rhythmic cycle (Taal)."""
    LEVEL_CHOICES = Student.LEVEL_CHOICES

    name = models.CharField(max_length=100, unique=True)
    matras = models.PositiveIntegerField(help_text="Total number of beats (matras)")
    vibhag_structure = models.CharField(
        max_length=100,
        help_text="Division of vibhags, e.g., '4 + 4 + 4 + 4' or '2 + 3 + 2 + 3'"
    )
    tali_khali_info = models.CharField(
        max_length=255,
        help_text="Tali and Khali positions, e.g., 'Tali on 1, 5, 13; Khali on 9'"
    )
    theka_notation = models.TextField(help_text="Basic theka bols with vibhag divisions")
    level = models.CharField(max_length=30, choices=LEVEL_CHOICES, default='beginner')
    notes = models.TextField(blank=True)
    reference_url = models.URLField(blank=True, help_text="Reference link or video/audio demonstration")

    class Meta:
        ordering = ['matras', 'name']

    def __str__(self):
        return f"{self.name} ({self.matras} Matras)"


class Composition(models.Model):
    """Tabla repertoire: Peshkar, Kayda, Rela, Tukda, Tihai, Chakradar, etc."""
    CATEGORY_CHOICES = [
        ('basic_bols', 'Basic Bols / Nikas'),
        ('theka', 'Theka & Prakar'),
        ('peshkar', 'Peshkar'),
        ('kayda', 'Kayda & Palte'),
        ('rela', 'Rela'),
        ('tukda', 'Tukda'),
        ('tihai', 'Tihai (Damdar / Bedam)'),
        ('chakradar', 'Chakradar'),
        ('paran', 'Paran'),
        ('layakari', 'Layakari Exercise'),
        ('other', 'Other Repertoire'),
    ]

    title = models.CharField(max_length=200)
    taal = models.ForeignKey(Taal, on_delete=models.CASCADE, related_name='compositions')
    category = models.CharField(max_length=40, choices=CATEGORY_CHOICES, default='kayda')
    difficulty = models.CharField(max_length=30, choices=Student.LEVEL_CHOICES, default='beginner')
    bol_notation = models.TextField(help_text="Musical bols / notation layout")
    recommended_tempo = models.CharField(max_length=100, blank=True, help_text="e.g. Madhya Laya (100-140 BPM)")
    practice_instructions = models.TextField(blank=True)
    reference_link = models.URLField(blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['taal', 'category', 'title']

    def __str__(self):
        return f"{self.title} ({self.get_category_display()} - {self.taal.name})"


class Lesson(models.Model):
    """Lesson diary entry for a conducted class or batch session."""
    session = models.ForeignKey(ClassSession, null=True, blank=True, on_delete=models.SET_NULL, related_name='lessons')
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name='lessons')
    date = models.DateField(default=timezone.now)
    topic = models.CharField(max_length=255)
    taal = models.ForeignKey(Taal, null=True, blank=True, on_delete=models.SET_NULL, related_name='lessons')
    composition_type = models.CharField(max_length=100, blank=True)
    bol_notation = models.TextField(blank=True, help_text="Bols taught in this session")
    tempo_bpm = models.CharField(max_length=60, blank=True, help_text="Target or taught tempo/laya")
    summary = models.TextField(blank=True, help_text="Lesson summary and theoretical points")
    homework = models.TextField(blank=True, help_text="Homework assigned")
    next_lesson_goal = models.TextField(blank=True, help_text="Plan for next class")
    teacher_feedback = models.TextField(blank=True, help_text="Observations on batch performance")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"{self.batch.name} - {self.topic} ({self.date})"


class PracticeAssignment(models.Model):
    """Homework and riyaz (practice) assignments."""
    STATUS_CHOICES = [
        ('assigned', 'Assigned'),
        ('reviewed', 'Reviewed'),
        ('completed', 'Completed'),
        ('needs_practice', 'Needs More Practice'),
    ]

    title = models.CharField(max_length=255)
    description = models.TextField()
    batch = models.ForeignKey(Batch, null=True, blank=True, on_delete=models.SET_NULL, related_name='assignments')
    student = models.ForeignKey(Student, null=True, blank=True, on_delete=models.SET_NULL, related_name='assignments')
    related_lesson = models.ForeignKey(Lesson, null=True, blank=True, on_delete=models.SET_NULL, related_name='assignments')
    taal = models.ForeignKey(Taal, null=True, blank=True, on_delete=models.SET_NULL, related_name='assignments')
    composition_type = models.CharField(max_length=100, blank=True)
    target_tempo = models.CharField(max_length=100, blank=True, help_text="Target BPM or laya")
    recommended_practice_duration = models.CharField(max_length=100, blank=True, help_text="e.g. 30 mins / day")
    assigned_date = models.DateField(default=timezone.now)
    due_date = models.DateField()
    teacher_instructions = models.TextField(blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='assigned')
    feedback = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['due_date', '-created_at']

    def __str__(self):
        target = self.student.full_name if self.student else (self.batch.name if self.batch else "General")
        return f"{self.title} -> {target} (Due: {self.due_date})"

    @property
    def is_overdue(self):
        return self.status in ['assigned', 'needs_practice'] and self.due_date < timezone.now().date()


class StudentProgress(models.Model):
    """Tracks musical milestones, compositions mastered, and revision needs."""
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='progress_records')
    date = models.DateField(default=timezone.now)
    current_level = models.CharField(max_length=50, choices=Student.LEVEL_CHOICES, default='beginner')
    taals_studied = models.TextField(blank=True, help_text="Taals currently practiced or studied")
    compositions_studied = models.TextField(blank=True, help_text="Compositions memorized and performed")
    topics_completed = models.TextField(blank=True, help_text="Techniques/topics successfully mastered")
    topics_needing_revision = models.TextField(blank=True, help_text="Nikas, bols, or speeds needing attention")
    tempo_targets = models.CharField(max_length=150, blank=True, help_text="Tempo goals achieved or targeted")
    feedback = models.TextField(blank=True)
    next_goal = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"{self.student.full_name} Progress ({self.date})"


class PerformanceRecord(models.Model):
    """Stage performances, recitals, and public presentations."""
    student = models.ForeignKey(Student, null=True, blank=True, on_delete=models.CASCADE, related_name='performances')
    batch = models.ForeignKey(Batch, null=True, blank=True, on_delete=models.SET_NULL, related_name='performances')
    event_name = models.CharField(max_length=255)
    event_date = models.DateField()
    venue = models.CharField(max_length=255, blank=True)
    composition_performed = models.TextField(blank=True)
    taal = models.CharField(max_length=100, blank=True)
    teacher_feedback = models.TextField(blank=True)
    recording_url = models.URLField(blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-event_date']

    def __str__(self):
        return f"{self.event_name} ({self.event_date})"


class ExaminationRecord(models.Model):
    """Formal musical examinations (e.g. Gandharva Mahavidyalaya or Academy Exams)."""
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='examinations')
    exam_name = models.CharField(max_length=255)
    exam_board = models.CharField(max_length=255, blank=True)
    exam_date = models.DateField()
    theory_progress = models.CharField(max_length=255, blank=True)
    practical_progress = models.CharField(max_length=255, blank=True)
    mock_result = models.CharField(max_length=100, blank=True)
    teacher_remarks = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-exam_date']

    def __str__(self):
        return f"{self.student.full_name} - {self.exam_name} ({self.exam_date})"


class FeePlan(models.Model):
    """Fee structures for student billing."""
    FREQUENCY_CHOICES = [
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('per_class', 'Per Class'),
        ('yearly', 'Yearly'),
    ]

    name = models.CharField(max_length=150)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    billing_frequency = models.CharField(max_length=30, choices=FREQUENCY_CHOICES, default='monthly')
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.amount})"


class PaymentRecord(models.Model):
    """Manual and automated payment record keeping for student fees."""
    METHOD_CHOICES = [
        ('cash', 'Cash'),
        ('upi', 'UPI / Online Transfer'),
        ('bank_transfer', 'Bank Transfer / NEFT'),
        ('cheque', 'Cheque'),
        ('other', 'Other'),
    ]

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='payments')
    fee_plan = models.ForeignKey(FeePlan, null=True, blank=True, on_delete=models.SET_NULL, related_name='payments')
    amount_due = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text="Total fee payable for this period (₹)")
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text="Amount received (₹)")
    fee_month = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Fee Month (1-12)")
    fee_year = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Fee Year (e.g. 2026)")
    billing_period = models.CharField(max_length=100, blank=True, help_text="e.g. October 2026")
    due_date = models.DateField(null=True, blank=True)
    payment_date = models.DateField(null=True, blank=True)
    payment_method = models.CharField(max_length=30, choices=METHOD_CHOICES, default='upi')
    receipt_number = models.CharField(max_length=100, blank=True, db_index=True)
    transaction_reference = models.CharField(max_length=150, blank=True, help_text="Transaction reference / UPI UTR / Cheque No.")
    idempotency_key = models.CharField(max_length=64, blank=True, db_index=True, help_text="Prevents duplicate submissions")
    is_reversed = models.BooleanField(default=False, help_text="Flagged if payment was corrected or refunded")
    reversal_reason = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-payment_date', '-created_at']

    def __str__(self):
        return f"{self.student.full_name} - {self.billing_period} (₹{self.amount_paid}/₹{self.amount_due})"

    @property
    def outstanding_balance(self):
        return max(Decimal('0.00'), self.amount_due - self.amount_paid)

    @property
    def remaining_balance(self):
        return self.outstanding_balance

    @property
    def is_fully_paid(self):
        return self.amount_paid >= self.amount_due and self.amount_due > 0

    @property
    def is_partial(self):
        return Decimal('0.00') < self.amount_paid < self.amount_due

    @property
    def is_pending(self):
        return self.amount_paid == Decimal('0.00') and self.amount_due > 0

    @classmethod
    def generate_receipt_number(cls):
        year = timezone.now().year
        prefix = f"RSV-REC-{year}-"
        last = cls.objects.filter(receipt_number__startswith=prefix).order_by('-id').first()
        if last and last.receipt_number:
            try:
                num = int(last.receipt_number.split('-')[-1]) + 1
            except (ValueError, IndexError):
                num = cls.objects.count() + 1
        else:
            num = cls.objects.count() + 1
        return f"{prefix}{num:04d}"

    def save(self, *args, **kwargs):
        if not self.receipt_number:
            self.receipt_number = self.generate_receipt_number()
        if not self.payment_date:
            self.payment_date = timezone.now().date()
        if not self.fee_year and self.payment_date:
            self.fee_year = self.payment_date.year
        if not self.fee_month and self.payment_date:
            self.fee_month = self.payment_date.month
        if not self.billing_period and self.payment_date:
            self.billing_period = self.payment_date.strftime('%B %Y')
        super().save(*args, **kwargs)


class AcademyAlert(models.Model):
    """Internal notifications and alerts for the teacher."""
    ALERT_TYPE_CHOICES = [
        ('attendance_low', 'Low Attendance Warning'),
        ('consecutive_absence', 'Consecutive Absence Alert'),
        ('unrecorded_session', 'Attendance Not Recorded'),
        ('upcoming_session', 'Upcoming Session'),
        ('overdue_assignment', 'Overdue Assignment'),
        ('fee_due', 'Fee Due Reminder'),
        ('general', 'General Notification'),
    ]

    SEVERITY_CHOICES = [
        ('info', 'Information'),
        ('warning', 'Warning'),
        ('danger', 'Critical Alert'),
    ]

    alert_type = models.CharField(max_length=40, choices=ALERT_TYPE_CHOICES)
    title = models.CharField(max_length=255)
    message = models.TextField()
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='info')
    link = models.CharField(max_length=255, blank=True)
    is_dismissed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.severity.upper()}] {self.title}"


class WhatsAppMessageLog(models.Model):
    """Audit log for automated and manual WhatsApp messages (reminders, receipts, chatbot responses)."""
    MESSAGE_TYPES = [
        ('class_reminder', 'Class Reminder'),
        ('fee_receipt', 'Payment Receipt'),
        ('chatbot_reply', 'Chatbot Response'),
        ('manual_alert', 'Manual Notification'),
    ]
    STATUS_CHOICES = [
        ('simulated', 'Simulated (Test Mode)'),
        ('sent', 'Sent via API'),
        ('delivered', 'Delivered'),
        ('failed', 'Failed'),
    ]

    student = models.ForeignKey(Student, null=True, blank=True, on_delete=models.SET_NULL, related_name='whatsapp_logs')
    session = models.ForeignKey(ClassSession, null=True, blank=True, on_delete=models.SET_NULL, related_name='whatsapp_logs')
    payment = models.ForeignKey(PaymentRecord, null=True, blank=True, on_delete=models.SET_NULL, related_name='whatsapp_logs')
    recipient_phone = models.CharField(max_length=25)
    recipient_name = models.CharField(max_length=150, blank=True)
    message_type = models.CharField(max_length=30, choices=MESSAGE_TYPES)
    message_text = models.TextField()
    provider_message_id = models.CharField(max_length=150, blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='simulated')
    error_details = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.get_message_type_display()}] {self.recipient_phone} ({self.status}) on {self.created_at.strftime('%Y-%m-%d %H:%M')}"


class ChatbotVerificationCode(models.Model):
    """Secure one-time verification codes for WhatsApp chatbot parent identification."""
    phone_number = models.CharField(max_length=25, db_index=True)
    code = models.CharField(max_length=10)
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-created_at']

    def is_valid(self):
        return not self.is_verified and timezone.now() <= self.expires_at and self.attempts < 5

