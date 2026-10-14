from django import forms
from .models import (
    AcademySettings, Student, Batch, BatchEnrollment, BatchRecurringSchedule,
    ClassSession, Attendance, Lesson, PracticeAssignment,
    Taal, Composition, StudentProgress, PerformanceRecord,
    ExaminationRecord, FeePlan, PaymentRecord
)



class BaseStyledModelForm(forms.ModelForm):
    """Base form that adds clean styling classes to all form widgets."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.update({'class': 'form-check-input'})
            elif isinstance(widget, forms.Select):
                widget.attrs.update({'class': 'form-select'})
            elif isinstance(widget, forms.Textarea):
                widget.attrs.update({'class': 'form-control', 'rows': 3})
            else:
                widget.attrs.update({'class': 'form-control'})


class StudentForm(BaseStyledModelForm):
    initial_batch = forms.ModelChoiceField(
        queryset=Batch.objects.filter(is_active=True),
        required=False,
        empty_label="-- Select Batch (Optional) --",
        help_text="Optionally assign to an active batch immediately"
    )

    class Meta:
        model = Student
        fields = [
            'first_name', 'last_name', 'phone', 'email',
            'guardian_name', 'guardian_phone', 'guardian_whatsapp',
            'whatsapp_opt_out', 'address', 'monthly_fee', 'date_of_birth',
            'enrollment_date', 'level', 'status', 'notes'
        ]
        widgets = {
            'date_of_birth': forms.DateInput(attrs={'type': 'date'}),
            'enrollment_date': forms.DateInput(attrs={'type': 'date'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def clean_phone(self):
        phone = self.cleaned_data.get('phone', '').strip()
        return phone


class BatchForm(BaseStyledModelForm):
    class Meta:
        model = Batch
        fields = [
            'name', 'course', 'description', 'level', 'teacher_name',
            'regular_day', 'start_time', 'end_time', 'capacity', 'monthly_fee',
            'start_date', 'end_date', 'is_active', 'notes'
        ]
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
            'start_time': forms.TimeInput(attrs={'type': 'time'}),
            'end_time': forms.TimeInput(attrs={'type': 'time'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get('start_time')
        end = cleaned_data.get('end_time')
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        regular_day = cleaned_data.get('regular_day')
        teacher = (cleaned_data.get('teacher_name') or '').strip().lower()

        if start and end and start >= end:
            raise forms.ValidationError("End time must be later than start time.")

        if start_date and end_date and end_date < start_date:
            raise forms.ValidationError("End date cannot be earlier than start date.")

        if regular_day and start and end:
            overlapping = Batch.objects.filter(
                regular_day=regular_day,
                is_active=True,
                is_archived=False
            )
            if self.instance.pk:
                overlapping = overlapping.exclude(pk=self.instance.pk)

            for other in overlapping:
                # Time overlap condition: start < other.end_time and end > other.start_time
                if start < other.end_time and end > other.start_time:
                    other_teacher = (other.teacher_name or '').strip().lower()
                    if teacher and other_teacher and teacher == other_teacher:
                        raise forms.ValidationError(
                            f"Instructor time conflict: Guru '{other.teacher_name}' is already assigned to "
                            f"{other.name} on {regular_day} ({other.start_time.strftime('%I:%M %p')} - {other.end_time.strftime('%I:%M %p')})."
                        )

        return cleaned_data


class BatchRecurringScheduleForm(BaseStyledModelForm):
    class Meta:
        model = BatchRecurringSchedule
        fields = ['batch', 'day_of_week', 'start_time', 'end_time', 'duration_minutes', 'is_active']
        widgets = {
            'start_time': forms.TimeInput(attrs={'type': 'time'}),
            'end_time': forms.TimeInput(attrs={'type': 'time'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get('start_time')
        end = cleaned_data.get('end_time')
        batch = cleaned_data.get('batch')
        day_of_week = cleaned_data.get('day_of_week')

        if start and end and start >= end:
            raise forms.ValidationError("End time must be later than start time.")

        if batch and day_of_week is not None and start:
            existing = BatchRecurringSchedule.objects.filter(
                batch=batch,
                day_of_week=day_of_week,
                start_time=start
            )
            if self.instance.pk:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                raise forms.ValidationError(f"This batch already has a recurring slot on this day at {start.strftime('%H:%M')}.")
        return cleaned_data


class BatchEnrollmentForm(BaseStyledModelForm):
    class Meta:
        model = BatchEnrollment
        fields = ['student', 'batch', 'enrolled_date', 'left_date', 'is_active']
        widgets = {
            'enrolled_date': forms.DateInput(attrs={'type': 'date'}),
            'left_date': forms.DateInput(attrs={'type': 'date'}),
        }


class ClassSessionForm(BaseStyledModelForm):
    class Meta:
        model = ClassSession
        fields = ['batch', 'date', 'start_time', 'end_time', 'status', 'cancellation_reason', 'lesson_topic', 'notes']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'start_time': forms.TimeInput(attrs={'type': 'time'}),
            'end_time': forms.TimeInput(attrs={'type': 'time'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        batch = cleaned_data.get('batch')
        session_date = cleaned_data.get('date')
        start_time = cleaned_data.get('start_time')
        end_time = cleaned_data.get('end_time')
        status = cleaned_data.get('status')
        cancellation_reason = cleaned_data.get('cancellation_reason')

        if start_time and end_time and start_time >= end_time:
            raise forms.ValidationError("End time must be later than start time.")

        if status == 'cancelled' and not cancellation_reason:
            self.add_error('cancellation_reason', 'Please provide a reason when cancelling a session.')

        if batch and session_date and start_time:
            # Check duplicate session on same day/time
            existing = ClassSession.objects.filter(
                batch=batch,
                date=session_date,
                start_time=start_time
            )
            if self.instance.pk:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                raise forms.ValidationError(f"A session for {batch.name} on {session_date} at {start_time} already exists.")

        return cleaned_data


class ClassSessionRescheduleForm(BaseStyledModelForm):
    class Meta:
        model = ClassSession
        fields = ['date', 'start_time', 'end_time', 'reschedule_reason']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'start_time': forms.TimeInput(attrs={'type': 'time'}),
            'end_time': forms.TimeInput(attrs={'type': 'time'}),
            'reschedule_reason': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Reason for rescheduling this session...'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get('start_time')
        end = cleaned_data.get('end_time')
        reason = cleaned_data.get('reschedule_reason')
        if start and end and start >= end:
            raise forms.ValidationError("End time must be later than start time.")
        if not reason:
            self.add_error('reschedule_reason', 'Please specify a reason for rescheduling.')
        return cleaned_data


class ClassSessionCancelForm(BaseStyledModelForm):
    class Meta:
        model = ClassSession
        fields = ['cancellation_reason']
        widgets = {
            'cancellation_reason': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Reason for cancellation (e.g. Guru Ji concert, holiday, emergency)...', 'required': 'required'}),
        }

    def clean_cancellation_reason(self):
        reason = self.cleaned_data.get('cancellation_reason', '').strip()
        if not reason:
            raise forms.ValidationError("A cancellation reason is required.")
        return reason


class LessonForm(BaseStyledModelForm):
    class Meta:
        model = Lesson
        fields = [
            'batch', 'session', 'date', 'topic', 'taal', 'composition_type',
            'bol_notation', 'tempo_bpm', 'summary', 'homework',
            'next_lesson_goal', 'teacher_feedback', 'notes'
        ]
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'bol_notation': forms.Textarea(attrs={'class': 'form-control font-monospace', 'rows': 4, 'placeholder': 'Dha Dhin Dhin Dha...'}),
        }


class PracticeAssignmentForm(BaseStyledModelForm):
    class Meta:
        model = PracticeAssignment
        fields = [
            'title', 'description', 'batch', 'student', 'related_lesson',
            'taal', 'composition_type', 'target_tempo',
            'recommended_practice_duration', 'assigned_date', 'due_date',
            'teacher_instructions', 'status', 'feedback'
        ]
        widgets = {
            'assigned_date': forms.DateInput(attrs={'type': 'date'}),
            'due_date': forms.DateInput(attrs={'type': 'date'}),
        }


class TaalForm(BaseStyledModelForm):
    class Meta:
        model = Taal
        fields = ['name', 'matras', 'vibhag_structure', 'tali_khali_info', 'theka_notation', 'level', 'notes', 'reference_url']
        widgets = {
            'theka_notation': forms.Textarea(attrs={'class': 'form-control font-monospace', 'rows': 3}),
        }


class CompositionForm(BaseStyledModelForm):
    class Meta:
        model = Composition
        fields = [
            'title', 'taal', 'category', 'difficulty', 'bol_notation',
            'recommended_tempo', 'practice_instructions', 'reference_link', 'notes'
        ]
        widgets = {
            'bol_notation': forms.Textarea(attrs={'class': 'form-control font-monospace', 'rows': 5}),
        }


class StudentProgressForm(BaseStyledModelForm):
    class Meta:
        model = StudentProgress
        fields = [
            'student', 'date', 'current_level', 'taals_studied',
            'compositions_studied', 'topics_completed', 'topics_needing_revision',
            'tempo_targets', 'feedback', 'next_goal'
        ]
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }


class PerformanceRecordForm(BaseStyledModelForm):
    class Meta:
        model = PerformanceRecord
        fields = [
            'student', 'batch', 'event_name', 'event_date', 'venue',
            'composition_performed', 'taal', 'teacher_feedback', 'recording_url', 'notes'
        ]
        widgets = {
            'event_date': forms.DateInput(attrs={'type': 'date'}),
        }


class ExaminationRecordForm(BaseStyledModelForm):
    class Meta:
        model = ExaminationRecord
        fields = [
            'student', 'exam_name', 'exam_board', 'exam_date',
            'theory_progress', 'practical_progress', 'mock_result', 'teacher_remarks'
        ]
        widgets = {
            'exam_date': forms.DateInput(attrs={'type': 'date'}),
        }


class FeePlanForm(BaseStyledModelForm):
    class Meta:
        model = FeePlan
        fields = ['name', 'amount', 'billing_frequency', 'description', 'is_active']


MONTH_CHOICES = [
    (1, 'January'), (2, 'February'), (3, 'March'), (4, 'April'),
    (5, 'May'), (6, 'June'), (7, 'July'), (8, 'August'),
    (9, 'September'), (10, 'October'), (11, 'November'), (12, 'December'),
]


class PaymentRecordForm(BaseStyledModelForm):
    MONTH_CHOICES = MONTH_CHOICES
    fee_month = forms.ChoiceField(choices=MONTH_CHOICES, required=False)

    class Meta:
        model = PaymentRecord
        fields = [
            'student', 'fee_plan', 'fee_month', 'fee_year',
            'amount_due', 'amount_paid', 'billing_period',
            'payment_date', 'due_date', 'payment_method',
            'transaction_reference', 'idempotency_key', 'notes'
        ]
        widgets = {
            'payment_date': forms.DateInput(attrs={'type': 'date'}),
            'due_date': forms.DateInput(attrs={'type': 'date'}),
            'idempotency_key': forms.HiddenInput(),
        }

    def clean_amount_paid(self):
        amount = self.cleaned_data.get('amount_paid')
        if amount is not None and amount <= 0:
            raise forms.ValidationError("Payment amount received must be greater than zero.")
        return amount

    def clean_amount_due(self):
        amount = self.cleaned_data.get('amount_due')
        if amount is not None and amount < 0:
            raise forms.ValidationError("Amount due cannot be negative.")
        return amount

    def clean(self):
        cleaned_data = super().clean()
        student = cleaned_data.get('student')
        amount_paid = cleaned_data.get('amount_paid')
        amount_due = cleaned_data.get('amount_due')
        month = cleaned_data.get('fee_month')
        year = cleaned_data.get('fee_year')

        # Auto-fill amount_due from student's monthly_fee if zero
        if student and (not amount_due or amount_due == 0):
            if student.monthly_fee and student.monthly_fee > 0:
                cleaned_data['amount_due'] = student.monthly_fee
            elif amount_paid:
                cleaned_data['amount_due'] = amount_paid

        # If billing_period is empty, auto generate from month/year
        if month and year and not cleaned_data.get('billing_period'):
            import calendar
            month_name = calendar.month_name[int(month)]
            cleaned_data['billing_period'] = f"{month_name} {year}"

        return cleaned_data


class AcademySettingsForm(BaseStyledModelForm):
    class Meta:
        model = AcademySettings
        fields = [
            'academy_name', 'tagline', 'teacher_name',
            'phone', 'email', 'address', 'whatsapp_number',
            'attendance_threshold', 'consecutive_absence_threshold',
            'currency_symbol', 'date_format',
            'enable_fees', 'enable_late_status', 'default_class_duration'
        ]
        widgets = {
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

