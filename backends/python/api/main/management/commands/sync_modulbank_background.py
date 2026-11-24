from django.core.management.base import BaseCommand
from django.utils import timezone

from main.background_sync_schedule import is_background_sync_due
from main.modulbank import ModulbankAuthError
from main.models import ModulbankCredentials, TochkaPortalPreferences
from main.modulbank_sync_logic import run_modulbank_sync
from main.tochka_sync_logic import run_post_sync_processing


class Command(BaseCommand):
    help = (
        "Sync due Modulbank portals using their saved background-sync interval. "
        "Run every minute from cron; use --force for an immediate administrator run."
    )

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=2, help="Calendar days to look back per portal (default 2)")
        parser.add_argument("--force", action="store_true", help="Sync every connected portal regardless of schedule")

    def handle(self, *args, **options):
        days = max(int(options["days"]), 1)
        force = bool(options["force"])
        credentials = list(ModulbankCredentials.objects.filter(is_connected=True))
        preferences = {pref.member_id: pref for pref in TochkaPortalPreferences.objects.all()}
        now = timezone.now()
        due = [
            creds
            for creds in credentials
            if is_background_sync_due(
                enabled=bool(preferences.get(creds.member_id) and preferences[creds.member_id].client_auto_sync_enabled),
                interval_minutes=(
                    preferences[creds.member_id].client_auto_sync_interval_minutes
                    if preferences.get(creds.member_id)
                    else 15
                ),
                last_attempt_at=creds.last_sync_attempt_at,
                now=now,
                force=force,
            )
        ]

        self.stdout.write(self.style.NOTICE(
            f"sync_modulbank_background: {len(due)}/{len(credentials)} due connected member(s), days={days}, force={force}"
        ))

        for creds in due:
            ModulbankCredentials.objects.filter(pk=creds.pk).update(last_sync_attempt_at=timezone.now())
            try:
                result = run_modulbank_sync(creds.member_id, days=days)
                run_post_sync_processing(creds.member_id, result)
                self.stdout.write(self.style.SUCCESS(f"  {creds.member_id}: synced {result['synced']}"))
            except ModulbankAuthError:
                ModulbankCredentials.objects.filter(pk=creds.pk).update(is_connected=False)
                self.stderr.write(self.style.ERROR(f"  {creds.member_id}: API key rejected, disconnected"))
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"  {creds.member_id}: {e}"))
