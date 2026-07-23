from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from operations.models import (
    AuditLog,
    BalanceAdjustment,
    CompanySettings,
    ConnectionItem,
    ConnectionSale,
    Customer,
    DocumentCounter,
    Order,
    OrderItem,
    Product,
    Shipment,
    ShipmentItem,
    UserProfile,
    Vehicle,
    Warehouse,
)

DEMO_PREFIX = "DEMO-"
DEMO_USERS = {
    "demo_admin": ("Demo", "Yönetici", UserProfile.Role.ADMIN, True),
    "demo_yonetim": ("Selin", "Ertan", UserProfile.Role.MANAGEMENT, False),
    "demo_satis": ("Berkan", "Miralay", UserProfile.Role.SALES, False),
    "demo_depo": ("Ahmet", "Kaya", UserProfile.Role.WAREHOUSE, False),
    "demo_sevkiyat": ("Murat", "Şahin", UserProfile.Role.DISPATCH, False),
}


class Command(BaseCommand):
    help = "AECO uygulaması için sade ve güvenli demo verisi oluşturur."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Önce demo verilerini siler, sonra yeniden oluşturur.")
        parser.add_argument("--clear", action="store_true", help="Yalnızca demo verilerini temizler.")
        parser.add_argument("--password", default="Demo1234!", help="Demo kullanıcılarının ortak şifresi.")

    def handle(self, *args, **options):
        if options["reset"] or options["clear"]:
            self._clear_demo()
            self.stdout.write(self.style.WARNING("Önceki demo kayıtları temizlendi."))
        if options["clear"]:
            return

        password = options["password"]
        if len(password) < 8:
            self.stderr.write(self.style.ERROR("Demo şifresi en az 8 karakter olmalıdır."))
            return

        with transaction.atomic():
            users = self._create_users(password)
            warehouses = self._create_warehouses()
            self._create_transport()
            products = self._create_products()
            customers = self._create_customers(users["demo_satis"])
            connections = self._create_connections(users, products, customers)
            self._create_orders_shipments(users, warehouses, connections)
            self._create_audit_logs(users, customers, connections)
            self._update_company_settings()

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("AECO sade demo verileri başarıyla oluşturuldu."))
        self.stdout.write("İçerik: 3 firma, 10 ürün, 3 bağlantı faturası, 4 sipariş ve 2 sevkiyat.")
        self.stdout.write("Demo girişleri (ortak şifre):")
        for username, (_first, _last, role, _superuser) in DEMO_USERS.items():
            self.stdout.write(f"  {username:<16} {password:<14} {UserProfile.Role(role).label}")
        self.stdout.write("")
        self.stdout.write(self.style.WARNING("Canlı sisteme geçmeden önce demo verilerini temizleyin."))

    def _clear_demo(self):
        demo_customer_ids = list(
            Customer.objects.filter(notes__startswith="DEMO:").values_list("id", flat=True)
        )
        demo_connection_ids = list(
            ConnectionSale.objects.filter(
                Q(number__startswith=DEMO_PREFIX)
                | Q(invoice_no__startswith=DEMO_PREFIX)
                | Q(customer_id__in=demo_customer_ids)
            ).distinct().values_list("id", flat=True)
        )
        demo_order_ids = list(
            Order.objects.filter(
                Q(number__startswith=DEMO_PREFIX)
                | Q(customer_id__in=demo_customer_ids)
                | Q(items__connection_item__connection_id__in=demo_connection_ids)
            ).distinct().values_list("id", flat=True)
        )
        demo_shipment_ids = list(
            Shipment.objects.filter(
                Q(number__startswith=DEMO_PREFIX)
                | Q(order_id__in=demo_order_ids)
                | Q(customer_id__in=demo_customer_ids)
            ).distinct().values_list("id", flat=True)
        )

        AuditLog.objects.filter(Q(details__demo=True) | Q(object_repr__startswith=DEMO_PREFIX)).delete()
        ShipmentItem.objects.filter(shipment_id__in=demo_shipment_ids).delete()
        Shipment.objects.filter(id__in=demo_shipment_ids).delete()
        OrderItem.objects.filter(order_id__in=demo_order_ids).delete()
        Order.objects.filter(id__in=demo_order_ids).delete()
        BalanceAdjustment.objects.filter(connection_item__connection_id__in=demo_connection_ids).delete()
        ConnectionSale.objects.filter(id__in=demo_connection_ids).delete()

        safe_targets = [
            (Customer.objects.filter(id__in=demo_customer_ids), "müşteri"),
            (Product.objects.filter(barcode__startswith="990000"), "ürün"),
            (Warehouse.objects.filter(code__startswith=DEMO_PREFIX), "depo"),
            (Vehicle.objects.filter(plate__startswith="DEMO-"), "araç"),
        ]
        for queryset, label in safe_targets:
            try:
                queryset.delete()
            except ProtectedError:
                self.stdout.write(self.style.WARNING(
                    f"Bazı demo {label} kayıtları başka kayıtlarda kullanıldığı için korundu."
                ))

        User.objects.filter(username__in=DEMO_USERS.keys()).delete()

        if not Customer.objects.exists():
            DocumentCounter.objects.filter(key='customer').update(value=0, year=0)

        media_root = Path(settings.MEDIA_ROOT)
        for relative in ["invoices/demo", "signatures/demo", "delivery_proofs/demo"]:
            folder = media_root / relative
            if folder.exists():
                for path in sorted(folder.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink(missing_ok=True)
                    elif path.is_dir():
                        try:
                            path.rmdir()
                        except OSError:
                            pass
                try:
                    folder.rmdir()
                except OSError:
                    pass

    def _create_users(self, password):
        users = {}
        phones = {
            "demo_admin": "0533 000 00 01",
            "demo_yonetim": "0533 000 00 02",
            "demo_satis": "0533 000 00 03",
            "demo_depo": "0533 000 00 04",
            "demo_sevkiyat": "0533 000 00 05",
        }
        for username, (first, last, role, is_superuser) in DEMO_USERS.items():
            user, _created = User.objects.get_or_create(username=username)
            user.email = f"{username}@aeco.demo"
            user.first_name = first
            user.last_name = last
            user.is_active = True
            user.is_staff = is_superuser
            user.is_superuser = is_superuser
            user.set_password(password)
            user.save()
            user.profile.role = role
            user.profile.phone = phones[username]
            user.profile.active = True
            user.profile.save()
            users[username] = user
        return users

    def _create_warehouses(self):
        rows = {
            "ana": ("DEMO-ANA", "AECO Ana Depo", "Lefkoşa Organize Sanayi Bölgesi"),
            "girne": ("DEMO-GRN", "Girne Dağıtım Deposu", "Karakum, Girne"),
        }
        warehouses = {}
        for key, (code, name, address) in rows.items():
            warehouse, _created = Warehouse.objects.update_or_create(
                code=code,
                defaults={"name": name, "address": address, "is_active": True},
            )
            warehouses[key] = warehouse
        return warehouses

    def _create_transport(self):
        for plate, description in [
            ("DEMO-KY-456", "Kapalı kasa dağıtım aracı"),
            ("DEMO-KY-789", "Hafif ticari dağıtım aracı"),
        ]:
            Vehicle.objects.update_or_create(
                plate=plate,
                defaults={
                    "description": description,
                    "is_active": True,
                },
            )

    def _create_products(self):
        rows = [
            ("001", "Jack Daniel's Old No.7 100 cl", "Jack Daniel's", "100 cl"),
            ("002", "Ballantine's Finest 100 cl", "Ballantine's", "100 cl"),
            ("003", "Chivas Regal 12 YO 100 cl", "Chivas Regal", "100 cl"),
            ("004", "Absolut Vodka 100 cl", "Absolut", "100 cl"),
            ("005", "Beefeater London Dry Gin 100 cl", "Beefeater", "100 cl"),
            ("006", "Bacardi Carta Blanca 100 cl", "Bacardi", "100 cl"),
            ("007", "Jägermeister 70 cl", "Jägermeister", "70 cl"),
            ("008", "Aperol 100 cl", "Aperol", "100 cl"),
            ("009", "Moët & Chandon Brut 75 cl", "Moët & Chandon", "75 cl"),
            ("010", "Sauvignon Blanc 75 cl", "Demo Estate", "75 cl"),
        ]
        products = {}
        for idx, (short, name, brand, volume) in enumerate(rows, 1):
            barcode = f"990000{idx:07d}"
            product, _created = Product.objects.update_or_create(
                barcode=barcode,
                defaults={
                    "name": name,
                    "brand": brand,
                    "category": "",
                    "volume": volume,
                    "units_per_case": 1,
                    "base_unit": Product.Unit.PIECE,
                    "is_active": True,
                },
            )
            products[short] = product
        return products

    def _create_customers(self, salesperson):
        rows = [
            ("M001", "PITBULL MARKET VE OFF LICENCE LTD", "Mehmet Ali", "0533 111 10 01", "demo01@customer.test"),
            ("M002", "BAFRA BEACH HOTEL LTD", "Ece Demir", "0533 111 10 02", "demo02@customer.test"),
            ("M003", "GİRNE CITY MARKET LTD", "Hasan Yılmaz", "0533 111 10 03", "demo03@customer.test"),
        ]
        customers = {}
        for short, name, contact, phone, email in rows:
            marker = f"DEMO:{short}"
            customer = Customer.objects.filter(notes__startswith=marker).first()
            if customer is None:
                customer = Customer(name=name)
            customer.name = name
            customer.contact_name = contact
            customer.phone = phone
            customer.email = email
            customer.assigned_salesperson = salesperson
            customer.notes = f"{marker} — Sade demo müşteri kaydı."
            customer.is_active = True
            customer.save()
            customers[short] = customer
        return customers

    def _write_invoice_pdf(self, connection):
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
            from reportlab.pdfgen import canvas
        except Exception:
            return ""
        folder = Path(settings.MEDIA_ROOT) / "invoices" / "demo"
        folder.mkdir(parents=True, exist_ok=True)
        filename = f"{connection.invoice_no.replace('/', '-')}.pdf"
        path = folder / filename
        font_name = "Helvetica"
        bold_font_name = "Helvetica-Bold"
        for font_path in [
            Path("C:/Windows/Fonts/arial.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        ]:
            if font_path.exists():
                pdfmetrics.registerFont(TTFont("DemoUtf8", str(font_path)))
                font_name = bold_font_name = "DemoUtf8"
                break
        c = canvas.Canvas(str(path), pagesize=A4)
        c.setFont(bold_font_name, 18)
        c.drawString(50, 790, "AECO TRADING LTD. — DEMO FATURA EKİ")
        c.setFont(font_name, 11)
        c.drawString(50, 750, f"Müşteri: {connection.customer.name}")
        c.drawString(50, 730, f"Fatura No: {connection.invoice_no}")
        c.drawString(50, 710, f"Fatura Tarihi: {connection.invoice_date:%d.%m.%Y}")
        c.drawString(50, 675, "Bu dosya yalnızca uygulama testleri için oluşturulmuştur.")
        c.save()
        return f"invoices/demo/{filename}"

    def _create_connection(self, *, key, customer, invoice_no, days_ago, status, user, items, products):
        approved = status in {ConnectionSale.Status.ACTIVE, ConnectionSale.Status.PARTIAL, ConnectionSale.Status.COMPLETED}
        invoice_date = timezone.localdate() - timedelta(days=days_ago)
        connection = ConnectionSale.objects.create(
            number=f"DEMO-BGL-{key}",
            customer=customer,
            invoice_no=invoice_no,
            invoice_date=invoice_date,
            status=status,
            notes="DEMO: Sade bağlantılı satış kaydı.",
            created_by=user,
            approved_by=user if approved else None,
            approved_at=timezone.now() - timedelta(days=max(days_ago - 1, 0)) if approved else None,
        )
        attachment = self._write_invoice_pdf(connection)
        if attachment:
            ConnectionSale.objects.filter(pk=connection.pk).update(invoice_attachment=attachment)
            connection.invoice_attachment.name = attachment
        item_map = {}
        product_occurrences = {}
        for product_key, qty, price, discount_rate, vat_rate in items:
            item = ConnectionItem.objects.create(
                connection=connection,
                product=products[product_key],
                quantity=int(qty),
                unit=Product.Unit.PIECE,
                unit_price=price,
                discount_rate=discount_rate,
                vat_rate=vat_rate,
            )
            occurrence = product_occurrences.get(product_key, 0) + 1
            product_occurrences[product_key] = occurrence
            item_map[f'{product_key}_{occurrence}'] = item
            item_map.setdefault(product_key, item)
        return {"connection": connection, "items": item_map}

    def _create_connections(self, users, products, customers):
        manager = users["demo_yonetim"]
        return {
            "PIT": self._create_connection(
                key="0001",
                customer=customers["M001"],
                invoice_no="DEMO-FTR-1001",
                days_ago=40,
                status=ConnectionSale.Status.PARTIAL,
                user=manager,
                products=products,
                items=[("001", 100, 9200, 0, 20), ("001", 20, 9200, 100, 20), ("002", 90, 7100, 5, 20), ("004", 60, 4950, 0, 20), ("007", 30, 4100, 0, 20)],
            ),
            "BAF": self._create_connection(
                key="0002",
                customer=customers["M002"],
                invoice_no="DEMO-FTR-1002",
                days_ago=25,
                status=ConnectionSale.Status.ACTIVE,
                user=manager,
                products=products,
                items=[("008", 40, 3900, 0, 20), ("009", 30, 18500, 10, 20), ("010", 80, 4900, 0, 20)],
            ),
            "GRN": self._create_connection(
                key="0003",
                customer=customers["M003"],
                invoice_no="DEMO-FTR-1003",
                days_ago=15,
                status=ConnectionSale.Status.ACTIVE,
                user=manager,
                products=products,
                items=[("003", 50, 8700, 0, 20), ("005", 45, 4200, 0, 20), ("006", 35, 4500, 15, 20)],
            ),
        }

    def _create_order(self, *, number, customer, user, status, days_ago, items, delivery_address, requested_in=2, notes="", approved=True):
        order_date = timezone.localdate() - timedelta(days=days_ago)
        order = Order.objects.create(
            number=f"DEMO-SIP-{number}",
            customer=customer,
            order_date=order_date,
            requested_delivery_date=order_date + timedelta(days=requested_in),
            delivery_address=delivery_address,
            status=status,
            notes=notes or "DEMO: Sade sipariş kaydı.",
            created_by=user,
            approved_by=user if approved else None,
            approved_at=timezone.now() - timedelta(days=max(days_ago - 1, 0)) if approved else None,
        )
        order_items = {}
        for connection_item, qty in items:
            line = OrderItem.objects.create(
                order=order,
                connection_item=connection_item,
                quantity_requested=int(qty),
                notes="Demo sipariş kalemi",
            )
            order_items[connection_item.pk] = line
        return order, order_items

    def _create_proof_image(self, shipment_number, kind, text):
        try:
            from PIL import Image, ImageDraw, ImageFont
        except Exception:
            return ""
        relative_folder = "signatures/demo" if kind == "signature" else "delivery_proofs/demo"
        folder = Path(settings.MEDIA_ROOT) / relative_folder
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{shipment_number.lower()}-{kind}.png"
        size = (900, 360) if kind == "signature" else (900, 650)
        image = Image.new("RGB", size, "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((12, 12, size[0] - 12, size[1] - 12), outline="#E71922", width=6)
        try:
            font_path = next(p for p in [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "C:/Windows/Fonts/segoeuib.ttf",
                "C:/Windows/Fonts/arialbd.ttf",
            ] if Path(p).exists())
            font = ImageFont.truetype(font_path, 34)
        except Exception:
            font = ImageFont.load_default()
        draw.text((45, 45), "AECO DEMO TESLİM KANITI", fill="#17191C", font=font)
        draw.text((45, 130), text, fill="#17191C", font=font)
        draw.text((45, size[1] - 75), shipment_number, fill="#E71922", font=font)
        if kind == "signature":
            draw.arc((400, 145, 760, 315), start=185, end=350, fill="#17191C", width=5)
            draw.line((430, 260, 760, 180), fill="#17191C", width=4)
        image.save(path, "PNG", optimize=True)
        return f"{relative_folder}/{path.name}"

    def _create_shipment(self, *, number, order, warehouse, user, status, days_ago, quantities, delivery_address, vehicle="DEMO-KY-456", dispatcher=None, delivered_to="", notes=""):
        shipment_date = timezone.localdate() - timedelta(days=days_ago)
        is_delivered = status == Shipment.Status.DELIVERED
        shipment = Shipment.objects.create(
            number=f"DEMO-SVK-{number}",
            order=order,
            customer=order.customer,
            warehouse=warehouse,
            shipment_date=shipment_date,
            delivery_date=shipment_date if is_delivered else None,
            delivery_address=delivery_address,
            status=status,
            vehicle_plate=vehicle,
            prepared_by_name="Ahmet Kaya",
            delivered_to=delivered_to if is_delivered else "",
            delivery_notes="",
            notes=notes or "DEMO: Sade sevkiyat kaydı.",
            created_by=user,
            assigned_dispatcher=dispatcher or (user if user.profile.role == UserProfile.Role.DISPATCH else None),
            delivered_by=user if is_delivered else None,
            delivered_at=timezone.now() - timedelta(days=days_ago) if is_delivered else None,
        )
        for order_item, qty in quantities:
            ShipmentItem.objects.create(
                shipment=shipment,
                order_item=order_item,
                connection_item=order_item.connection_item,
                quantity_delivered=int(qty),
                notes="Demo sevk kalemi",
            )
        if is_delivered:
            signature = self._create_proof_image(shipment.number, "signature", delivered_to or "Teslim Alan")
            proof = self._create_proof_image(shipment.number, "proof", "Ürünler müşteriye teslim edilmiştir.")
            Shipment.objects.filter(pk=shipment.pk).update(receiver_signature=signature, delivery_proof=proof)
            shipment.receiver_signature.name = signature
            shipment.delivery_proof.name = proof
        return shipment

    def _create_orders_shipments(self, users, warehouses, connections):
        sales = users["demo_satis"]
        dispatch = users["demo_sevkiyat"]
        warehouse_user = users["demo_depo"]

        # 1) Pitbull: tamamlanmış eski sipariş + teslim edilmiş sevkiyat.
        pit = connections["PIT"]
        order, lines = self._create_order(
            number="0001",
            customer=pit["connection"].customer,
            user=sales,
            status=Order.Status.COMPLETED,
            days_ago=28,
            delivery_address="Karaoğlanoğlu Şube, Girne",
            items=[
                (pit["items"]["001"], 20),
                (pit["items"]["002"], 15),
                (pit["items"]["004"], 10),
            ],
        )
        self._create_shipment(
            number="0001",
            order=order,
            warehouse=warehouses["ana"],
            user=dispatch,
            status=Shipment.Status.DELIVERED,
            days_ago=26,
            delivery_address=order.delivery_address,
            delivered_to="Mehmet Ali",
            quantities=[
                (lines[pit["items"]["001"].pk], 20),
                (lines[pit["items"]["002"].pk], 15),
                (lines[pit["items"]["004"].pk], 10),
            ],
        )

        # 2) Pitbull: onaylanmış ve henüz sevk edilmemiş güncel sipariş.
        self._create_order(
            number="0002",
            customer=pit["connection"].customer,
            user=sales,
            status=Order.Status.APPROVED,
            days_ago=1,
            delivery_address="Karaoğlanoğlu Şube, Girne",
            items=[(pit["items"]["001"], 12), (pit["items"]["007"], 6)],
            notes="Yeni sevkiyat oluşturma testi için hazır sipariş.",
        )

        # 3) Bafra: onaylanmış, sevkiyat bekleyen sipariş.
        baf = connections["BAF"]
        self._create_order(
            number="0003",
            customer=baf["connection"].customer,
            user=sales,
            status=Order.Status.APPROVED,
            days_ago=2,
            delivery_address="Ana Mal Kabul, Bafra",
            items=[(baf["items"]["008"], 8), (baf["items"]["009"], 5), (baf["items"]["010"], 12)],
            notes="Otel için onaylanmış sipariş.",
        )

        # 4) Girne City: hazırlıkta olan sipariş ve tek açık sevkiyat.
        grn = connections["GRN"]
        order, lines = self._create_order(
            number="0004",
            customer=grn["connection"].customer,
            user=sales,
            status=Order.Status.PREPARING,
            days_ago=1,
            delivery_address="Girne Merkez Mağaza",
            items=[(grn["items"]["003"], 10), (grn["items"]["005"], 8), (grn["items"]["006"], 6)],
            notes="Depo ve sevkiyat durum akışı testi.",
        )
        self._create_shipment(
            number="0002",
            order=order,
            warehouse=warehouses["girne"],
            user=warehouse_user,
            status=Shipment.Status.PREPARING,
            days_ago=0,
            delivery_address=order.delivery_address,
            vehicle="DEMO-KY-789",
            dispatcher=dispatch,
            quantities=[
                (lines[grn["items"]["003"].pk], 10),
                (lines[grn["items"]["005"].pk], 8),
                (lines[grn["items"]["006"].pk], 6),
            ],
            notes="Sevkiyat hazırlık aşamasında.",
        )

    def _create_audit_logs(self, users, customers, connections):
        records = [
            (users["demo_admin"], "LOGIN", customers["M001"], {"demo": True, "message": "Demo yönetici girişi"}),
            (users["demo_satis"], "CREATE", customers["M002"], {"demo": True, "message": "Sipariş oluşturuldu"}),
            (users["demo_yonetim"], "APPROVE", connections["PIT"]["connection"], {"demo": True, "message": "Bağlantı onaylandı"}),
            (users["demo_depo"], "STATUS", connections["GRN"]["connection"], {"demo": True, "status": "PREPARING"}),
            (users["demo_sevkiyat"], "DELIVER", connections["PIT"]["connection"], {"demo": True, "message": "Teslimat kesinleştirildi"}),
        ]
        for user, action, obj, details in records:
            AuditLog.objects.create(
                user=user,
                action=action,
                model_name=obj.__class__.__name__,
                object_id=str(obj.pk),
                object_repr=str(obj)[:250],
                details=details,
                ip_address="192.168.1.50",
            )

    def _update_company_settings(self):
        company = CompanySettings.get_solo()
        defaults = {
            "company_name": "AECO TRADING LTD.",
            "registration_no": "DEMO-HE-0000",
            "tax_no": "DEMO-VKN-0000",
            "phone": "+90 392 000 00 00",
            "email": "info@aecotrading.demo",
            "address": "Lefkoşa, Kuzey Kıbrıs Türk Cumhuriyeti",
            "footer_note": "Bu belge AECO demo ortamında elektronik olarak oluşturulmuştur.",
            "document_prefix": "AECO",
            "default_currency": "TRY",
        }
        updates = {}
        for field, value in defaults.items():
            current = getattr(company, field)
            if not current or (field == "company_name" and current == "AECO TRADING LTD."):
                updates[field] = value
        if updates:
            CompanySettings.objects.filter(pk=company.pk).update(**updates)
