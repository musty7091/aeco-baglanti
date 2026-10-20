# AECO Bağlantılı Satış ve Sevkiyat Yönetimi v1.8.0

AECO TRADING LTD. için bağlantılı satış faturalarını, müşteri bakiyelerini, siparişleri ve sevkiyatları yerel ağda yöneten Django tabanlı Windows/PWA uygulamasıdır.

## Temel özellikler

- Otomatik ve sıralı müşteri kodu: `MUS-00001`, `MUS-00002`…
- Satış faturası bazında bağlantılı ürün takibi
- İskonto ve KDV dâhil güvenilir satır/fatura toplamları
- Müşteri, ürün, sipariş, sevkiyat, PDF ve Excel işlemleri
- Rol bazlı yönetim, satış, depo ve sevkiyat yetkileri
- Mobil uyumlu yerel PWA
- USB/ağ evrak tarayıcıları için ücretsiz Windows WIA yerel servisi
- PDF, JPG, JPEG ve PNG fatura eki yükleme
- Çok sayfalı taramayı tek PDF olarak fatura formuna ekleme
- SQLite ve tamamen yerel çalışma

## Windows temiz kurulum

1. ZIP içeriğini `C:\aeco-baglanti` klasörüne çıkarın.
2. Python 3.13 kurulu değilse kurun ve `Add Python to PATH` seçeneğini işaretleyin.
3. `SETUP_WINDOWS.bat` dosyasını çalıştırın. Mevcut v1.6 demo veritabanı varsa `backups` klasörüne alınır ve v1.7.1 temiz şeması kurulur.
4. Demo ortamı için `DEMO_VERI_OLUSTUR.bat` dosyasını çalıştırın.
5. Bilgisayarda `RUN_WINDOWS.bat` dosyasını açın.
6. Aynı Wi-Fi ağındaki telefonlar için bir kez `MOBIL_ERISIM_IZNI.bat`, ardından `RUN_MOBILE_LAN.bat` kullanın.

Demo giriş bilgileri:

- Kullanıcı: `demo_admin`
- Şifre: `Demo1234!`

## Fiziksel tarayıcı kullanımı

`RUN_WINDOWS.bat`, Django uygulamasıyla birlikte yerel tarama servisini de otomatik başlatır. Servis yalnızca `127.0.0.1:8765` adresini dinler ve uygulamayla paylaşılan gizli token olmadan işlem yapmaz.

Yeni bağlantılı satış ekranında:

1. **Tarayıcıdan Tara** seçeneğini açın.
2. Windows'ta görünen WIA tarayıcısını seçin.
3. Her sayfa için **Sayfa Tara** düğmesine basın.
4. **PDF'i Oluştur ve Ekle** ile sayfaları tek PDF'e dönüştürün.
5. Oluşan PDF formdaki satış faturası ekine otomatik atanır.

Fiziksel WIA taraması telefon tarayıcısından çalıştırılmaz. Telefonda **Dosyadan Seç** ile PDF veya kamera fotoğrafı yüklenebilir.

Tarayıcı görünmüyorsa Windows **Ayarlar > Bluetooth ve cihazlar > Yazıcılar ve tarayıcılar** bölümünde cihazın kurulu ve açık olduğunu kontrol edin. Gerekirse `SCANNER_SERVICE.bat` dosyasını ayrı açarak servis hata mesajını inceleyin.

## Demo içerik

- 3 müşteri
- 10 ürün
- 3 bağlantılı satış faturası
- 4 sipariş
- 2 sevkiyat
- 2 depo
- 2 araç
- Yönetim, satış, depo ve sevkiyat rolleri

Demo ürünleri arasında doğru UTF-8 metinlerle `Jägermeister`, `Moët & Chandon`, `Şahin` ve `Şube` örnekleri bulunur.

## Teknik kontroller

Windows'ta kurulumdan sonra `TEST_WINDOWS.bat` dosyası sistem kontrolünü, model-migrasyon eşleşmesini ve operations testlerini tek seferde çalıştırır.

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
- pywin32 / WIA (yalnızca Windows tarama servisi)
