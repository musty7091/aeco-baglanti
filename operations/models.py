import uuid
from decimal import Decimal, ROUND_HALF_UP
from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import F, Sum, Q
from django.utils import timezone

ZERO = 0
MONEY_ZERO = Decimal('0.00')

class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        abstract = True

class CompanySettings(TimeStampedModel):
    company_name = models.CharField(max_length=200, default='AECO TRADING LTD.')
    registration_no = models.CharField(max_length=100, blank=True)
    tax_no = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    footer_note = models.CharField(max_length=250, blank=True, default='Bu belge elektronik sistem üzerinden oluşturulmuştur.')
    document_prefix = models.CharField(max_length=10, default='AECO')
    default_currency = models.CharField(max_length=3, default='TRY')
    logo = models.ImageField(upload_to='company/', blank=True)

    class Meta:
        verbose_name = 'Şirket ayarı'
        verbose_name_plural = 'Şirket ayarları'

    def __str__(self):
        return self.company_name

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

class UserProfile(TimeStampedModel):
    class Role(models.TextChoices):
        ADMIN = 'ADMIN', 'Sistem Yöneticisi'
        MANAGEMENT = 'MANAGEMENT', 'Yönetim / Kontrol'
        SALES = 'SALES', 'Satış Temsilcisi'
        WAREHOUSE = 'WAREHOUSE', 'Depo Personeli'
        DISPATCH = 'DISPATCH', 'Sevkiyat Personeli'
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.SALES)
    phone = models.CharField(max_length=30, blank=True)
    active = models.BooleanField(default=True)

    def __str__(self):
        return f'{self.user.get_full_name() or self.user.username} - {self.get_role_display()}'

    @property
    def can_manage(self):
        return self.role in {self.Role.ADMIN, self.Role.MANAGEMENT}

class Customer(TimeStampedModel):
    code = models.CharField(max_length=40, unique=True, blank=True, editable=False)
    name = models.CharField(max_length=200)
    contact_name = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    assigned_salesperson = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='customers')
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']
        indexes = [models.Index(fields=['code']), models.Index(fields=['name'])]

    @classmethod
    def next_code(cls):
        """Müşteri kodunu transaction ve kilitli sayaçla güvenli biçimde üretir."""
        with transaction.atomic():
            counter, _created = DocumentCounter.objects.get_or_create(
                key='customer',
                defaults={'year': 0, 'value': 0},
            )
            counter = DocumentCounter.objects.select_for_update().get(pk=counter.pk)
            DocumentCounter.objects.filter(pk=counter.pk).update(value=F('value') + 1)
            counter.refresh_from_db(fields=['value'])
            return f'MUS-{counter.value:05d}'

    def save(self, *args, **kwargs):
        if self.code:
            return super().save(*args, **kwargs)
        with transaction.atomic():
            self.code = self.next_code()
            return super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.code} - {self.name}'

class Product(TimeStampedModel):
    class Unit(models.TextChoices):
        PIECE = 'ADET', 'Adet'
        CASE = 'KOLI', 'Koli'
        PACK = 'PAKET', 'Paket'
        BOTTLE = 'SISE', 'Şişe'

    barcode = models.CharField('Barkod', max_length=50, unique=True, db_index=True)
    name = models.CharField('Ürün adı', max_length=220)
    brand = models.CharField('Marka', max_length=120, blank=True)
    category = models.CharField('Kategori', max_length=120, blank=True)
    volume = models.CharField('Hacim', max_length=50, blank=True)
    units_per_case = models.PositiveIntegerField('Koli içi adet', default=1)
    base_unit = models.CharField('Takip birimi', max_length=10, choices=Unit.choices, default=Unit.PIECE)
    image = models.ImageField('Ürün görseli', upload_to='products/', blank=True)
    is_active = models.BooleanField('Aktif', default=True)

    def save(self, *args, **kwargs):
        self.base_unit = self.Unit.PIECE
        self.units_per_case = 1
        self.category = ''
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['name']
        indexes = [models.Index(fields=['name']), models.Index(fields=['barcode'])]

    def __str__(self):
        return f'{self.barcode} - {self.name}'

class Warehouse(TimeStampedModel):
    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=120)
    address = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Vehicle(TimeStampedModel):
    plate = models.CharField('Araç plakası', max_length=30, unique=True)
    description = models.CharField('Araç açıklaması', max_length=120, blank=True)
    is_active = models.BooleanField('Aktif', default=True)

    class Meta:
        ordering = ['plate']
        verbose_name = 'Araç'
        verbose_name_plural = 'Araçlar'

    def __str__(self):
        return f'{self.plate} - {self.description}' if self.description else self.plate


class DocumentCounter(models.Model):
    key = models.CharField(max_length=50, unique=True)
    year = models.PositiveIntegerField()
    value = models.PositiveIntegerField(default=0)

class ConnectionSale(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Taslak'
        PENDING = 'PENDING', 'Onay Bekliyor'
        ACTIVE = 'ACTIVE', 'Teslimat Bekliyor'
        PARTIAL = 'PARTIAL', 'Kısmen Teslim Edildi'
        COMPLETED = 'COMPLETED', 'Tamamlandı'
        CANCELLED = 'CANCELLED', 'İptal Edildi'
    number = models.CharField(max_length=40, unique=True, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='connections')
    invoice_no = models.CharField(max_length=80)
    invoice_date = models.DateField()
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.DRAFT)
    notes = models.TextField(blank=True)
    invoice_attachment = models.FileField(upload_to='invoices/%Y/%m/', blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='connections_created')
    approved_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name='connections_approved')
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-invoice_date', '-id']
        constraints = [models.UniqueConstraint(fields=['customer', 'invoice_no'], name='unique_customer_invoice')]
        indexes = [models.Index(fields=['status']), models.Index(fields=['invoice_no'])]

    def __str__(self):
        return f'{self.number} / {self.invoice_no}'

    @property
    def is_locked(self):
        return self.status not in {self.Status.DRAFT, self.Status.PENDING}

    @property
    def total_quantity(self):
        return sum((item.effective_quantity for item in self.items.all()), ZERO)

    @property
    def delivered_quantity(self):
        return sum((item.delivered_quantity for item in self.items.all()), ZERO)

    @property
    def remaining_quantity(self):
        return sum((item.remaining_quantity for item in self.items.all()), ZERO)

    def _sum_amount(self, attribute):
        total = sum((getattr(item, attribute) for item in self.items.all()), MONEY_ZERO)
        return total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @property
    def gross_amount(self):
        return self._sum_amount('gross_amount')

    @property
    def discount_amount(self):
        return self._sum_amount('discount_amount')

    @property
    def net_amount(self):
        return self._sum_amount('net_amount')

    @property
    def vat_amount(self):
        return self._sum_amount('vat_amount')

    @property
    def total_amount(self):
        return self._sum_amount('total_amount')

    def refresh_status(self):
        if self.status == self.Status.CANCELLED:
            return
        total = self.total_quantity
        delivered = self.delivered_quantity
        if total > ZERO and delivered >= total:
            new = self.Status.COMPLETED
        elif delivered > ZERO:
            new = self.Status.PARTIAL
        elif self.approved_at:
            new = self.Status.ACTIVE
        else:
            return
        if self.status != new:
            ConnectionSale.objects.filter(pk=self.pk).update(status=new)
            self.status = new

class ConnectionItem(TimeStampedModel):
    connection = models.ForeignKey(ConnectionSale, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='connection_items')
    quantity = models.PositiveIntegerField('Bağlantı miktarı')
    unit = models.CharField(max_length=10, choices=Product.Unit.choices, default=Product.Unit.PIECE)
    unit_price = models.DecimalField('Birim fiyat', max_digits=14, decimal_places=2, null=True, blank=True)
    discount_rate = models.DecimalField('İskonto oranı', max_digits=5, decimal_places=2, default=0)
    vat_rate = models.DecimalField('KDV oranı', max_digits=5, decimal_places=2, default=20)

    def save(self, *args, **kwargs):
        self.unit = Product.Unit.PIECE
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['product__name', 'id']
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name='connection_quantity_positive'),
            models.CheckConstraint(condition=Q(discount_rate__gte=0) & Q(discount_rate__lte=100), name='connection_discount_rate_valid'),
            models.CheckConstraint(condition=Q(vat_rate__gte=0) & Q(vat_rate__lte=100), name='connection_vat_rate_valid'),
        ]

    def __str__(self):
        return f'{self.connection.invoice_no} - {self.product.name}'

    @property
    def gross_amount(self):
        return (Decimal(self.quantity) * (self.unit_price or Decimal('0'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @property
    def discount_amount(self):
        return (self.gross_amount * (self.discount_rate or Decimal('0')) / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @property
    def net_amount(self):
        return (self.gross_amount - self.discount_amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @property
    def vat_amount(self):
        return (self.net_amount * (self.vat_rate or Decimal('0')) / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @property
    def total_amount(self):
        return (self.net_amount + self.vat_amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @property
    def is_free_item(self):
        return self.total_amount == Decimal('0.00')

    @property
    def adjustment_quantity(self):
        return self.adjustments.aggregate(v=Sum('signed_quantity'))['v'] or ZERO

    @property
    def effective_quantity(self):
        return self.quantity + self.adjustment_quantity

    @property
    def delivered_quantity(self):
        return self.shipment_items.filter(shipment__status=Shipment.Status.DELIVERED).aggregate(v=Sum('quantity_delivered'))['v'] or ZERO

    @property
    def reserved_quantity(self):
        active_items = self.order_items.exclude(order__status__in=[Order.Status.CANCELLED, Order.Status.COMPLETED])
        reserved = ZERO
        for item in active_items:
            reserved += max(item.quantity_requested - item.delivered_quantity, ZERO)
        return reserved

    @property
    def remaining_quantity(self):
        return max(self.effective_quantity - self.delivered_quantity, ZERO)

    @property
    def available_quantity(self):
        return max(self.remaining_quantity - self.reserved_quantity, ZERO)

class BalanceAdjustment(TimeStampedModel):
    class Kind(models.TextChoices):
        RETURN = 'RETURN', 'Müşteri İadesi'
        DAMAGE = 'DAMAGE', 'Hasar / Fire'
        CORRECTION = 'CORRECTION', 'Miktar Düzeltmesi'
        TRANSFER = 'TRANSFER', 'Devir / Transfer'
        OTHER = 'OTHER', 'Diğer'
    connection_item = models.ForeignKey(ConnectionItem, on_delete=models.PROTECT, related_name='adjustments')
    signed_quantity = models.IntegerField('Düzeltme miktarı', help_text='Artış için pozitif, azalış için negatif tam sayı girin')
    kind = models.CharField(max_length=20, choices=Kind.choices)
    reason = models.TextField()
    reference_no = models.CharField(max_length=80, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)
    approved_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='adjustments_approved')

    def clean(self):
        if self.signed_quantity == ZERO:
            raise ValidationError('Düzeltme miktarı sıfır olamaz.')
        minimum_committed = self.connection_item.delivered_quantity + self.connection_item.reserved_quantity
        if self.connection_item.effective_quantity + self.signed_quantity < minimum_committed:
            raise ValidationError('Düzeltme sonrası toplam hak, teslim edilmiş ve siparişe ayrılmış miktarın altına düşemez.')

class Order(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Taslak'
        PENDING = 'PENDING', 'Onay Bekliyor'
        APPROVED = 'APPROVED', 'Onaylandı'
        PREPARING = 'PREPARING', 'Sevkte'
        PARTIAL = 'PARTIAL', 'Kısmi Sevk'
        COMPLETED = 'COMPLETED', 'Tamamlandı'
        CANCELLED = 'CANCELLED', 'İptal Edildi'
    number = models.CharField(max_length=40, unique=True, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='orders')
    order_date = models.DateField(default=timezone.localdate)
    requested_delivery_date = models.DateField(null=True, blank=True)
    delivery_address = models.TextField(blank=True)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.PENDING)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='orders_created')
    approved_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name='orders_approved')
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-order_date', '-id']
        indexes = [models.Index(fields=['status']), models.Index(fields=['customer', 'order_date'])]

    def __str__(self):
        return self.number

    @property
    def total_requested(self):
        return self.items.aggregate(v=Sum('quantity_requested'))['v'] or ZERO

    @property
    def total_delivered(self):
        return sum((item.delivered_quantity for item in self.items.all()), ZERO)

    @property
    def total_remaining(self):
        return max(self.total_requested - self.total_delivered, ZERO)

    def refresh_status(self):
        if self.status == self.Status.CANCELLED:
            return
        total = self.total_requested
        delivered = self.total_delivered
        if total > ZERO and delivered >= total:
            new = self.Status.COMPLETED
        elif delivered > ZERO:
            new = self.Status.PARTIAL
        elif self.approved_at and self.status in {self.Status.PENDING, self.Status.DRAFT}:
            new = self.Status.APPROVED
        else:
            return
        if self.status != new:
            Order.objects.filter(pk=self.pk).update(status=new)
            self.status = new

class OrderItem(TimeStampedModel):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    connection_item = models.ForeignKey(ConnectionItem, on_delete=models.PROTECT, related_name='order_items')
    quantity_requested = models.PositiveIntegerField('Talep miktarı')
    notes = models.CharField(max_length=250, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['order', 'connection_item'], name='unique_order_connection_item'),
            models.CheckConstraint(condition=Q(quantity_requested__gt=0), name='order_quantity_positive'),
        ]

    @property
    def delivered_quantity(self):
        return self.shipment_items.filter(shipment__status=Shipment.Status.DELIVERED).aggregate(v=Sum('quantity_delivered'))['v'] or ZERO

    @property
    def remaining_quantity(self):
        return max(self.quantity_requested - self.delivered_quantity, ZERO)

    @property
    def open_shipment_quantity(self):
        return self.shipment_items.exclude(shipment__status__in=[Shipment.Status.DELIVERED, Shipment.Status.CANCELLED]).aggregate(v=Sum('quantity_delivered'))['v'] or ZERO

    @property
    def allocatable_quantity(self):
        return max(self.remaining_quantity - self.open_shipment_quantity, ZERO)

    def clean(self):
        if self.connection_item.connection.customer_id != self.order.customer_id:
            raise ValidationError('Sipariş kalemi başka bir müşterinin bağlantısına ait olamaz.')

class Shipment(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Taslak'
        PREPARING = 'PREPARING', 'Hazırlanıyor'
        LOADED = 'LOADED', 'Yüklendi'
        ON_ROUTE = 'ON_ROUTE', 'Yolda'
        DELIVERED = 'DELIVERED', 'Teslim Edildi'
        CANCELLED = 'CANCELLED', 'İptal Edildi'
    number = models.CharField(max_length=40, unique=True, blank=True)
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name='shipments')
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='shipments')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='shipments')
    shipment_date = models.DateField(default=timezone.localdate)
    delivery_date = models.DateField(null=True, blank=True)
    delivery_address = models.TextField(blank=True)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.DRAFT)
    vehicle_plate = models.CharField(max_length=30, blank=True)
    prepared_by_name = models.CharField(max_length=120, blank=True)
    delivered_to = models.CharField(max_length=120, blank=True)
    receiver_signature = models.ImageField(upload_to='signatures/%Y/%m/', blank=True)
    delivery_proof = models.ImageField(upload_to='delivery_proofs/%Y/%m/', blank=True)
    delivery_notes = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    verification_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='shipments_created')
    assigned_dispatcher = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='shipments_assigned',
        verbose_name='Sevkiyat personeli',
    )
    delivered_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name='shipments_delivered')
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-shipment_date', '-id']
        indexes = [models.Index(fields=['status']), models.Index(fields=['number'])]

    def __str__(self):
        return self.number

    @property
    def total_delivered(self):
        return self.items.aggregate(v=Sum('quantity_delivered'))['v'] or ZERO

class ShipmentItem(TimeStampedModel):
    shipment = models.ForeignKey(Shipment, on_delete=models.CASCADE, related_name='items')
    order_item = models.ForeignKey(OrderItem, on_delete=models.PROTECT, related_name='shipment_items')
    connection_item = models.ForeignKey(ConnectionItem, on_delete=models.PROTECT, related_name='shipment_items')
    quantity_delivered = models.PositiveIntegerField('Sevk miktarı', default=0)
    notes = models.CharField('Kalem notu', max_length=250, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['shipment', 'order_item'], name='unique_shipment_order_item'),
            models.CheckConstraint(condition=Q(quantity_delivered__gte=0), name='shipment_delivered_nonnegative'),
        ]

    def clean(self):
        if self.connection_item_id != self.order_item.connection_item_id:
            raise ValidationError('Fatura bağlantısı sipariş kalemiyle uyuşmuyor.')
        if self.quantity_delivered > self.order_item.remaining_quantity and self.shipment.status != Shipment.Status.DELIVERED:
            raise ValidationError('Sevk miktarı siparişte kalan miktarı aşamaz.')

class AuditLog(models.Model):
    action_time = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=30)
    model_name = models.CharField(max_length=80)
    object_id = models.CharField(max_length=80)
    object_repr = models.CharField(max_length=250)
    details = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ['-action_time']
        indexes = [models.Index(fields=['model_name', 'object_id']), models.Index(fields=['action_time'])]

    def __str__(self):
        return f'{self.action_time} - {self.action} - {self.object_repr}'
