# PythonAnywhere Kurulum Notu

Bu proje öncelikle **Windows yerel ağ uygulaması** olarak tasarlanmıştır. PythonAnywhere üzerinde Django uygulaması çalıştırılabilir; ancak Windows'a bağlı fiziksel evrak tarayıcısına WIA üzerinden erişilemez. Bulut kullanımında yalnızca **Dosyadan Seç** yükleme yöntemi kullanılmalıdır.

## Kurulum

1. Proje ZIP'ini PythonAnywhere Files bölümüne yükleyin ve açın.
2. Python 3.13 veya uyumlu güncel Python sürümüyle sanal ortam oluşturun.
3. Sanal ortamda bağımlılıkları kurun:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

`pywin32` yalnızca Windows'ta kurulur; Linux tabanlı PythonAnywhere ortamında otomatik olarak atlanır.

4. `.env.example` dosyasını `.env` adıyla kopyalayın ve güvenli ayarları yapın.
5. Temiz veritabanını oluşturun:

```bash
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py setup_aeco --username admin --email EMAIL_ADRESINIZ
python manage.py check --deploy
```

Bu sürüm tek ve güncel `operations/migrations/0001_initial.py` migrasyonunu kullanır. Eski demo veritabanını yeni şemaya taşımaya çalışmayın.

## WSGI

`pythonanywhere_wsgi.py.example` içindeki proje yolunu kendi kullanıcı adınıza göre düzenleyin ve PythonAnywhere WSGI yapılandırmasına uygulayın.

## Static ve media

PythonAnywhere Web ekranında aşağıdaki eşleştirmeleri tanımlayın:

- `/static/` → proje içindeki `staticfiles` klasörü
- `/media/` → proje içindeki `media` klasörü

## Önemli sınırlama

- **Tarayıcıdan Tara** özelliği yalnızca Windows bilgisayarda çalışan `scanner_service.py` ve yerel WIA cihazlarıyla kullanılabilir.
- PythonAnywhere, telefon veya başka bir uzak sunucu fiziksel Windows tarayıcısına doğrudan erişemez.
- PDF/JPG/JPEG/PNG dosyaları normal dosya yükleme alanından eklenebilir.
