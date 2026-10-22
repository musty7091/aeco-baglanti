# PythonAnywhere Kurulum Notu

Canlı uygulama PythonAnywhere üzerinde çalışır. Bu not ilk kurulumu ve güncelleme adımlarını anlatır.

## Kurulum

1. Proje ZIP'ini PythonAnywhere Files bölümüne yükleyin ve açın.
2. Python 3.13 veya uyumlu güncel Python sürümüyle sanal ortam oluşturun.
3. Sanal ortamda bağımlılıkları kurun:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

4. `.env.example` dosyasını `.env` adıyla kopyalayın ve güvenli ayarları yapın.
5. Temiz veritabanını oluşturun:

```bash
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py setup_aeco --username admin --email EMAIL_ADRESINIZ
python manage.py check --deploy
```

Migrasyonlar `operations/migrations/` altındadır; `migrate` hepsini sırayla uygular.

## WSGI

`pythonanywhere_wsgi.py.example` içindeki proje yolunu kendi kullanıcı adınıza göre düzenleyin ve PythonAnywhere WSGI yapılandırmasına uygulayın.

## Static ve media

PythonAnywhere Web ekranında aşağıdaki eşleştirmeleri tanımlayın:

- `/static/` → proje içindeki `staticfiles` klasörü
- `/media/` → proje içindeki `media` klasörü

## Güncelleme

Her güncellemeden önce veritabanı yedeği alın. PythonAnywhere Bash konsolunda:

```bash
P=~/.virtualenvs/aeco-baglanti/bin/python; cd ~/aeco-baglanti && B=backups/db_$(date +%Y%m%d_%H%M%S).sqlite3 && mkdir -p backups && sqlite3 db.sqlite3 ".backup $B" && sqlite3 "$B" 'PRAGMA integrity_check;' && git status --short && git pull --ff-only origin main && $P manage.py check && $P manage.py migrate --plan && $P manage.py migrate && $P manage.py collectstatic --noinput | tail -1 && touch /var/www/aecobaglanti_pythonanywhere_com_wsgi.py && echo DEPLOY_OK
```

`git status --short` boş olmalıdır; sunucuda elle değiştirilmiş dosya varsa önce onları inceleyin. `backups/` klasöründe son birkaç yedeği tutup eskileri silebilirsiniz.
