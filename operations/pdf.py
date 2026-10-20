from io import BytesIO
from pathlib import Path
import os
import qrcode
from django.conf import settings
from django.urls import reverse
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak, KeepTogether
from .models import CompanySettings
from .services import shipment_balance_rows

RED=colors.HexColor('#E71922'); DARK=colors.HexColor('#17191C'); MUTED=colors.HexColor('#667085'); LIGHT=colors.HexColor('#F4F5F7'); BORDER=colors.HexColor('#D9DDE3')
PORTRAIT_MARGIN = 15 * mm
PORTRAIT_CONTENT_WIDTH = A4[0] - (2 * PORTRAIT_MARGIN)

def register_font():
    candidates=[
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        'C:/Windows/Fonts/arial.ttf',
        'C:/Windows/Fonts/segoeui.ttf',
    ]
    bold_candidates=[
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        'C:/Windows/Fonts/arialbd.ttf',
        'C:/Windows/Fonts/segoeuib.ttf',
    ]
    normal=next((p for p in candidates if Path(p).exists()),None)
    bold=next((p for p in bold_candidates if Path(p).exists()),None)
    if normal:
        pdfmetrics.registerFont(TTFont('AECOFont',normal))
        pdfmetrics.registerFont(TTFont('AECOFontBold',bold or normal))
        return 'AECOFont','AECOFontBold'
    return 'Helvetica','Helvetica-Bold'

FONT,FONT_BOLD=register_font()
styles=getSampleStyleSheet()
styles.add(ParagraphStyle(name='AecoTitle',fontName=FONT_BOLD,fontSize=15,leading=18,textColor=DARK,spaceAfter=5))
styles.add(ParagraphStyle(name='AecoSub',fontName=FONT,fontSize=8.5,leading=11,textColor=MUTED))
styles.add(ParagraphStyle(name='AecoBody',fontName=FONT,fontSize=8.5,leading=11,textColor=DARK))
styles.add(ParagraphStyle(name='AecoSmall',fontName=FONT,fontSize=7,leading=9,textColor=MUTED))
styles.add(ParagraphStyle(name='AecoRight',fontName=FONT,fontSize=8.5,leading=11,alignment=TA_RIGHT))


def fmt(value):
    try:
        return f'{int(value):,}'.replace(',', '.')
    except Exception:
        return str(value or '')

def safe(text):
    return str(text or '').replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')


def money(value):
    try:
        number = float(value or 0)
        return f'{number:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
    except Exception:
        return str(value or '0,00')

def rate_text(value):
    try:
        number = float(value or 0)
        return f'{number:g}'.replace('.', ',')
    except Exception:
        return str(value or 0)

def commercial_line_name(item):
    if item.is_free_item:
        return f'{item.product.name} (Bedelsiz)'
    if item.discount_rate:
        return f'{item.product.name} (%{rate_text(item.discount_rate)} iskonto)'
    return item.product.name

def logo_flowable(company, width=48*mm):
    candidates=[]
    if company.logo:
        try: candidates.append(company.logo.path)
        except Exception: pass
    candidates.append(str(settings.BASE_DIR/'static/img/aeco-logo.png'))
    path=next((p for p in candidates if p and Path(p).exists()),None)
    return Image(path,width=width,height=width*0.39) if path else Paragraph('<b>AECO TRADING LTD.</b>',styles['AecoTitle'])

def header_table(title, doc_no='', date_text=''):
    company=CompanySettings.get_solo()
    left=logo_flowable(company)
    right=Table([
        [Paragraph(safe(title),styles['AecoTitle'])],
        [Paragraph(f'<b>Belge No:</b> {safe(doc_no)}',styles['AecoBody'])],
        [Paragraph(f'<b>Tarih:</b> {safe(date_text)}',styles['AecoBody'])],
    ],colWidths=[72*mm])
    right.setStyle(TableStyle([('ALIGN',(0,0),(-1,-1),'RIGHT'),('VALIGN',(0,0),(-1,-1),'TOP')]))
    t=Table([[left,right]],colWidths=[90*mm,90*mm],hAlign='LEFT')
    t.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,-1),1.2,RED),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
    return t

def info_box(rows, widths=(30*mm,60*mm,30*mm,60*mm)):
    data=[]
    for row in rows:
        data.append([Paragraph(f'<b>{safe(row[0])}</b>',styles['AecoSmall']),Paragraph(safe(row[1]),styles['AecoBody']),Paragraph(f'<b>{safe(row[2])}</b>',styles['AecoSmall']),Paragraph(safe(row[3]),styles['AecoBody'])])
    t=Table(data,colWidths=list(widths),hAlign='LEFT')
    t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(0,-1),LIGHT),('BACKGROUND',(2,0),(2,-1),LIGHT),('BOX',(0,0),(-1,-1),0.5,BORDER),('INNERGRID',(0,0),(-1,-1),0.35,BORDER),
        ('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),
    ])); return t

def data_table(headers, rows, widths, repeatRows=1):
    data=[[Paragraph(f'<b>{safe(h)}</b>',styles['AecoSmall']) for h in headers]]
    for row in rows: data.append([Paragraph(safe(v),styles['AecoSmall']) for v in row])
    t=Table(data,colWidths=widths,repeatRows=repeatRows,hAlign='LEFT')
    t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),DARK),('TEXTCOLOR',(0,0),(-1,0),colors.white),('BOX',(0,0),(-1,-1),0.5,BORDER),('INNERGRID',(0,0),(-1,-1),0.3,BORDER),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LEFTPADDING',(0,0),(-1,-1),4),('RIGHTPADDING',(0,0),(-1,-1),4),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),
    ]))
    for i in range(1,len(data)):
        if i%2==0: t.setStyle(TableStyle([('BACKGROUND',(0,i),(-1,i),colors.HexColor('#FAFAFB'))]))
    return t

def footer(canvas,doc):
    company=CompanySettings.get_solo(); canvas.saveState(); canvas.setFont(FONT,7); canvas.setFillColor(MUTED)
    page_width=doc.pagesize[0]
    canvas.drawString(doc.leftMargin,11*mm,str(company.footer_note or ''))
    canvas.drawRightString(page_width-doc.rightMargin,11*mm,f'Sayfa {doc.page}')
    canvas.setStrokeColor(BORDER); canvas.line(doc.leftMargin,15*mm,page_width-doc.rightMargin,15*mm); canvas.restoreState()

def build_pdf(story, landscape_mode=False):
    buf=BytesIO(); pagesize=landscape(A4) if landscape_mode else A4
    margin = 12*mm if landscape_mode else PORTRAIT_MARGIN
    doc=SimpleDocTemplate(buf,pagesize=pagesize,rightMargin=margin,leftMargin=margin,topMargin=12*mm,bottomMargin=20*mm,title='AECO TRADING LTD.')
    doc.build(story,onFirstPage=footer,onLaterPages=footer); buf.seek(0); return buf.getvalue()

def customer_balance_pdf(customer):
    from .models import ConnectionItem
    lines=ConnectionItem.objects.select_related('connection','product').filter(connection__customer=customer).exclude(connection__status='CANCELLED').order_by('product__name','connection__invoice_date')
    story=[header_table('BAĞLANTILI MALLAR LİSTESİ',customer.code, __import__('django').utils.timezone.localdate().strftime('%d.%m.%Y')),Spacer(1,7*mm)]
    story.append(info_box([('Müşteri',customer.name,'Müşteri Kodu',customer.code),('Yetkili',customer.contact_name or '-','Telefon',customer.phone or '-'),('E-posta',customer.email or '-','Rapor Türü','Güncel bağlantı bakiyesi')]))
    story.append(Spacer(1,6*mm))
    rows=[]
    for i in lines:
        rows.append([i.product.barcode,commercial_line_name(i),i.connection.invoice_no,i.connection.invoice_date.strftime('%d.%m.%Y'),fmt(i.effective_quantity),fmt(i.delivered_quantity),fmt(i.reserved_quantity),fmt(i.available_quantity),'Adet'])
    story.append(data_table(['Barkod','Ürün','Satış Faturası','Fatura Tarihi','Toplam','Teslim','Sipariş','Kullanılabilir','Birim'],rows,[31*mm,38*mm,24*mm,20*mm,15*mm,15*mm,15*mm,19*mm,14*mm]))
    story.append(Spacer(1,5*mm)); story.append(Paragraph('Not: Siparişe ayrılmış miktarlar kullanılabilir bakiyeden düşülmüştür. Her ürün satırı ilgili satış faturasına istinaden takip edilir.',styles['AecoSmall']))
    return build_pdf(story,landscape_mode=True)

def connection_pdf(connection):
    story = [
        header_table(
            'BAĞLANTILI SATIŞ FATURA ÖZETİ',
            connection.number,
            connection.invoice_date.strftime('%d.%m.%Y'),
        ),
        Spacer(1, 7 * mm),
    ]
    creator = connection.created_by.get_full_name() or connection.created_by.username
    story.append(info_box([
        ('Müşteri', connection.customer.name, 'Müşteri Kodu', connection.customer.code),
        ('Satış Faturası', connection.invoice_no, 'Durum', connection.get_status_display()),
        ('Fatura Tarihi', connection.invoice_date.strftime('%d.%m.%Y'), 'Oluşturan', creator),
    ]))
    story.append(Spacer(1, 6 * mm))

    rows = []
    for item in connection.items.select_related('product').all():
        rows.append([
            item.product.barcode,
            commercial_line_name(item),
            fmt(item.quantity),
            money(item.unit_price),
            f'%{rate_text(item.discount_rate)}',
            f'%{rate_text(item.vat_rate)}',
            money(item.total_amount),
        ])
    story.append(data_table(
        ['Barkod', 'Ürün', 'Miktar', 'Birim Fiyat', 'İskonto', 'KDV', 'KDV Dahil Toplam'],
        rows,
        [28*mm, 52*mm, 16*mm, 22*mm, 16*mm, 16*mm, 30*mm],
    ))
    story.append(Spacer(1, 6 * mm))

    totals = Table([
        [Paragraph('<b>Brüt Tutar</b>', styles['AecoBody']), Paragraph(money(connection.gross_amount), styles['AecoRight'])],
        [Paragraph('<b>İskonto Toplamı</b>', styles['AecoBody']), Paragraph(money(connection.discount_amount), styles['AecoRight'])],
        [Paragraph('<b>Net Tutar</b>', styles['AecoBody']), Paragraph(money(connection.net_amount), styles['AecoRight'])],
        [Paragraph('<b>KDV Toplamı</b>', styles['AecoBody']), Paragraph(money(connection.vat_amount), styles['AecoRight'])],
        [Paragraph('<b>FATURA GENEL TOPLAMI — KDV DAHİL</b>', styles['AecoTitle']), Paragraph(f'<b>{money(connection.total_amount)}</b>', styles['AecoTitle'])],
    ], colWidths=[105*mm, 55*mm], hAlign='RIGHT')
    totals.setStyle(TableStyle([
        ('BOX', (0,0), (-1,-1), 0.7, BORDER),
        ('INNERGRID', (0,0), (-1,-2), 0.3, BORDER),
        ('BACKGROUND', (0,-1), (-1,-1), LIGHT),
        ('TEXTCOLOR', (0,-1), (-1,-1), RED),
        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 7),
        ('RIGHTPADDING', (0,0), (-1,-1), 7),
    ]))
    story.append(totals)
    if connection.notes:
        story.extend([Spacer(1, 5 * mm), Paragraph(f'<b>Açıklama:</b> {safe(connection.notes)}', styles['AecoBody'])])
    return build_pdf(story)


def order_pdf(order):
    story=[header_table('BAĞLANTILI MAL SİPARİŞ FORMU',order.number,order.order_date.strftime('%d.%m.%Y')),Spacer(1,7*mm)]
    story.append(info_box([('Müşteri',order.customer.name,'Müşteri Kodu',order.customer.code),('Talep Edilen Teslim',order.requested_delivery_date.strftime('%d.%m.%Y') if order.requested_delivery_date else '-','Durum',order.get_status_display()),('Teslimat Adresi',order.delivery_address,'Oluşturan',order.created_by.get_full_name() or order.created_by.username)]))
    story.append(Spacer(1,6*mm)); rows=[]
    for i in order.items.select_related('connection_item__product','connection_item__connection'):
        ci=i.connection_item
        rows.append([ci.product.barcode,commercial_line_name(ci),ci.connection.invoice_no,ci.connection.invoice_date.strftime('%d.%m.%Y'),fmt(i.quantity_requested),fmt(i.delivered_quantity),fmt(i.remaining_quantity),'Adet'])
    story.append(data_table(['Barkod','Ürün','İstinaden Fatura','Fatura Tarihi','Talep','Teslim','Kalan','Birim'],rows,[28*mm,45*mm,27*mm,21*mm,16*mm,16*mm,16*mm,11*mm]))
    if order.notes: story.extend([Spacer(1,5*mm),Paragraph(f'<b>Açıklama:</b> {safe(order.notes)}',styles['AecoBody'])])
    return build_pdf(story)

def qr_image(url):
    qr=qrcode.QRCode(version=2,box_size=5,border=1); qr.add_data(url); qr.make(fit=True); img=qr.make_image(fill_color='black',back_color='white'); buf=BytesIO(); img.save(buf,format='PNG'); buf.seek(0); return Image(buf,width=28*mm,height=28*mm)

def proof_photo_flowable(file_field, max_width=74*mm, max_height=42*mm):
    """Teslimat fotoğrafını EXIF yönünü düzelterek PDF'e uygun küçük görsele dönüştürür."""
    if not file_field:
        return Paragraph('Görsel yüklenmemiş.', styles['AecoSmall'])
    try:
        from PIL import Image as PILImage, ImageOps
        file_field.open('rb')
        pil = PILImage.open(file_field.file)
        pil = ImageOps.exif_transpose(pil)
        if pil.mode in {'RGBA', 'LA'}:
            background = PILImage.new('RGB', pil.size, 'white')
            alpha = pil.getchannel('A') if pil.mode == 'RGBA' else pil.getchannel('A')
            background.paste(pil.convert('RGBA'), mask=alpha)
            pil = background
        elif pil.mode != 'RGB':
            pil = pil.convert('RGB')
        pil.thumbnail((1400, 1000))
        width_px, height_px = pil.size
        if not width_px or not height_px:
            raise ValueError('Geçersiz görsel boyutu')
        scale = min(max_width / width_px, max_height / height_px)
        width = width_px * scale
        height = height_px * scale
        buffer = BytesIO()
        pil.save(buffer, format='JPEG', quality=82, optimize=True)
        buffer.seek(0)
        return Image(buffer, width=width, height=height)
    except Exception:
        return Paragraph('Görsel PDF içine eklenemedi.', styles['AecoSmall'])
    finally:
        try:
            file_field.close()
        except Exception:
            pass


def delivery_evidence_table(shipment):
    if not shipment.receiver_signature and not shipment.delivery_proof:
        return None
    signature = proof_photo_flowable(shipment.receiver_signature)
    proof = proof_photo_flowable(shipment.delivery_proof)
    table = Table([
        [Paragraph('<b>İmzalı Evrak / İmza Kanıtı</b>', styles['AecoSmall']), Paragraph('<b>Teslimat Kanıt Fotoğrafı</b>', styles['AecoSmall'])],
        [signature, proof],
    ], colWidths=[90*mm, 90*mm], hAlign='LEFT')
    table.setStyle(TableStyle([
        ('BOX', (0,0), (-1,-1), 0.5, BORDER),
        ('INNERGRID', (0,0), (-1,-1), 0.3, BORDER),
        ('BACKGROUND', (0,0), (-1,0), LIGHT),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING', (0,0), (-1,-1), 5),
        ('RIGHTPADDING', (0,0), (-1,-1), 5),
    ]))
    return table


def shipment_pdf(shipment, absolute_verify_url):
    # Teslim eden, teslimi sistemde kesinleştiren kullanıcıdır; teslimden önce elle doldurulur.
    deliverer_name = (
        shipment.delivered_by.get_full_name() or shipment.delivered_by.username
        if shipment.delivered_by
        else ''
    )

    story = [
        header_table(
            'SEVK VE TESLİM TUTANAĞI',
            shipment.number,
            shipment.shipment_date.strftime('%d.%m.%Y'),
        ),
        Spacer(1, 6 * mm),
    ]

    story.append(info_box([
        (
            'Müşteri',
            shipment.customer.name,
            'Müşteri Kodu',
            shipment.customer.code,
        ),
        (
            'Sipariş No',
            shipment.order.number,
            'Durum',
            shipment.get_status_display(),
        ),
        (
            'Teslimat Adresi',
            shipment.delivery_address or '-',
            'Teslim Tarihi',
            (
                shipment.delivery_date.strftime('%d.%m.%Y')
                if shipment.delivery_date
                else '-'
            ),
        ),
    ]))

    story.append(Spacer(1, 5 * mm))
    rows = []

    for item in shipment.items.select_related(
        'connection_item__product',
        'connection_item__connection',
    ):
        connection_item = item.connection_item
        rows.append([
            connection_item.product.barcode,
            commercial_line_name(connection_item),
            connection_item.connection.invoice_no,
            connection_item.connection.invoice_date.strftime('%d.%m.%Y'),
            fmt(item.quantity_delivered),
            'Adet',
        ])

    story.append(data_table(
        [
            'Barkod',
            'Ürün',
            'İstinaden Fatura',
            'Fatura Tarihi',
            'Sevk Miktarı',
            'Birim',
        ],
        rows,
        [
            29 * mm,
            55 * mm,
            28 * mm,
            23 * mm,
            27 * mm,
            18 * mm,
        ],
    ))

    balance_rows = [
        [
            commercial_line_name(row['item']),
            row['item'].connection.invoice_no,
            fmt(row['total']),
            fmt(row['before']),
            fmt(row['this']) if row['this'] else '-',
            fmt(row['remaining']),
        ]
        for row in shipment_balance_rows(shipment)
    ]
    if balance_rows:
        story.extend([
            Spacer(1, 5 * mm),
            Paragraph('MÜŞTERİNİN BAĞLANTI BAKİYESİ (BU SEVK SONRASI)', styles['AecoBody']),
            Spacer(1, 2 * mm),
            data_table(
                ['Ürün', 'Fatura', 'Toplam Hak', 'Önceki Teslim', 'Bu Sevk', 'Kalan'],
                balance_rows,
                [64 * mm, 28 * mm, 22 * mm, 24 * mm, 20 * mm, 22 * mm],
            ),
        ])

    statement = Paragraph(
        'Yukarıda belirtilen ürünleri eksiksiz ve hasarsız olarak teslim aldım. '
        'Kalan bağlantı bakiyesini kontrol ettim.',
        styles['AecoBody'],
    )

    sign = Table(
        [
            [
                Paragraph('<b>Hazırlayan</b>', styles['AecoSmall']),
                Paragraph('<b>Teslim Eden</b>', styles['AecoSmall']),
                Paragraph('<b>Teslim Alan (Ad Soyad / İmza / Kaşe)</b>', styles['AecoSmall']),
                qr_image(absolute_verify_url),
            ],
            [
                Paragraph(
                    safe(shipment.prepared_by_name or '-'),
                    styles['AecoBody'],
                ),
                Paragraph(
                    safe(deliverer_name),
                    styles['AecoBody'],
                ),
                Paragraph(
                    safe(shipment.delivered_to or ''),
                    styles['AecoBody'],
                ),
                Paragraph(
                    'Belgeyi doğrulamak için QR kodu okutun.',
                    styles['AecoSmall'],
                ),
            ],
        ],
        colWidths=[
            40 * mm,
            40 * mm,
            44 * mm,
            56 * mm,
        ],
        rowHeights=[
            12 * mm,
            27 * mm,
        ],
    )

    sign.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.5, BORDER),
        ('INNERGRID', (0, 0), (-2, -1), 0.3, BORDER),
        ('SPAN', (-1, 0), (-1, -1)),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (-1, 0), (-1, -1), 'CENTER'),
        ('BACKGROUND', (0, 0), (-2, 0), LIGHT),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
    ]))

    story.extend([Spacer(1, 5 * mm), KeepTogether([statement, Spacer(1, 3 * mm), sign])])

    if shipment.notes:
        story.extend([
            Spacer(1, 4 * mm),
            Paragraph(
                f'<b>Sevk açıklaması:</b> {safe(shipment.notes)}',
                styles['AecoBody'],
            ),
        ])

    if shipment.delivery_notes:
        story.extend([
            Spacer(1, 3 * mm),
            Paragraph(
                (
                    '<b>Teslimat açıklaması:</b> '
                    f'{safe(shipment.delivery_notes)}'
                ),
                styles['AecoBody'],
            ),
        ])

    evidence = delivery_evidence_table(shipment)

    if evidence:
        story.append(KeepTogether([
            Spacer(1, 5 * mm),
            Paragraph('TESLİMAT KANITLARI', styles['AecoTitle']),
            Spacer(1, 2 * mm),
            evidence,
        ]))

    return build_pdf(story)
