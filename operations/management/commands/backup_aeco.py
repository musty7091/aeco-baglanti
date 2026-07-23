from pathlib import Path
import shutil
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

class Command(BaseCommand):
    help='SQLite veritabanının tarihli yerel kopyasını oluşturur.'
    def handle(self,*args,**kwargs):
        source=Path(settings.DATABASES['default']['NAME']); target_dir=Path(settings.BASE_DIR)/'backups';target_dir.mkdir(exist_ok=True)
        target=target_dir/f'db_{timezone.localtime():%Y%m%d_%H%M%S}.sqlite3'
        shutil.copy2(source,target);self.stdout.write(self.style.SUCCESS(str(target)))
