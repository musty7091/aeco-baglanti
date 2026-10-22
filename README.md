# AECO Bağlantılı Satış ve Sevkiyat Yönetimi

AECO TRADING LTD. için bağlantılı satış faturalarını, müşteri bakiyelerini, siparişleri ve sevkiyatları yöneten Django tabanlı web/PWA uygulamasıdır. Canlı sürüm PythonAnywhere üzerinde çalışır; kurulum ve güncelleme adımları için `DEPLOY_PYTHONANYWHERE.md` dosyasına bakın. Sürüm geçmişi `DEGISIKLIKLER.txt` dosyasındadır.

## Temel özellikler

- Otomatik ve sıralı müşteri kodu: `MUS-00001`, `MUS-00002`…
- Satış faturası bazında bağlantılı ürün takibi
- İskonto ve KDV dâhil güvenilir satır/fatura toplamları
- Müşteri, ürün, sipariş, sevkiyat, PDF ve Excel işlemleri
- Rol bazlı yönetim, satış, depo ve sevkiyat yetkileri
- Mobil uyumlu PWA (ana ekrana eklenebilir)
- PDF, JPG, JPEG ve PNG fatura eki yükleme (telefonda kamerayla)
- Doğrulanabilir (QR kodlu) sevk tutanağı

## Bilgisayarda geliştirme ortamı

```bash
python -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # Linux/macOS: cp .env.example .env
python manage.py migrate
python manage.py demo_aeco      # isteğe bağlı demo verisi
python manage.py runserver
```

Demo verisi tüm demo kullanıcıları için `Demo1234!` şifresini kullanır (`demo_admin`, `demo_yonetim`, `demo_satis`, `demo_depo`, `demo_sevkiyat`). Demo kayıtlarını silmek için `python manage.py demo_aeco --clear` kullanın. Demo verisini canlı sistemde oluşturmayın.

## Demo içerik

- 3 müşteri, 10 ürün
- 3 bağlantılı satış faturası
- 4 sipariş, 2 sevkiyat
- 2 depo
- Yönetim, satış, depo ve sevkiyat rolleri

## Teknik kontroller

```bash
python manage.py check
python manage.py test operations
python manage.py makemigrations operations --check --dry-run
```

## Teknik yapı

- Python 3.13
- Django 5.2.16
- SQLite
- ReportLab
- OpenPyXL
- Pillow / QRCode
- WhiteNoise
