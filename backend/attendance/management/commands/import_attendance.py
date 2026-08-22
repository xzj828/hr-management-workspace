from decimal import Decimal
from pathlib import Path

from django.contrib.auth.models import User
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from attendance.models import ImportBatch
from attendance.services import process_import_batch


class Command(BaseCommand):
    help = "从命令行导入一份打卡 Excel，适合首次部署验证"

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--year", type=int, required=True)
        parser.add_argument("--month", type=int, required=True)
        parser.add_argument("--expected-days", type=Decimal, default=Decimal("25"))
        parser.add_argument("--username", default="admin")

    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.exists():
            raise CommandError(f"文件不存在：{path}")
        try:
            user = User.objects.get(username=options["username"])
        except User.DoesNotExist as exc:
            raise CommandError("指定管理员账号不存在") from exc
        from attendance.services import file_sha256

        with path.open("rb") as handle:
            django_file = File(handle, name=path.name)
            digest = file_sha256(django_file)
            existing = ImportBatch.objects.filter(
                file_sha256=digest,
                year=options["year"],
                month=options["month"],
            ).first()
            if existing:
                self.stdout.write(f"文件已导入，批次 ID={existing.id}")
                return
            batch = ImportBatch.objects.create(
                original_filename=path.name,
                source_file=django_file,
                file_sha256=digest,
                year=options["year"],
                month=options["month"],
                default_expected_days=options["expected_days"],
                uploaded_by=user,
            )
        process_import_batch(batch)
        self.stdout.write(
            self.style.SUCCESS(
                f"导入完成：批次 {batch.id}，总行 {batch.total_rows}，匹配 {batch.matched_rows}，"
                f"未匹配 {batch.unmatched_rows}，跨日疑似 {batch.suspicion_count}"
            )
        )
