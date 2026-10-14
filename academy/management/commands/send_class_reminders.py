from django.core.management.base import BaseCommand
from django.utils import timezone
from academy.models import ClassSession
from academy.services import send_class_reminder_whatsapp


class Command(BaseCommand):
    help = "Sends automated WhatsApp reminders to parents for today's scheduled classes."

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Send reminders even if already recorded (not recommended).'
        )

    def handle(self, *args, **options):
        today = timezone.now().date()
        sessions = ClassSession.objects.filter(
            date=today,
            status='scheduled'
        ).select_related('batch')

        if not sessions.exists():
            self.stdout.write("No scheduled sessions found for today.")
            return

        self.stdout.write(f"Found {sessions.count()} scheduled session(s) today ({today}). Sending reminders...")

        total_sent = 0
        total_skipped = 0

        for session in sessions:
            results = send_class_reminder_whatsapp(session)
            for res in results:
                status = res.get('status')
                if status in ['sent', 'simulated']:
                    total_sent += 1
                    sim_tag = " [TEST SIMULATED]" if res.get('simulated') else ""
                    self.stdout.write(f"  Sent reminder to {res['student']} ({res['phone']}){sim_tag}")
                else:
                    total_skipped += 1
                    self.stdout.write(f"  Skipped {res['student']}: {res.get('reason', 'Already processed')}")

        self.stdout.write(
            self.style.SUCCESS(
                f"Completed class reminders: {total_sent} reminder(s) dispatched, {total_skipped} skipped."
            )
        )
