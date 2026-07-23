from __future__ import annotations

import ipaddress
import json
import os
import platform
import re
import secrets
import shutil
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image

BASE_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = BASE_DIR / 'runtime'
TOKEN_FILE = RUNTIME_DIR / 'scanner_token.txt'
TEMP_ROOT = RUNTIME_DIR / 'scanner_temp'
SESSION_ROOT = TEMP_ROOT / 'sessions'
DOCUMENT_ROOT = TEMP_ROOT / 'documents'
HOST = '127.0.0.1'
PORT = int(os.getenv('AECO_SCANNER_PORT', '8765'))
MAX_REQUEST_BYTES = 64 * 1024
MAX_PAGES = 100
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
SESSION_TTL_SECONDS = 30 * 60
DOCUMENT_TTL_SECONDS = 60 * 60
WIA_SCANNER_DEVICE_TYPE = 1
WIA_FORMAT_PNG = '{B96B3CAF-0728-11D3-9D7B-0000F81EF32E}'
ID_RE = re.compile(r'^[a-f0-9]{32}$')

SESSIONS: dict[str, dict] = {}
SESSIONS_LOCK = threading.RLock()


def ensure_runtime() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_ROOT.mkdir(parents=True, exist_ok=True)
    DOCUMENT_ROOT.mkdir(parents=True, exist_ok=True)


def get_token() -> str:
    ensure_runtime()
    if TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text(encoding='utf-8').strip()
        if len(token) >= 32:
            return token
    token = secrets.token_urlsafe(32)
    TOKEN_FILE.write_text(token, encoding='utf-8')
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except OSError:
        pass
    return token


def is_windows() -> bool:
    return platform.system().lower() == 'windows'


def _property_value(properties, name: str, default=''):
    try:
        count = properties.Count
        for index in range(1, count + 1):
            prop = properties.Item(index)
            if str(prop.Name).lower() == name.lower():
                return prop.Value
    except Exception:
        pass
    return default


@contextmanager
def _wia_manager():
    if not is_windows():
        raise RuntimeError('Fiziksel WIA tarama yalnızca Windows bilgisayarda kullanılabilir.')
    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:
        raise RuntimeError(
            'WIA bileşeni yüklenemedi. SETUP_WINDOWS.bat dosyasını yeniden çalıştırın.'
        ) from exc
    pythoncom.CoInitialize()
    try:
        yield win32com.client.Dispatch('WIA.DeviceManager')
    finally:
        pythoncom.CoUninitialize()


def list_scanners() -> list[dict[str, str]]:
    devices = []
    with _wia_manager() as manager:
        infos = manager.DeviceInfos
        for index in range(1, infos.Count + 1):
            info = infos.Item(index)
            if int(info.Type) != WIA_SCANNER_DEVICE_TYPE:
                continue
            name = _property_value(info.Properties, 'Name', f'Tarayıcı {index}')
            description = _property_value(info.Properties, 'Description', '')
            devices.append({
                'id': str(info.DeviceID),
                'name': str(name),
                'description': str(description or ''),
            })
    return devices


def _find_device(manager, device_id: str):
    infos = manager.DeviceInfos
    for index in range(1, infos.Count + 1):
        info = infos.Item(index)
        if int(info.Type) == WIA_SCANNER_DEVICE_TYPE and str(info.DeviceID) == device_id:
            return info.Connect()
    raise RuntimeError('Seçilen tarayıcı bulunamadı veya bağlantısı kesildi.')


def scan_page(device_id: str, output_path: Path) -> None:
    with _wia_manager() as manager:
        device = _find_device(manager, device_id)
        try:
            item = device.Items.Item(1)
        except Exception as exc:
            raise RuntimeError('Tarayıcıda kullanılabilir tarama kaynağı bulunamadı.') from exc
        try:
            image_file = item.Transfer(WIA_FORMAT_PNG)
            image_file.SaveFile(str(output_path))
        except Exception as exc:
            message = str(exc)
            if 'cancel' in message.lower() or '0x80210064' in message.lower():
                raise RuntimeError('Tarama kullanıcı tarafından iptal edildi.') from exc
            raise RuntimeError(
                'Belge taranamadı. Tarayıcının açık, hazır ve kâğıdın doğru yerleştirilmiş olduğunu kontrol edin.'
            ) from exc


def images_to_pdf(image_paths: list[Path], output_path: Path) -> None:
    images = []
    try:
        for path in image_paths:
            with Image.open(path) as source:
                image = source.convert('RGB')
                image.load()
                images.append(image.copy())
        if not images:
            raise RuntimeError('PDF oluşturmak için taranmış sayfa bulunmuyor.')
        first, rest = images[0], images[1:]
        first.save(
            output_path,
            'PDF',
            resolution=300.0,
            save_all=True,
            append_images=rest,
        )
    finally:
        for image in images:
            image.close()


def cleanup_temp_files() -> None:
    now = time.time()
    ensure_runtime()
    with SESSIONS_LOCK:
        stale_sessions = [
            session_id
            for session_id, data in SESSIONS.items()
            if now - data.get('updated_at', now) > SESSION_TTL_SECONDS
        ]
        for session_id in stale_sessions:
            data = SESSIONS.pop(session_id, None)
            if data:
                shutil.rmtree(data['folder'], ignore_errors=True)

    for folder in SESSION_ROOT.iterdir():
        try:
            if folder.is_dir() and now - folder.stat().st_mtime > SESSION_TTL_SECONDS:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            pass
    for file_path in DOCUMENT_ROOT.glob('*.pdf'):
        try:
            if now - file_path.stat().st_mtime > DOCUMENT_TTL_SECONDS:
                file_path.unlink(missing_ok=True)
        except OSError:
            pass


def _is_private_or_loopback(hostname: str | None) -> bool:
    if not hostname:
        return False
    if hostname.lower() == 'localhost':
        return True
    try:
        address = ipaddress.ip_address(hostname)
        return address.is_loopback or address.is_private
    except ValueError:
        return False


class ScannerRequestHandler(BaseHTTPRequestHandler):
    server_version = 'AECOScanner/1.0'

    def log_message(self, fmt, *args):
        sys.stdout.write('[SCANNER] ' + (fmt % args) + '\n')
        sys.stdout.flush()

    def _origin(self) -> str | None:
        origin = self.headers.get('Origin')
        if not origin:
            return None
        try:
            parsed = urlparse(origin)
        except ValueError:
            return None
        if parsed.scheme not in {'http', 'https'} or not _is_private_or_loopback(parsed.hostname):
            return None
        return origin

    def _cors_headers(self):
        origin = self._origin()
        if origin:
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-AECO-Scanner-Token')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')

    def _send_json(self, status: int, payload: dict):
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self._cors_headers()
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_error(self, status: int, message: str):
        self._send_json(status, {'ok': False, 'error': message})

    def _local_client(self) -> bool:
        return _is_private_or_loopback(self.client_address[0]) and ipaddress.ip_address(
            self.client_address[0]
        ).is_loopback

    def _authorized(self) -> bool:
        supplied = self.headers.get('X-AECO-Scanner-Token', '')
        return self._local_client() and secrets.compare_digest(supplied, get_token())

    def _require_authorized(self) -> bool:
        if not self._local_client():
            self._send_error(HTTPStatus.FORBIDDEN, 'Tarama servisi yalnızca bu Windows bilgisayardan kullanılabilir.')
            return False
        if not self._authorized():
            self._send_error(HTTPStatus.UNAUTHORIZED, 'Tarama servisi yetkilendirmesi geçersiz.')
            return False
        origin_header = self.headers.get('Origin')
        if origin_header and not self._origin():
            self._send_error(HTTPStatus.FORBIDDEN, 'İstek kaynağına izin verilmiyor.')
            return False
        return True

    def _read_json(self) -> dict:
        length = int(self.headers.get('Content-Length', '0') or '0')
        if length < 0 or length > MAX_REQUEST_BYTES:
            raise ValueError('İstek boyutu geçersiz.')
        raw = self.rfile.read(length) if length else b'{}'
        try:
            payload = json.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError('Geçerli JSON gönderilmelidir.') from exc
        if not isinstance(payload, dict):
            raise ValueError('İstek gövdesi nesne olmalıdır.')
        return payload

    def do_OPTIONS(self):
        if self.headers.get('Origin') and not self._origin():
            self._send_error(HTTPStatus.FORBIDDEN, 'İstek kaynağına izin verilmiyor.')
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        cleanup_temp_files()
        path = urlparse(self.path).path
        if path == '/health':
            self._send_json(HTTPStatus.OK, {
                'ok': True,
                'service': 'AECO Yerel Tarama Servisi',
                'platform': platform.system(),
                'wia_available': is_windows(),
            })
            return
        if not self._require_authorized():
            return
        if path == '/devices':
            try:
                devices = list_scanners()
                self._send_json(HTTPStatus.OK, {'ok': True, 'devices': devices})
            except RuntimeError as exc:
                self._send_error(HTTPStatus.SERVICE_UNAVAILABLE, str(exc))
            return
        match = re.fullmatch(r'/files/([a-f0-9]{32})\.pdf', path)
        if match:
            file_id = match.group(1)
            file_path = DOCUMENT_ROOT / f'{file_id}.pdf'
            if not file_path.is_file():
                self._send_error(HTTPStatus.NOT_FOUND, 'Taranan PDF bulunamadı veya süresi doldu.')
                return
            data = file_path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self._cors_headers()
            self.send_header('Content-Type', 'application/pdf')
            self.send_header('Content-Disposition', 'attachment; filename="taranan-fatura.pdf"')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self._send_error(HTTPStatus.NOT_FOUND, 'Endpoint bulunamadı.')

    def do_POST(self):
        cleanup_temp_files()
        if not self._require_authorized():
            return
        path = urlparse(self.path).path
        try:
            payload = self._read_json()
            if path == '/sessions':
                device_id = str(payload.get('device_id', '')).strip()
                if not device_id:
                    raise ValueError('Tarayıcı seçilmelidir.')
                available_ids = {device['id'] for device in list_scanners()}
                if device_id not in available_ids:
                    raise RuntimeError('Seçilen tarayıcı artık kullanılamıyor.')
                session_id = secrets.token_hex(16)
                folder = SESSION_ROOT / session_id
                folder.mkdir(parents=True, exist_ok=False)
                with SESSIONS_LOCK:
                    SESSIONS[session_id] = {
                        'device_id': device_id,
                        'folder': folder,
                        'pages': [],
                        'updated_at': time.time(),
                        'busy': False,
                    }
                self._send_json(HTTPStatus.CREATED, {
                    'ok': True,
                    'session_id': session_id,
                    'page_count': 0,
                })
                return

            page_match = re.fullmatch(r'/sessions/([a-f0-9]{32})/pages', path)
            if page_match:
                session_id = page_match.group(1)
                with SESSIONS_LOCK:
                    session = SESSIONS.get(session_id)
                    if not session:
                        raise RuntimeError('Tarama oturumu bulunamadı veya süresi doldu.')
                    if session.get('busy'):
                        raise RuntimeError('Bu tarama oturumunda başka bir işlem devam ediyor.')
                    if len(session['pages']) >= MAX_PAGES:
                        raise RuntimeError(f'Bir belgede en fazla {MAX_PAGES} sayfa taranabilir.')
                    session['busy'] = True
                    page_number = len(session['pages']) + 1
                    output_path = session['folder'] / f'page-{page_number:03d}.png'
                    device_id = session['device_id']
                try:
                    scan_page(device_id, output_path)
                except Exception:
                    with SESSIONS_LOCK:
                        current = SESSIONS.get(session_id)
                        if current:
                            current['busy'] = False
                            current['updated_at'] = time.time()
                    output_path.unlink(missing_ok=True)
                    raise
                with SESSIONS_LOCK:
                    session = SESSIONS.get(session_id)
                    if not session:
                        output_path.unlink(missing_ok=True)
                        raise RuntimeError('Tarama oturumu sona erdi.')
                    session['pages'].append(output_path)
                    session['busy'] = False
                    session['updated_at'] = time.time()
                    count = len(session['pages'])
                self._send_json(HTTPStatus.OK, {
                    'ok': True,
                    'page_count': count,
                    'message': f'{count}. sayfa tarandı.',
                })
                return

            finish_match = re.fullmatch(r'/sessions/([a-f0-9]{32})/finish', path)
            if finish_match:
                session_id = finish_match.group(1)
                with SESSIONS_LOCK:
                    session = SESSIONS.get(session_id)
                    if not session:
                        raise RuntimeError('Tarama oturumu bulunamadı veya süresi doldu.')
                    if session.get('busy'):
                        raise RuntimeError('Bu tarama oturumunda başka bir işlem devam ediyor.')
                    pages = list(session['pages'])
                    if not pages:
                        raise RuntimeError('Önce en az bir sayfa tarayın.')
                    session['busy'] = True
                file_id = secrets.token_hex(16)
                output_path = DOCUMENT_ROOT / f'{file_id}.pdf'
                try:
                    images_to_pdf(pages, output_path)
                    if output_path.stat().st_size > MAX_DOCUMENT_BYTES:
                        output_path.unlink(missing_ok=True)
                        raise RuntimeError(
                            'Oluşturulan PDF 10 MB sınırını aşıyor. Daha az sayfa tarayın veya tarayıcı çözünürlüğünü düşürün.'
                        )
                except Exception:
                    with SESSIONS_LOCK:
                        current = SESSIONS.get(session_id)
                        if current:
                            current['busy'] = False
                            current['updated_at'] = time.time()
                    raise
                with SESSIONS_LOCK:
                    session = SESSIONS.pop(session_id, None)
                if session:
                    shutil.rmtree(session['folder'], ignore_errors=True)
                self._send_json(HTTPStatus.OK, {
                    'ok': True,
                    'file_id': file_id,
                    'filename': f'taranan-fatura-{time.strftime("%Y%m%d-%H%M%S")}.pdf',
                    'page_count': len(pages),
                    'download_url': f'/files/{file_id}.pdf',
                })
                return

            self._send_error(HTTPStatus.NOT_FOUND, 'Endpoint bulunamadı.')
        except ValueError as exc:
            self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        except RuntimeError as exc:
            self._send_error(HTTPStatus.SERVICE_UNAVAILABLE, str(exc))
        except Exception:
            traceback.print_exc()
            self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, 'Tarama işlemi sırasında beklenmeyen bir hata oluştu.')

    def do_DELETE(self):
        if not self._require_authorized():
            return
        path = urlparse(self.path).path
        match = re.fullmatch(r'/sessions/([a-f0-9]{32})', path)
        if not match:
            self._send_error(HTTPStatus.NOT_FOUND, 'Endpoint bulunamadı.')
            return
        session_id = match.group(1)
        with SESSIONS_LOCK:
            session = SESSIONS.get(session_id)
            if session and session.get('busy'):
                self._send_error(HTTPStatus.CONFLICT, 'Tarama işlemi devam ederken oturum kapatılamaz.')
                return
            session = SESSIONS.pop(session_id, None)
        if session:
            shutil.rmtree(session['folder'], ignore_errors=True)
        self._send_json(HTTPStatus.OK, {'ok': True})


class ScannerHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> int:
    ensure_runtime()
    get_token()
    cleanup_temp_files()
    server = ScannerHTTPServer((HOST, PORT), ScannerRequestHandler)
    print(f'AECO Yerel Tarama Servisi: http://{HOST}:{PORT}')
    print('Servis yalnızca localhost üzerinden erişilebilir.')
    if not is_windows():
        print('UYARI: WIA tarama yalnızca Windows üzerinde kullanılabilir.')
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print('\nTarama servisi kapatıldı.')
    finally:
        server.server_close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
