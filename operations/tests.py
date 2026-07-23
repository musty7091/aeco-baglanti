from decimal import Decimal
from io import BytesIO
import tempfile

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import (
    ConnectionItemForm,
    ConnectionSaleForm,
    CustomerForm,
    ShipmentDeliveryForm,
    ShipmentForm,
)
from .models import (
    BalanceAdjustment,
    ConnectionItem,
    ConnectionSale,
    Customer,
    DocumentCounter,
    Order,
    Product,
    Shipment,
    ShipmentItem,
    UserProfile,
    Vehicle,
    Warehouse,
)
from .services import create_order_from_request, deliver_shipment, parse_quantity


class CustomerCodeAndFormTests(TestCase):
    def setUp(self):
        DocumentCounter.objects.update_or_create(
            key='customer', defaults={'year': 0, 'value': 0}
        )

    def test_customer_codes_are_automatic_and_sequential(self):
        first = Customer.objects.create(name='Birinci Müşteri')
        second = Customer.objects.create(name='İkinci Müşteri')
        third = Customer.objects.create(name='Üçüncü Müşteri')

        self.assertEqual(first.code, 'MUS-00001')
        self.assertEqual(second.code, 'MUS-00002')
        self.assertEqual(third.code, 'MUS-00003')
        self.assertEqual(DocumentCounter.objects.get(key='customer').value, 3)

    def test_customer_form_has_only_requested_business_fields(self):
        form = CustomerForm()
        self.assertEqual(
            list(form.fields),
            [
                'name', 'contact_name', 'phone', 'email',
                'assigned_salesperson', 'notes', 'is_active',
            ],
        )
        for removed in (
            'code', 'billing_address', 'delivery_addresses',
            'delivery_addresses_text',
        ):
            self.assertNotIn(removed, form.fields)

    def test_customer_model_has_no_removed_address_fields(self):
        field_names = {field.name for field in Customer._meta.get_fields()}
        self.assertNotIn('billing_address', field_names)
        self.assertNotIn('delivery_addresses', field_names)

    def test_customer_code_cannot_be_changed_through_edit_form(self):
        customer = Customer.objects.create(name='Kod Koruma Testi')
        original_code = customer.code
        form = CustomerForm(
            data={
                'name': 'Kod Koruma Testi Güncel',
                'contact_name': '',
                'phone': '',
                'email': '',
                'assigned_salesperson': '',
                'notes': '',
                'is_active': 'on',
                'code': 'HACK-99999',
            },
            instance=customer,
        )
        self.assertTrue(form.is_valid(), form.errors)
        updated = form.save()
        self.assertEqual(updated.code, original_code)


class InvoiceAmountAndAttachmentTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            'invoice_admin', 'invoice@example.com', 'StrongPass123!'
        )
        self.customer = Customer.objects.create(name='Fatura Test Müşterisi')
        self.product_a = Product.objects.create(
            barcode='8690000000001', name='Test Ürün A'
        )
        self.product_b = Product.objects.create(
            barcode='8690000000002', name='Test Ürün B'
        )
        self.connection = ConnectionSale.objects.create(
            number='BGL-TEST-1',
            customer=self.customer,
            invoice_no='FAT-TEST-1',
            invoice_date=timezone.localdate(),
            status=ConnectionSale.Status.PENDING,
            created_by=self.user,
        )

    def create_item(
        self, product, quantity, unit_price, discount_rate=0, vat_rate=20
    ):
        return ConnectionItem.objects.create(
            connection=self.connection,
            product=product,
            quantity=quantity,
            unit_price=Decimal(str(unit_price)),
            discount_rate=Decimal(str(discount_rate)),
            vat_rate=Decimal(str(vat_rate)),
        )

    def test_connection_form_has_no_expiry_date(self):
        self.assertNotIn('expiry_date', ConnectionSaleForm().fields)
        field_names = {field.name for field in ConnectionSale._meta.get_fields()}
        self.assertNotIn('expiry_date', field_names)

    def test_line_total_calculates_discount_and_vat(self):
        line = self.create_item(
            self.product_a, quantity=10, unit_price='100.00',
            discount_rate='10.00', vat_rate='20.00',
        )
        self.assertEqual(line.gross_amount, Decimal('1000.00'))
        self.assertEqual(line.discount_amount, Decimal('100.00'))
        self.assertEqual(line.net_amount, Decimal('900.00'))
        self.assertEqual(line.vat_amount, Decimal('180.00'))
        self.assertEqual(line.total_amount, Decimal('1080.00'))

    def test_connection_totals_sum_multiple_lines(self):
        self.create_item(
            self.product_a, quantity=2, unit_price='100.00',
            discount_rate='10.00', vat_rate='20.00',
        )
        self.create_item(
            self.product_b, quantity=3, unit_price='50.00',
            discount_rate='0.00', vat_rate='10.00',
        )
        self.assertEqual(self.connection.gross_amount, Decimal('350.00'))
        self.assertEqual(self.connection.discount_amount, Decimal('20.00'))
        self.assertEqual(self.connection.net_amount, Decimal('330.00'))
        self.assertEqual(self.connection.vat_amount, Decimal('51.00'))
        self.assertEqual(self.connection.total_amount, Decimal('381.00'))

    def test_fully_discounted_free_line_does_not_increase_total(self):
        paid = self.create_item(
            self.product_a, quantity=1, unit_price='100.00',
            discount_rate='0.00', vat_rate='20.00',
        )
        free = self.create_item(
            self.product_b, quantity=50, unit_price='999.00',
            discount_rate='100.00', vat_rate='20.00',
        )
        self.assertEqual(paid.total_amount, Decimal('120.00'))
        self.assertEqual(free.total_amount, Decimal('0.00'))
        self.assertTrue(free.is_free_item)
        self.assertEqual(self.connection.total_amount, Decimal('120.00'))

    def _form_data(self):
        return {
            'customer': self.customer.pk,
            'invoice_no': 'FAT-DOSYA-1',
            'invoice_date': timezone.localdate().isoformat(),
            'notes': '',
        }

    def test_invoice_attachment_extension_validation(self):
        bad_file = SimpleUploadedFile(
            'fatura.exe', b'not-a-document', content_type='application/octet-stream'
        )
        form = ConnectionSaleForm(
            data=self._form_data(), files={'invoice_attachment': bad_file}
        )
        self.assertFalse(form.is_valid())
        self.assertIn('invoice_attachment', form.errors)

    def test_invoice_attachment_size_validation(self):
        oversized = SimpleUploadedFile(
            'fatura.pdf', b'x' * (10 * 1024 * 1024 + 1),
            content_type='application/pdf',
        )
        form = ConnectionSaleForm(
            data=self._form_data(), files={'invoice_attachment': oversized}
        )
        self.assertFalse(form.is_valid())
        self.assertIn('invoice_attachment', form.errors)

    def test_supported_invoice_attachment_is_valid(self):
        valid_pdf = SimpleUploadedFile(
            'fatura.pdf', b'%PDF-1.4\n%%EOF', content_type='application/pdf'
        )
        form = ConnectionSaleForm(
            data=self._form_data(), files={'invoice_attachment': valid_pdf}
        )
        self.assertTrue(form.is_valid(), form.errors)


class CreateViewTests(TestCase):
    def setUp(self):
        DocumentCounter.objects.update_or_create(
            key='customer', defaults={'year': 0, 'value': 0}
        )
        self.user = User.objects.create_superuser(
            'create_admin', 'create@example.com', 'StrongPass123!'
        )
        self.client.force_login(self.user)

    def test_new_customer_creation_works_and_assigns_code(self):
        response = self.client.post(
            reverse('customer_create'),
            {
                'name': 'Yeni Ticari Müşteri Ltd.',
                'contact_name': 'Ayşe Şahin',
                'phone': '0533 123 45 67',
                'email': 'ayse@example.com',
                'assigned_salesperson': '',
                'notes': 'Yeni müşteri testi',
                'is_active': 'on',
            },
        )
        self.assertEqual(response.status_code, 302)
        customer = Customer.objects.get(name='Yeni Ticari Müşteri Ltd.')
        self.assertEqual(customer.code, 'MUS-00001')

    def test_new_connection_sale_creation_works(self):
        customer = Customer.objects.create(name='Bağlantı Müşterisi')
        product = Product.objects.create(
            barcode='9900000000999', name='Bağlantı Test Ürünü'
        )
        response = self.client.post(
            reverse('connection_create'),
            {
                'customer': customer.pk,
                'invoice_no': 'TEST-FTR-2026-1',
                'invoice_date': timezone.localdate().isoformat(),
                'notes': 'Bağlantı oluşturma testi',
                'items-TOTAL_FORMS': '1',
                'items-INITIAL_FORMS': '0',
                'items-MIN_NUM_FORMS': '1',
                'items-MAX_NUM_FORMS': '1000',
                'items-0-product': str(product.pk),
                'items-0-quantity': '4',
                'items-0-unit_price': '125.00',
                'items-0-discount_rate': '10.00',
                'items-0-vat_rate': '20.00',
            },
        )
        self.assertEqual(response.status_code, 302)
        connection = ConnectionSale.objects.get(invoice_no='TEST-FTR-2026-1')
        self.assertEqual(connection.items.count(), 1)
        self.assertEqual(connection.total_amount, Decimal('540.00'))


class BusinessFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            'admin', 'a@a.com', 'StrongPass123!'
        )
        self.customer = Customer.objects.create(name='Test Market')
        self.product = Product.objects.create(
            barcode='8690000000101', name='Test Ürün'
        )
        self.warehouse = Warehouse.objects.create(code='ANA', name='Ana Depo')
        self.connection = ConnectionSale.objects.create(
            number='BGL-1', customer=self.customer, invoice_no='FAT-100',
            invoice_date=timezone.localdate(),
            status=ConnectionSale.Status.ACTIVE, created_by=self.user,
            approved_by=self.user, approved_at=timezone.now(),
        )
        self.line = ConnectionItem.objects.create(
            connection=self.connection, product=self.product,
            quantity=100, unit=Product.Unit.PIECE,
            unit_price=Decimal('100.00'), vat_rate=Decimal('20.00'),
        )

    def create_approved_order(self, quantity='25'):
        order = create_order_from_request(
            customer=self.customer,
            user=self.user,
            order_data={
                'order_date': timezone.localdate(),
                'requested_delivery_date': None,
                'delivery_address': 'Adres',
                'notes': '',
            },
            quantities={str(self.line.pk): quantity},
        )
        order.status = Order.Status.APPROVED
        order.approved_by = self.user
        order.approved_at = timezone.now()
        order.save()
        return order

    def test_connection_item_form_is_simplified(self):
        line_form = ConnectionItemForm()
        self.assertEqual(
            list(line_form.fields),
            ['product', 'quantity', 'unit_price', 'discount_rate', 'vat_rate', 'total_amount'],
        )

    def test_invoice_based_reservation_and_delivery(self):
        order = self.create_approved_order('25')
        self.assertEqual(self.line.available_quantity, 75)
        shipment = Shipment.objects.create(
            number='SVK-1', order=order, customer=self.customer,
            warehouse=self.warehouse, created_by=self.user,
        )
        order_item = order.items.get()
        ShipmentItem.objects.create(
            shipment=shipment,
            order_item=order_item,
            connection_item=self.line,
            quantity_delivered=25,
        )
        deliver_shipment(shipment=shipment, user=self.user)
        self.line.refresh_from_db()
        self.assertEqual(self.line.delivered_quantity, 25)
        self.assertEqual(self.line.available_quantity, 75)

    def test_open_shipment_allocation_prevents_duplicate_planning(self):
        order = self.create_approved_order('25')
        order_item = order.items.get()
        shipment = Shipment.objects.create(
            number='SVK-2', order=order, customer=self.customer,
            warehouse=self.warehouse, created_by=self.user,
        )
        ShipmentItem.objects.create(
            shipment=shipment,
            order_item=order_item,
            connection_item=self.line,
            quantity_delivered=10,
        )
        self.assertEqual(order_item.allocatable_quantity, 15)

    def test_adjustment_cannot_reduce_below_reserved_amount(self):
        self.create_approved_order('25')
        adjustment = BalanceAdjustment(
            connection_item=self.line,
            signed_quantity=-80,
            kind=BalanceAdjustment.Kind.CORRECTION,
            reason='Test',
            created_by=self.user,
            approved_by=self.user,
        )
        with self.assertRaises(ValidationError):
            adjustment.full_clean()

    def test_quantities_are_whole_numbers(self):
        self.assertEqual(parse_quantity('18'), 18)
        self.assertEqual(parse_quantity('18,000'), 18)
        with self.assertRaises(ValidationError):
            parse_quantity('18,5')

    def test_shipment_form_contains_only_current_transport_fields(self):
        Vehicle.objects.create(plate='KY 123', description='Dağıtım aracı')
        shipment = Shipment(
            order=self.create_approved_order('5'),
            customer=self.customer,
            warehouse=self.warehouse,
            created_by=self.user,
        )
        form = ShipmentForm(instance=shipment)
        self.assertIn(
            ('KY 123', 'KY 123 - Dağıtım aracı'),
            form.fields['vehicle_plate'].choices,
        )
        self.assertIn('assigned_dispatcher', form.fields)
        self.assertIn('prepared_by_name', form.fields)
        self.assertNotIn('driver_name', form.fields)
        self.assertNotIn('checked_by_name', form.fields)

    def test_delivery_form_notes_are_optional(self):
        shipment = Shipment(
            order=self.create_approved_order('5'),
            customer=self.customer,
            warehouse=self.warehouse,
            created_by=self.user,
        )
        form = ShipmentDeliveryForm(instance=shipment)
        self.assertIn('delivery_notes', form.fields)
        self.assertFalse(form.fields['delivery_notes'].required)


class DemoDataCommandTests(TestCase):
    def setUp(self):
        self.temp_media = tempfile.TemporaryDirectory()
        self.media_override = self.settings(MEDIA_ROOT=self.temp_media.name)
        self.media_override.enable()

    def tearDown(self):
        self.media_override.disable()
        self.temp_media.cleanup()

    def test_demo_command_runs_with_new_model(self):
        call_command('demo_aeco', '--reset', verbosity=0)

        customers = Customer.objects.filter(notes__startswith='DEMO:').order_by('code')
        self.assertEqual(customers.count(), 3)
        self.assertEqual(
            list(customers.values_list('code', flat=True)),
            ['MUS-00001', 'MUS-00002', 'MUS-00003'],
        )
        self.assertEqual(Product.objects.filter(barcode__startswith='990000').count(), 10)
        self.assertTrue(Product.objects.filter(name__contains='Jägermeister').exists())
        self.assertTrue(Product.objects.filter(name__contains='Moët & Chandon').exists())
        self.assertEqual(ConnectionSale.objects.filter(number__startswith='DEMO-').count(), 3)
        self.assertEqual(Order.objects.filter(number__startswith='DEMO-').count(), 4)
        self.assertEqual(Shipment.objects.filter(number__startswith='DEMO-').count(), 2)
        self.assertEqual(Vehicle.objects.filter(plate__startswith='DEMO-').count(), 2)
        self.assertEqual(
            User.objects.get(username='demo_sevkiyat').last_name,
            'Şahin',
        )

        pit_connection = ConnectionSale.objects.get(number='DEMO-BGL-0001')
        repeated_barcode = Product.objects.get(barcode='9900000000001')
        repeated_lines = ConnectionItem.objects.filter(
            connection=pit_connection, product=repeated_barcode
        )
        self.assertEqual(repeated_lines.count(), 2)
        self.assertTrue(repeated_lines.filter(discount_rate=100).exists())
        self.assertGreater(pit_connection.total_amount, Decimal('0.00'))

        call_command('demo_aeco', '--clear', verbosity=0)
        self.assertFalse(Customer.objects.filter(notes__startswith='DEMO:').exists())
        self.assertFalse(User.objects.filter(username='demo_admin').exists())


class RolePermissionTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('role_admin', password='Pass12345!')
        self.admin.profile.role = UserProfile.Role.ADMIN
        self.admin.profile.save()

        self.management = User.objects.create_user(
            'role_management', password='Pass12345!'
        )
        self.management.profile.role = UserProfile.Role.MANAGEMENT
        self.management.profile.save()

        self.sales = User.objects.create_user(
            'role_sales', password='Pass12345!', first_name='Satış'
        )
        self.sales.profile.role = UserProfile.Role.SALES
        self.sales.profile.save()

        self.other_sales = User.objects.create_user(
            'role_sales_2', password='Pass12345!'
        )
        self.other_sales.profile.role = UserProfile.Role.SALES
        self.other_sales.profile.save()

        self.warehouse_user = User.objects.create_user(
            'role_warehouse', password='Pass12345!'
        )
        self.warehouse_user.profile.role = UserProfile.Role.WAREHOUSE
        self.warehouse_user.profile.save()

        self.dispatch = User.objects.create_user(
            'role_dispatch', password='Pass12345!', first_name='Sevk'
        )
        self.dispatch.profile.role = UserProfile.Role.DISPATCH
        self.dispatch.profile.save()

        self.other_dispatch = User.objects.create_user(
            'role_dispatch_2', password='Pass12345!'
        )
        self.other_dispatch.profile.role = UserProfile.Role.DISPATCH
        self.other_dispatch.profile.save()

        self.customer = Customer.objects.create(
            name='Satış Müşterisi', assigned_salesperson=self.sales
        )
        self.other_customer = Customer.objects.create(
            name='Diğer Müşteri', assigned_salesperson=self.other_sales
        )
        self.unassigned_customer = Customer.objects.create(name='Atanmamış Müşteri')
        self.product = Product.objects.create(
            barcode='9900990099001', name='Yetki Test Ürünü'
        )
        self.warehouse = Warehouse.objects.create(
            code='ROLE-WH', name='Yetki Test Deposu'
        )

        self.connection = ConnectionSale.objects.create(
            number='ROLE-BGL-1',
            customer=self.customer,
            invoice_no='ROLE-FAT-1',
            invoice_date=timezone.localdate(),
            status=ConnectionSale.Status.ACTIVE,
            created_by=self.management,
            approved_by=self.management,
            approved_at=timezone.now(),
        )
        self.connection_item = ConnectionItem.objects.create(
            connection=self.connection,
            product=self.product,
            quantity=50,
            unit_price=100,
            vat_rate=20,
        )
        self.pending_order = Order.objects.create(
            number='ROLE-SIP-P',
            customer=self.customer,
            status=Order.Status.PENDING,
            created_by=self.sales,
        )
        self.approved_order = Order.objects.create(
            number='ROLE-SIP-A',
            customer=self.customer,
            status=Order.Status.APPROVED,
            created_by=self.sales,
            approved_by=self.management,
            approved_at=timezone.now(),
        )
        self.order_item = self.approved_order.items.create(
            connection_item=self.connection_item,
            quantity_requested=10,
        )
        self.assigned_shipment = Shipment.objects.create(
            number='ROLE-SVK-1',
            order=self.approved_order,
            customer=self.customer,
            warehouse=self.warehouse,
            created_by=self.warehouse_user,
            assigned_dispatcher=self.dispatch,
            status=Shipment.Status.LOADED,
        )
        ShipmentItem.objects.create(
            shipment=self.assigned_shipment,
            order_item=self.order_item,
            connection_item=self.connection_item,
            quantity_delivered=10,
        )
        self.other_shipment = Shipment.objects.create(
            number='ROLE-SVK-2',
            order=self.approved_order,
            customer=self.customer,
            warehouse=self.warehouse,
            created_by=self.warehouse_user,
            assigned_dispatcher=self.other_dispatch,
            status=Shipment.Status.LOADED,
        )

    def test_sales_sees_only_explicitly_assigned_customers(self):
        self.client.force_login(self.sales)
        response = self.client.get(reverse('customer_list'))
        self.assertContains(response, 'Satış Müşterisi')
        self.assertNotContains(response, 'Diğer Müşteri')
        self.assertNotContains(response, 'Atanmamış Müşteri')
        self.assertEqual(
            self.client.get(reverse('customer_detail', args=[self.other_customer.pk])).status_code,
            404,
        )

    def test_warehouse_sees_operational_orders_but_not_pending_orders(self):
        self.client.force_login(self.warehouse_user)
        response = self.client.get(reverse('order_list'))
        self.assertContains(response, 'ROLE-SIP-A')
        self.assertNotContains(response, 'ROLE-SIP-P')

    def test_dispatch_sees_only_assigned_shipments(self):
        self.client.force_login(self.dispatch)
        response = self.client.get(reverse('shipment_list'))
        self.assertContains(response, 'ROLE-SVK-1')
        self.assertNotContains(response, 'ROLE-SVK-2')

    def test_shipment_form_lists_only_dispatch_users(self):
        form = ShipmentForm(instance=self.assigned_shipment)
        usernames = set(
            form.fields['assigned_dispatcher'].queryset.values_list('username', flat=True)
        )
        self.assertIn('role_dispatch', usernames)
        self.assertIn('role_dispatch_2', usernames)
        self.assertNotIn('role_warehouse', usernames)
        self.assertNotIn('role_sales', usernames)


class WarehouseManagementTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('warehouse_admin', password='Pass12345!')
        self.admin.profile.role = UserProfile.Role.ADMIN
        self.admin.profile.save()
        self.management = User.objects.create_user('warehouse_management', password='Pass12345!')
        self.management.profile.role = UserProfile.Role.MANAGEMENT
        self.management.profile.save()
        self.warehouse = Warehouse.objects.create(code='ANA', name='Ana Depo', is_active=True)

    def test_admin_can_edit_warehouse(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('warehouse_edit', args=[self.warehouse.pk]),
            {'code': 'MERKEZ', 'name': 'Merkez Depo', 'address': 'Lefkoşa', 'is_active': 'on'},
        )
        self.assertRedirects(response, reverse('warehouse_list'))
        self.warehouse.refresh_from_db()
        self.assertEqual(self.warehouse.code, 'MERKEZ')
        self.assertEqual(self.warehouse.name, 'Merkez Depo')

    def test_admin_can_toggle_warehouse(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('warehouse_toggle', args=[self.warehouse.pk]))
        self.assertRedirects(response, reverse('warehouse_list'))
        self.warehouse.refresh_from_db()
        self.assertFalse(self.warehouse.is_active)

    def test_management_can_edit_and_toggle_warehouse(self):
        self.client.force_login(self.management)
        edit_response = self.client.post(
            reverse('warehouse_edit', args=[self.warehouse.pk]),
            {'code': 'ANA', 'name': 'Ana Depo Güncel', 'address': '', 'is_active': 'on'},
        )
        self.assertRedirects(edit_response, reverse('warehouse_list'))
        toggle_response = self.client.post(reverse('warehouse_toggle', args=[self.warehouse.pk]))
        self.assertRedirects(toggle_response, reverse('warehouse_list'))
        self.warehouse.refresh_from_db()
        self.assertEqual(self.warehouse.name, 'Ana Depo Güncel')
        self.assertFalse(self.warehouse.is_active)
