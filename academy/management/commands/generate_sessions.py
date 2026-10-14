from django.core.management.base import BaseCommand
from academy.services import generate_future_sessions
from academy.models import Batch


class Command(BaseCommand):
    help = "Generates upcoming class sessions from recurring batch schedules."

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=60,
            help='Number of days ahead to generate sessions for (default: 60).'
        )
        parser.add_argument(
            '--batch-id',
            type=int,
            default=None,
            help='Generate sessions only for a specific batch ID.'
        )

    def handle(self, *args, **options):
        days = options['days']
        batch_id = options.get('batch_id')
        batch = None
        if batch_id:
            batch = Batch.objects.filter(id=batch_id).first()
            if not batch:
                self.stderr.write(f"Batch with ID {batch_id} not found.")
                return

        self.stdout.write(f"Generating upcoming sessions for horizon of {days} days...")
        result = generate_future_sessions(batch=batch, horizon_days=days)
        self.stdout.write(
            self.style.SUCCESS(
                f"Done! Created: {result['created_count']} new session(s). Skipped: {result['skipped_count']} existing session(s)."
            )
        )
        if result['conflicts']:
            self.stdout.write(self.style.WARNING("Scheduling Conflict Notices:"))
            for c in result['conflicts']:
                self.stdout.write(f"  - {c}")
