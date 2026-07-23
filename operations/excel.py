from io import BytesIO

from django.contrib.auth.models import User
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

from .models import Customer, Product, UserProfile

HEADER_FILL = 'E71922'


def styled_workbook(title, headers):
    wb = Workbook()
    ws = wb.active
    ws.title = title
    for col, header in enumerate(headers, 1):
        cell = ws.cell(1, col, header)
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill('solid', fgColor=HEADER_FILL)
        cell.alignment = Alignment(horizontal='center')
        ws.column_dimensions[cell.column_letter].width = max(14, len(header) + 3)
    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = f'A1:{ws.cell(1, len(headers)).coordinate}'
    return wb, ws


def workbook_bytes(wb):
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output.getvalue()


def product_template():
    headers = ['Barkod*', 'Ürün Adı*', 'Marka', 'Hacim', 'Aktif (E/H)']
    wb, ws = styled_workbook('Ürünler', headers)
    ws.append(['8690000000000', 'Örnek Ürün 100 cl', 'Örnek Marka', '100 cl', 'E'])
    return workbook_bytes(wb)


def customer_template():
    headers = [
        'Müşteri Kodu (yalnızca güncelleme)',
        'Ticari Unvan*',
        'Yetkili',
        'Telefon',
        'E-posta',
        'Satış Temsilcisi Kullanıcı Adı',
        'Notlar',
        'Aktif (E/H)',
    ]
    wb, ws = styled_workbook('Müşteriler', headers)
    ws.append(['', 'Örnek Market', 'Yetkili', '0533...', '', 'demo_satis', '', 'E'])
    ws.append(['MUS-00001', 'Mevcut müşteriyi güncelleme örneği', '', '', '', '', '', 'E'])
    return workbook_bytes(wb)


def _normalized_header(value):
    return (
        str(value or '')
        .strip()
        .lower()
        .replace('*', '')
        .replace('ı', 'i')
        .replace('ş', 's')
        .replace('ğ', 'g')
        .replace('ü', 'u')
        .replace('ö', 'o')
        .replace('ç', 'c')
    )


def _header_map(ws):
    return {_normalized_header(cell.value): idx for idx, cell in enumerate(ws[1])}


def _cell(row, mapping, *names, default=''):
    for name in names:
        idx = mapping.get(_normalized_header(name))
        if idx is not None and idx < len(row):
            value = row[idx]
            return default if value is None else value
    return default


def _is_active(value):
    return str(value or 'E').strip().upper() not in {'H', 'HAYIR', '0', 'FALSE', 'PASİF', 'PASIF'}


def import_products(file):
    wb = load_workbook(file, data_only=True)
    ws = wb.active
    mapping = _header_map(ws)
    created = updated = 0
    errors = []
    for row_no, row in enumerate(ws.iter_rows(min_row=2, values_only=True), 2):
        if not any(row):
            continue
        try:
            barcode = str(_cell(row, mapping, 'Barkod')).strip()
            name = str(_cell(row, mapping, 'Ürün Adı', 'Ürün')).strip()
            if not barcode or not name:
                raise ValueError('Barkod ve ürün adı zorunludur.')
            defaults = {
                'name': name,
                'brand': str(_cell(row, mapping, 'Marka')).strip(),
                'volume': str(_cell(row, mapping, 'Hacim')).strip(),
                'category': '',
                'units_per_case': 1,
                'base_unit': Product.Unit.PIECE,
                'is_active': _is_active(_cell(row, mapping, 'Aktif (E/H)', 'Aktif', default='E')),
            }
            _, is_created = Product.objects.update_or_create(barcode=barcode, defaults=defaults)
            created += int(is_created)
            updated += int(not is_created)
        except Exception as exc:
            errors.append(f'Satır {row_no}: {exc}')
    return created, updated, errors


def import_customers(file):
    """Yeni müşterilerde kodu sistem üretir; kod yalnızca mevcut kaydı bulmak için kullanılır."""
    wb = load_workbook(file, data_only=True)
    ws = wb.active
    mapping = _header_map(ws)
    created = updated = 0
    errors = []

    for row_no, row in enumerate(ws.iter_rows(min_row=2, values_only=True), 2):
        if not any(row):
            continue
        try:
            code = str(_cell(
                row,
                mapping,
                'Müşteri Kodu (yalnızca güncelleme)',
                'Müşteri Kodu',
                'Kod',
            )).strip()
            name = str(_cell(row, mapping, 'Ticari Unvan', 'Unvan')).strip()
            if not name:
                raise ValueError('Ticari unvan zorunludur.')

            salesperson_username = str(_cell(
                row,
                mapping,
                'Satış Temsilcisi Kullanıcı Adı',
                'Satış Temsilcisi',
            )).strip()
            salesperson = None
            if salesperson_username:
                salesperson = User.objects.filter(
                    username=salesperson_username,
                    is_active=True,
                    profile__active=True,
                    profile__role=UserProfile.Role.SALES,
                ).first()
                if not salesperson:
                    raise ValueError(
                        f'"{salesperson_username}" aktif bir satış temsilcisi değildir.'
                    )

            defaults = {
                'name': name,
                'contact_name': str(_cell(row, mapping, 'Yetkili', 'Yetkili Kişi')).strip(),
                'phone': str(_cell(row, mapping, 'Telefon')).strip(),
                'email': str(_cell(row, mapping, 'E-posta', 'Eposta')).strip(),
                'assigned_salesperson': salesperson,
                'notes': str(_cell(row, mapping, 'Notlar', 'Not')).strip(),
                'is_active': _is_active(_cell(row, mapping, 'Aktif (E/H)', 'Aktif', default='E')),
            }

            customer = Customer.objects.filter(code=code).first() if code else None
            if code and customer is None:
                raise ValueError(
                    f'{code} kodlu müşteri bulunamadı. Yeni müşteri için kod hücresini boş bırakın.'
                )
            if customer:
                for field, value in defaults.items():
                    setattr(customer, field, value)
                customer.save()
                updated += 1
            else:
                Customer.objects.create(**defaults)
                created += 1
        except Exception as exc:
            errors.append(f'Satır {row_no}: {exc}')
    return created, updated, errors


def export_products():
    wb, ws = styled_workbook('Ürünler', ['Barkod', 'Ürün Adı', 'Marka', 'Hacim', 'Aktif'])
    for product in Product.objects.all():
        ws.append([
            product.barcode,
            product.name,
            product.brand,
            product.volume,
            'E' if product.is_active else 'H',
        ])
    return workbook_bytes(wb)


def export_customers(queryset=None):
    wb, ws = styled_workbook(
        'Müşteriler',
        [
            'Müşteri Kodu',
            'Ticari Unvan',
            'Yetkili',
            'Telefon',
            'E-posta',
            'Satış Temsilcisi Kullanıcı Adı',
            'Notlar',
            'Aktif',
        ],
    )
    for customer in (queryset if queryset is not None else Customer.objects.all()):
        ws.append([
            customer.code,
            customer.name,
            customer.contact_name,
            customer.phone,
            customer.email,
            customer.assigned_salesperson.username if customer.assigned_salesperson else '',
            customer.notes,
            'E' if customer.is_active else 'H',
        ])
    return workbook_bytes(wb)


def export_balances(queryset=None):
    from .models import ConnectionItem

    wb, ws = styled_workbook(
        'Bağlantı Bakiyeleri',
        [
            'Müşteri Kodu',
            'Müşteri',
            'Fatura',
            'Fatura Tarihi',
            'Barkod',
            'Ürün',
            'Toplam Hak',
            'Birim Fiyat',
            'İskonto (%)',
            'KDV (%)',
            'Satır Toplamı (KDV Dahil)',
            'Teslim',
            'Sipariş',
            'Kullanılabilir',
            'Birim',
        ],
    )
    lines = queryset if queryset is not None else ConnectionItem.objects.select_related(
        'connection__customer', 'product'
    ).exclude(connection__status='CANCELLED')
    for item in lines:
        ws.append([
            item.connection.customer.code,
            item.connection.customer.name,
            item.connection.invoice_no,
            item.connection.invoice_date,
            item.product.barcode,
            item.product.name,
            int(item.effective_quantity),
            item.unit_price or 0,
            item.discount_rate,
            item.vat_rate,
            item.total_amount,
            int(item.delivered_quantity),
            int(item.reserved_quantity),
            int(item.available_quantity),
            'Adet',
        ])
    return workbook_bytes(wb)
