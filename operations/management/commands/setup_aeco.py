from getpass import getpass
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from operations.models import CompanySettings, UserProfile, Warehouse

class Command(BaseCommand):
    help='AECO ilk şirket, depo ve yönetici kaydını oluşturur.'
    def add_arguments(self,parser):
        parser.add_argument('--username',default='admin')
        parser.add_argument('--email',default='')
        parser.add_argument('--password',default='')
    def handle(self,*args,**opts):
        CompanySettings.get_solo()
        Warehouse.objects.get_or_create(code='ANA',defaults={'name':'Ana Depo','is_active':True})
        username=opts['username'];password=opts['password']
        user=User.objects.filter(username=username).first()
        if not user:
            if not password:
                password=getpass('Yönetici şifresi: ')
                confirm=getpass('Şifre tekrar: ')
                if password != confirm: raise CommandError('Şifreler aynı değil.')
            if len(password)<8: raise CommandError('Şifre en az 8 karakter olmalıdır.')
            user=User.objects.create_superuser(username=username,email=opts['email'],password=password)
            self.stdout.write(self.style.SUCCESS(f'Yönetici oluşturuldu: {username}'))
        else:
            self.stdout.write(self.style.WARNING(f'Kullanıcı zaten mevcut: {username}'))
        profile,_=UserProfile.objects.get_or_create(user=user);profile.role=UserProfile.Role.ADMIN;profile.active=True;profile.save()
        self.stdout.write(self.style.SUCCESS('AECO başlangıç ayarları hazır.'))
