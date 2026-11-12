"""Run Google Drive backups for workspaces that need a new monthly snapshot.

Cron example (1st of each month, 02:15 IST):
  15 2 1 * * cd /path/to/cubesites_backend && ../venv/bin/python manage.py run_monthly_drive_backups

Also safe to run daily — skips workspaces already backed up this calendar month.
"""
from django.core.management.base import BaseCommand

from ops.drive_services import run_workspace_backup, workspaces_due_for_monthly_backup


class Command(BaseCommand):
    help = "Upload monthly Google Drive backups (replaces previous file per workspace)."

    def add_arguments(self, parser):
        parser.add_argument("--workspace", dest="workspace_id", default="", help="Limit to one workspace UUID")
        parser.add_argument("--force", action="store_true", help="Backup even if already done this month")

    def handle(self, *args, **options):
        from accounts.models import Workspace

        if options["workspace_id"]:
            ws = Workspace.objects.filter(pk=options["workspace_id"]).first()
            if not ws:
                self.stderr.write("Workspace not found.")
                return
            targets = [ws]
        elif options["force"]:
            targets = list(
                Workspace.objects.filter(drive_status="connected").exclude(drive_refresh_token="")
            )
        else:
            targets = workspaces_due_for_monthly_backup()

        self.stdout.write(f"Backing up {len(targets)} workspace(s)…")
        ok = fail = 0
        for ws in targets:
            try:
                job = run_workspace_backup(ws, job_type="scheduled")
                ok += 1
                self.stdout.write(self.style.SUCCESS(f"  {ws.business_name}: {job.note}"))
            except Exception as e:
                fail += 1
                self.stderr.write(self.style.ERROR(f"  {ws.business_name}: {e}"))
        self.stdout.write(f"Done. success={ok} failed={fail}")
