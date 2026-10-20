from decimal import Decimal, InvalidOperation
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from .models import AuditLog, ConnectionItem, DocumentCounter, Order, OrderItem, Shipment, ShipmentItem

PREFIXES = {'connection': 'BGL', 'order': 'SIP', 'shipment': 'SVK'}

def next_document_number(kind):
    year = timezone.localdate().year
    key = f'{kind}:{year}'
    with transaction.atomic():
        counter, _ = DocumentCounter.objects.select_for_update().get_or_create(key=key, defaults={'year': year, 'value': 0})
        counter.value += 1
        counter.save(update_fields=['value'])
    return f"{PREFIXES[kind]}-{year}-{counter.value:05d}"

def client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    return (forwarded.split(',')[0].strip() if forwarded else request.META.get('REMOTE_ADDR')) or None

def audit(request, action, obj, details=None):
    AuditLog.objects.create(
        user=request.user if request.user.is_authenticated else None,
        action=action,
        model_name=obj.__class__.__name__,
        object_id=str(obj.pk),
        object_repr=str(obj)[:250],
        details=details or {},
        ip_address=client_ip(request),
    )

def parse_quantity(value, field='Miktar'):
    text = str(value or '').strip()
    if not text:
        return 0
    try:
        number = Decimal(text.replace(',', '.'))
    except InvalidOperation:
        raise ValidationError(f'{field} geçerli bir tam sayı olmalıdır.')
    if number != number.to_integral_value():
        raise ValidationError(f'{field} tam sayı olmalıdır; virgüllü miktar kullanılamaz.')
    quantity = int(number)
    if quantity < 0:
        raise ValidationError(f'{field} negatif olamaz.')
    return quantity

def create_order_from_request(*, customer, user, order_data, quantities):
    selected = [(int(pk), parse_quantity(qty)) for pk, qty in quantities.items() if parse_quantity(qty) > 0]
    if not selected:
        raise ValidationError('En az bir ürün miktarı girilmelidir.')
    with transaction.atomic():
        locked = {x.pk: x for x in ConnectionItem.objects.select_for_update().select_related('connection','product').filter(pk__in=[x[0] for x in selected])}
        order = Order.objects.create(number=next_document_number('order'), customer=customer, created_by=user, **order_data)
        for item_id, qty in selected:
            item = locked.get(item_id)
            if not item or item.connection.customer_id != customer.id:
                raise ValidationError('Seçilen ürün müşteriye ait değil.')
            if item.connection.status not in {'ACTIVE','PARTIAL'}:
                raise ValidationError(f'{item.product.name} için bağlantı aktif değil.')
            if qty > item.available_quantity:
                raise ValidationError(f'{item.product.name} / {item.connection.invoice_no}: kullanılabilir miktar {item.available_quantity}.')
            OrderItem.objects.create(order=order, connection_item=item, quantity_requested=qty)
        return order

def shipment_balance_rows(shipment):
    """Sevk tutanağı için müşterinin bağlantı bakiyesi: önceki teslim, bu sevk ve sevk sonrası kalan.

    Teslim edilmiş sevkiyatta yalnızca bu sevkten önce teslim edilenler sayılır; böylece
    tutanak sonradan yeniden basıldığında da teslim anındaki tabloyu gösterir.
    """
    this_quantities = {x.connection_item_id: x.quantity_delivered for x in shipment.items.all()}
    previous = ShipmentItem.objects.filter(
        connection_item__connection__customer_id=shipment.customer_id,
        shipment__status=Shipment.Status.DELIVERED,
    ).exclude(shipment=shipment)
    if shipment.status == Shipment.Status.DELIVERED and shipment.delivered_at:
        previous = previous.filter(shipment__delivered_at__lt=shipment.delivered_at)
    delivered_before = dict(previous.values('connection_item_id').annotate(v=Sum('quantity_delivered')).values_list('connection_item_id', 'v'))
    rows = []
    items = ConnectionItem.objects.select_related('connection', 'product').filter(
        connection__customer_id=shipment.customer_id,
    ).exclude(connection__status='CANCELLED').order_by('connection__invoice_date', 'connection_id', 'product__name', 'id')
    for item in items:
        before = delivered_before.get(item.pk, 0)
        this = this_quantities.get(item.pk, 0)
        remaining = max(item.effective_quantity - before - this, 0)
        if this or remaining:
            rows.append({'item': item, 'total': item.effective_quantity, 'before': before, 'this': this, 'remaining': remaining})
    return rows

def deliver_shipment(*, shipment, user):
    with transaction.atomic():
        shipment = Shipment.objects.select_for_update().select_related('order').get(pk=shipment.pk)
        if shipment.status == Shipment.Status.DELIVERED:
            raise ValidationError('Bu sevkiyat daha önce teslim edilmiş.')
        if shipment.status == Shipment.Status.CANCELLED:
            raise ValidationError('İptal edilmiş sevkiyat teslim edilemez.')
        order = Order.objects.select_for_update().get(pk=shipment.order_id)
        if order.status == Order.Status.CANCELLED:
            raise ValidationError('İptal edilmiş siparişe bağlı sevkiyat teslim edilemez.')
        items = list(shipment.items.select_related('order_item','connection_item__product','connection_item__connection').all())
        if not items:
            raise ValidationError('Sevkiyat kalemi bulunmuyor.')
        locked_order_items = {x.pk:x for x in OrderItem.objects.select_for_update().filter(pk__in=[x.order_item_id for x in items])}
        locked_connection_items = {x.pk:x for x in ConnectionItem.objects.select_for_update().filter(pk__in=[x.connection_item_id for x in items])}
        for line in items:
            order_item=locked_order_items[line.order_item_id]
            connection_item=locked_connection_items[line.connection_item_id]
            if line.quantity_delivered <= 0:
                raise ValidationError('Teslim miktarları sıfırdan büyük olmalıdır.')
            already = order_item.delivered_quantity
            if line.quantity_delivered > order_item.quantity_requested - already:
                raise ValidationError(f'{connection_item.product.name}: teslim miktarı sipariş bakiyesini aşıyor.')
            if line.quantity_delivered > connection_item.remaining_quantity:
                raise ValidationError(f'{connection_item.product.name}: fatura bakiyesi yetersiz.')
        shipment.status = Shipment.Status.DELIVERED
        shipment.delivery_date = shipment.delivery_date or timezone.localdate()
        shipment.delivered_at = timezone.now()
        shipment.delivered_by = user
        shipment.save(update_fields=['status','delivery_date','delivered_at','delivered_by','updated_at'])
        order.refresh_status()
        connection_ids={x.connection_item.connection_id for x in items}
        for connection_id in connection_ids:
            locked_connection_items[next(k for k,v in locked_connection_items.items() if v.connection_id==connection_id)].connection.refresh_status()
        return shipment

