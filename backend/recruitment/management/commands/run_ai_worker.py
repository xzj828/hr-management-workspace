import time

from django.conf import settings
from django.core.management.base import BaseCommand

from recruitment.services.ai_tasks import execute_task, lease_next_task


class Command(BaseCommand):
    help = "运行本地简历智能处理 Worker"

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        poll_seconds = float(getattr(settings, "AI_POLL_SECONDS", 3))
        while True:
            task = lease_next_task()
            if task:
                execute_task(task)
            if options["once"]:
                return
            time.sleep(poll_seconds)
