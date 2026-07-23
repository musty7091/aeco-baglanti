from datetime import timedelta
from io import BytesIO
from pathlib import Path
import zipfile
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from .excel import customer_template, export_balances, export_customers, export_products, import_customers, import_products, product_template
from .forms import (BalanceAdjustmentForm, CompanySettingsForm, ConnectionItemFormSet, ConnectionSaleForm,
                    CustomerForm, ExcelUploadForm, OrderHeaderForm, ProductForm, ShipmentDeliveryForm, ShipmentForm,
                    UserCreateForm, UserEditForm, VehicleForm, WarehouseForm)
from .models import (AuditLog, BalanceAdjustment, CompanySettings, ConnectionItem, ConnectionSale,
                     Customer, Order, OrderItem, Product, Shipment, ShipmentItem, UserProfile, Vehicle, Warehouse)
from .pdf import connection_pdf, customer_balance_pdf, order_pdf, shipment_pdf
from .permissions import (
    ADMIN, DISPATCH, MANAGEMENT, SALES, WAREHOUSE,
    admin_required, audit_access_required, customer_access_required,
    customers_for_user, get_role, has_role, is_manager, manage_required,
    order_access_required, orders_for_user, product_access_required,
    report_access_required, role_required, shipment_access_required,
    shipments_for_user,
)
from .scanner import scanner_client_config
from .services import audit, create_order_from_request, deliver_shipment, next_document_number, parse_quantity

PER_PAGE=25

def page(request, queryset, n=PER_PAGE):
    return Paginator(queryset,n).get_page(request.GET.get('page'))

def visible_customers(request):
    return customers_for_user(request.user)


def visible_orders(request):
    return orders_for_user(request.user)


def visible_shipments(request):
    return shipments_for_user(request.user)


def customer_allowed(request, customer):
    return visible_customers(request).filter(pk=customer.pk).exists()


def order_allowed(request, order):
    return visible_orders(request).filter(pk=order.pk).exists()


def shipment_allowed(request, shipment):
    return visible_shipments(request).filter(pk=shipment.pk).exists()

def attachment_response(data, filename, content_type):
    response=HttpResponse(data,content_type=content_type)
    response['Content-Disposition']=f'attachment; filename="{filename}"'
    return response

@role_required(ADMIN, MANAGEMENT, SALES, WAREHOUSE, DISPATCH)
def dashboard(request):
    customers=visible_customers(request)
    orders=visible_orders(request)
    shipments=visible_shipments(request)
    role=get_role(request.user)

    if role in {ADMIN, MANAGEMENT, SALES} or request.user.is_superuser:
        connections=ConnectionSale.objects.filter(customer__in=customers).exclude(status=ConnectionSale.Status.CANCELLED)
        items=ConnectionItem.objects.filter(connection__in=connections).select_related('product','connection__customer')
        total_obligation=sum((x.remaining_quantity for x in items), 0)
        total_available=sum((x.available_quantity for x in items), 0)
    else:
        connections=ConnectionSale.objects.none()
        total_obligation=0
        total_available=0

    if role in {WAREHOUSE, DISPATCH}:
        customer_count=Customer.objects.filter(Q(orders__in=orders)|Q(shipments__in=shipments)).distinct().count()
    else:
        customer_count=customers.filter(is_active=True).count()

    stale_date=timezone.localdate()-timedelta(days=90)
    context={
        'customer_count':customer_count,
        'active_connection_count':connections.filter(status__in=[ConnectionSale.Status.ACTIVE,ConnectionSale.Status.PARTIAL]).count(),
        'open_order_count':orders.exclude(status__in=[Order.Status.COMPLETED,Order.Status.CANCELLED]).count(),
        'pending_shipment_count':shipments.exclude(status__in=[Shipment.Status.DELIVERED,Shipment.Status.CANCELLED]).count(),
        'total_obligation':total_obligation,
        'total_available':total_available,
        'recent_shipments':shipments.order_by('-shipment_date','-id')[:6],
        'recent_orders':orders.order_by('-order_date','-id')[:6],
        'stale_connections':connections.filter(invoice_date__lt=stale_date,status__in=[ConnectionSale.Status.ACTIVE,ConnectionSale.Status.PARTIAL]).select_related('customer')[:5],
    }
    return render(request,'operations/dashboard.html',context)

@customer_access_required
def customer_list(request):
    qs=visible_customers(request)
    q=request.GET.get('q','').strip()
    if q:
        qs=qs.filter(Q(name__icontains=q)|Q(code__icontains=q)|Q(phone__icontains=q)|Q(contact_name__icontains=q))
    return render(request,'operations/customer_list.html',{'page_obj':page(request,qs),'q':q})

@manage_required
def customer_create(request):
    form=CustomerForm(request.POST or None)
    if form.is_valid():
        obj=form.save(); audit(request,'CREATE',obj); messages.success(request,'Müşteri oluşturuldu.'); return redirect('customer_detail',obj.pk)
    return render(request,'operations/form.html',{'form':form,'title':'Yeni Müşteri','subtitle':'Ticari ve iletişim bilgileri','cancel_url':'customer_list'})

@manage_required
def customer_edit(request,pk):
    obj=get_object_or_404(Customer,pk=pk); form=CustomerForm(request.POST or None,instance=obj)
    if form.is_valid():
        obj=form.save(); audit(request,'UPDATE',obj); messages.success(request,'Müşteri güncellendi.'); return redirect('customer_detail',obj.pk)
    return render(request,'operations/form.html',{'form':form,'title':'Müşteriyi Düzenle','cancel_url':'customer_detail','cancel_args':[obj.pk]})

@customer_access_required
def customer_detail(request,pk):
    customer=get_object_or_404(visible_customers(request),pk=pk)
    items=ConnectionItem.objects.select_related('connection','product').filter(connection__customer=customer).exclude(connection__status=ConnectionSale.Status.CANCELLED).order_by('product__name','connection__invoice_date')
    context={
        'customer':customer,
        'items':items,
        'connections':customer.connections.all()[:10],
        'orders':customer.orders.all()[:10],
        'shipments':customer.shipments.all()[:10],
        'shipment_lines':ShipmentItem.objects.select_related('shipment','connection_item__product','connection_item__connection').filter(shipment__customer=customer,shipment__status=Shipment.Status.DELIVERED).order_by('-shipment__delivery_date','-shipment_id')[:25],
    }
    return render(request,'operations/customer_detail.html',context)

@customer_access_required
def customer_history(request,pk):
    customer=get_object_or_404(visible_customers(request),pk=pk)
    qs=ShipmentItem.objects.select_related('shipment','connection_item__product','connection_item__connection').filter(shipment__customer=customer).order_by('-shipment__shipment_date','-id')
    date_from=request.GET.get('date_from')
    date_to=request.GET.get('date_to')
    if date_from:
        qs=qs.filter(shipment__shipment_date__gte=date_from)
    if date_to:
        qs=qs.filter(shipment__shipment_date__lte=date_to)
    return render(request,'operations/customer_history.html',{'customer':customer,'page_obj':page(request,qs,20),'date_from':date_from,'date_to':date_to})

@customer_access_required
def customer_balance_pdf_view(request,pk):
    customer=get_object_or_404(visible_customers(request),pk=pk)
    return attachment_response(customer_balance_pdf(customer),f'{customer.code}_baglantili_mallar.pdf','application/pdf')

@product_access_required
def product_list(request):
    qs=Product.objects.all()
    q=request.GET.get('q','').strip()
    if q:
        qs=qs.filter(Q(name__icontains=q)|Q(barcode__icontains=q)|Q(brand__icontains=q))
    return render(request,'operations/product_list.html',{'page_obj':page(request,qs),'q':q})

@manage_required
def product_create(request):
    form=ProductForm(request.POST or None,request.FILES or None)
    if form.is_valid(): obj=form.save();audit(request,'CREATE',obj);messages.success(request,'Ürün oluşturuldu.');return redirect('product_list')
    return render(request,'operations/form.html',{'form':form,'title':'Yeni Ürün','cancel_url':'product_list'})

@manage_required
def product_edit(request,pk):
    obj=get_object_or_404(Product,pk=pk);form=ProductForm(request.POST or None,request.FILES or None,instance=obj)
    if form.is_valid(): obj=form.save();audit(request,'UPDATE',obj);messages.success(request,'Ürün güncellendi.');return redirect('product_list')
    return render(request,'operations/form.html',{'form':form,'title':'Ürünü Düzenle','cancel_url':'product_list'})

@customer_access_required
def connection_list(request):
    qs=ConnectionSale.objects.select_related('customer').prefetch_related('items').filter(customer__in=visible_customers(request))
    q=request.GET.get('q','').strip()
    status=request.GET.get('status','')
    if q:
        qs=qs.filter(Q(number__icontains=q)|Q(invoice_no__icontains=q)|Q(customer__name__icontains=q))
    if status:
        qs=qs.filter(status=status)
    return render(request,'operations/connection_list.html',{'page_obj':page(request,qs),'q':q,'status':status,'statuses':ConnectionSale.Status.choices})

@manage_required
def connection_create(request):
    obj=ConnectionSale(created_by=request.user,status=ConnectionSale.Status.PENDING)
    form=ConnectionSaleForm(request.POST or None,request.FILES or None,instance=obj)
    formset=ConnectionItemFormSet(request.POST or None,instance=obj,prefix='items')
    if request.method=='POST' and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            obj=form.save(commit=False);obj.number=next_document_number('connection');obj.created_by=request.user;obj.status=ConnectionSale.Status.PENDING;obj.save();formset.instance=obj;formset.save()
        audit(request,'CREATE',obj,{'invoice_no':obj.invoice_no});messages.success(request,'Bağlantılı satış kaydı oluşturuldu ve onaya gönderildi.');return redirect('connection_detail',obj.pk)
    return render(request,'operations/connection_form.html',{'form':form,'formset':formset,'title':'Yeni Bağlantılı Satış','scanner':scanner_client_config()})

@manage_required
def connection_edit(request,pk):
    obj=get_object_or_404(ConnectionSale,pk=pk)
    if obj.is_locked:
        messages.error(request,'Onaylanmış bağlantı doğrudan değiştirilemez. Düzeltme hareketi kullanın.');return redirect('connection_detail',pk)
    form=ConnectionSaleForm(request.POST or None,request.FILES or None,instance=obj);formset=ConnectionItemFormSet(request.POST or None,instance=obj,prefix='items')
    if request.method=='POST' and form.is_valid() and formset.is_valid():
        with transaction.atomic(): form.save();formset.save()
        audit(request,'UPDATE',obj);messages.success(request,'Bağlantı güncellendi.');return redirect('connection_detail',pk)
    return render(request,'operations/connection_form.html',{'form':form,'formset':formset,'title':'Bağlantıyı Düzenle','object':obj,'scanner':scanner_client_config()})

@customer_access_required
def connection_detail(request,pk):
    obj=get_object_or_404(ConnectionSale.objects.select_related('customer','created_by','approved_by').prefetch_related('items').filter(customer__in=visible_customers(request)),pk=pk)
    return render(request,'operations/connection_detail.html',{
        'connection':obj,
        'items':obj.items.select_related('product'),
        'shipment_lines':ShipmentItem.objects.select_related('shipment','connection_item__product').filter(connection_item__connection=obj).order_by('-shipment__shipment_date','-id')[:50],
        'adjustments':BalanceAdjustment.objects.select_related('connection_item__product','created_by').filter(connection_item__connection=obj).order_by('-created_at')[:50],
    })

@customer_access_required
def connection_pdf_view(request, pk):
    obj = get_object_or_404(
        ConnectionSale.objects.select_related('customer', 'created_by', 'approved_by')
        .prefetch_related('items__product')
        .filter(customer__in=visible_customers(request)),
        pk=pk,
    )
    return attachment_response(
        connection_pdf(obj),
        f'{obj.number or obj.invoice_no}_baglanti.pdf',
        'application/pdf',
    )


@manage_required
@require_POST
def connection_approve(request,pk):
    obj=get_object_or_404(ConnectionSale,pk=pk)
    if obj.status not in [ConnectionSale.Status.DRAFT,ConnectionSale.Status.PENDING]: messages.error(request,'Bu kayıt onaylanamaz.')
    elif not obj.items.exists(): messages.error(request,'Ürün kalemi bulunmuyor.')
    else:
        obj.status=ConnectionSale.Status.ACTIVE;obj.approved_by=request.user;obj.approved_at=timezone.now();obj.save(update_fields=['status','approved_by','approved_at','updated_at']);audit(request,'APPROVE',obj);messages.success(request,'Bağlantı onaylandı ve teslimata açıldı.')
    return redirect('connection_detail',pk)

@manage_required
@require_POST
def connection_cancel(request,pk):
    obj=get_object_or_404(ConnectionSale,pk=pk)
    if obj.delivered_quantity>0 or any(x.reserved_quantity>0 for x in obj.items.all()): messages.error(request,'Teslimat veya aktif rezerv bulunan bağlantı iptal edilemez.')
    else: obj.status=ConnectionSale.Status.CANCELLED;obj.save(update_fields=['status','updated_at']);audit(request,'CANCEL',obj);messages.success(request,'Bağlantı iptal edildi.')
    return redirect('connection_detail',pk)

@manage_required
def adjustment_create(request,item_pk):
    item=get_object_or_404(ConnectionItem.objects.select_related('connection__customer','product'),pk=item_pk)
    adjustment=BalanceAdjustment(connection_item=item,created_by=request.user,approved_by=request.user)
    form=BalanceAdjustmentForm(request.POST or None,instance=adjustment)
    if form.is_valid():
        try:
            with transaction.atomic():
                locked_item=ConnectionItem.objects.select_for_update().get(pk=item.pk)
                obj=form.save(commit=False);obj.connection_item=locked_item;obj.created_by=request.user;obj.approved_by=request.user;obj.full_clean();obj.save()
            audit(request,'ADJUST',obj,{'quantity':str(obj.signed_quantity)});locked_item.connection.refresh_status();messages.success(request,'Bakiye düzeltme hareketi kaydedildi.');return redirect('connection_detail',item.connection_id)
        except ValidationError as exc: messages.error(request,' '.join(exc.messages))
    return render(request,'operations/form.html',{'form':form,'title':'Bakiye Düzeltmesi','subtitle':f'{item.product.name} / Fatura {item.connection.invoice_no}','cancel_url':'connection_detail','cancel_args':[item.connection_id]})

@order_access_required
def order_list(request):
    qs=visible_orders(request)
    q=request.GET.get('q','').strip()
    status=request.GET.get('status','')
    if q:
        qs=qs.filter(Q(number__icontains=q)|Q(customer__name__icontains=q))
    if status:
        qs=qs.filter(status=status)
    return render(request,'operations/order_list.html',{'page_obj':page(request,qs),'q':q,'status':status,'statuses':Order.Status.choices})

@role_required(UserProfile.Role.ADMIN,UserProfile.Role.MANAGEMENT,UserProfile.Role.SALES)
def order_create(request):
    customers=visible_customers(request).filter(is_active=True); customer_id=request.POST.get('customer') or request.GET.get('customer');customer=None;available_items=[]
    if customer_id:
        customer=get_object_or_404(customers,pk=customer_id)
        candidates=ConnectionItem.objects.select_related('connection','product').filter(connection__customer=customer,connection__status__in=[ConnectionSale.Status.ACTIVE,ConnectionSale.Status.PARTIAL]).order_by('product__name','connection__invoice_date')
        available_items=[i for i in candidates if i.available_quantity>0]
    form=OrderHeaderForm(request.POST or None)
    if request.method=='POST' and customer and form.is_valid():
        quantities={k[4:]:v for k,v in request.POST.items() if k.startswith('qty_')}
        try:
            order=create_order_from_request(customer=customer,user=request.user,order_data=form.cleaned_data,quantities=quantities);audit(request,'CREATE',order);messages.success(request,'Sipariş oluşturuldu.');return redirect('order_detail',order.pk)
        except ValidationError as exc: messages.error(request,' '.join(exc.messages))
    return render(request,'operations/order_form.html',{'form':form,'customers':customers,'customer':customer,'available_items':available_items})

@order_access_required
def order_detail(request,pk):
    obj=get_object_or_404(visible_orders(request),pk=pk)
    items=list(obj.items.select_related('connection_item__product','connection_item__connection'))
    shipments=obj.shipments.filter(pk__in=visible_shipments(request).values('pk'))
    has_active_shipments=shipments.exclude(status=Shipment.Status.CANCELLED).exists()
    can_manage=is_manager(request.user)
    can_ship=has_role(request.user,ADMIN,MANAGEMENT,WAREHOUSE) and obj.status in {
        Order.Status.APPROVED,Order.Status.PREPARING,Order.Status.PARTIAL,
    } and any(item.allocatable_quantity>0 for item in items)
    can_approve=can_manage and obj.status in {Order.Status.DRAFT,Order.Status.PENDING}
    can_cancel=can_manage and obj.status not in {Order.Status.COMPLETED,Order.Status.CANCELLED} and obj.total_delivered==0 and not has_active_shipments
    return render(request,'operations/order_detail.html',{
        'order':obj,
        'items':items,
        'shipments':shipments,
        'can_approve_order':can_approve,
        'can_create_shipment':can_ship,
        'can_cancel_order':can_cancel,
    })

@manage_required
@require_POST
def order_approve(request,pk):
    obj=get_object_or_404(Order,pk=pk)
    if obj.status not in [Order.Status.DRAFT,Order.Status.PENDING]:messages.error(request,'Bu sipariş onaylanamaz.')
    else: obj.status=Order.Status.APPROVED;obj.approved_by=request.user;obj.approved_at=timezone.now();obj.save(update_fields=['status','approved_by','approved_at','updated_at']);audit(request,'APPROVE',obj);messages.success(request,'Sipariş onaylandı.')
    return redirect('order_detail',pk)

@manage_required
@require_POST
def order_cancel(request,pk):
    obj=get_object_or_404(Order,pk=pk)
    if obj.total_delivered>0:messages.error(request,'Teslimat yapılmış sipariş iptal edilemez.')
    elif obj.shipments.exclude(status=Shipment.Status.CANCELLED).exists():messages.error(request,'Siparişe bağlı aktif sevkiyatlar var. Önce sevkiyatları iptal edin.')
    else: obj.status=Order.Status.CANCELLED;obj.save(update_fields=['status','updated_at']);audit(request,'CANCEL',obj);messages.success(request,'Sipariş iptal edildi ve rezervler serbest bırakıldı.')
    return redirect('order_detail',pk)

@order_access_required
def order_pdf_view(request,pk):
    obj=get_object_or_404(visible_orders(request),pk=pk)
    return attachment_response(order_pdf(obj),f'{obj.number}.pdf','application/pdf')

@shipment_access_required
def shipment_list(request):
    qs=visible_shipments(request)
    q=request.GET.get('q','').strip()
    status=request.GET.get('status','')
    if q:
        qs=qs.filter(Q(number__icontains=q)|Q(order__number__icontains=q)|Q(customer__name__icontains=q)|Q(vehicle_plate__icontains=q))
    if status:
        qs=qs.filter(status=status)
    return render(request,'operations/shipment_list.html',{'page_obj':page(request,qs),'q':q,'status':status,'statuses':Shipment.Status.choices})

@role_required(ADMIN,MANAGEMENT,WAREHOUSE)
def shipment_create(request,order_pk):
    order=get_object_or_404(visible_orders(request),pk=order_pk)
    if order.status not in [Order.Status.APPROVED,Order.Status.PREPARING,Order.Status.PARTIAL]:
        messages.error(request,'Sevkiyat için sipariş onaylanmış olmalıdır.')
        return redirect('order_detail',order.pk)
    obj=Shipment(order=order,customer=order.customer,created_by=request.user,delivery_address=order.delivery_address)
    form=ShipmentForm(request.POST or None,request.FILES or None,instance=obj)
    remaining_items=[i for i in order.items.select_related('connection_item__product','connection_item__connection') if i.allocatable_quantity>0]
    if request.method=='POST' and form.is_valid():
        lines=[]
        try:
            for oi in remaining_items:
                quantity=parse_quantity(request.POST.get(f'quantity_{oi.pk}'),f'{oi.connection_item.product.name} bu sevkte verilecek miktar')
                if quantity>0:
                    if quantity>oi.allocatable_quantity:
                        raise ValidationError(f'{oi.connection_item.product.name}: bu sevkte verilecek miktar siparişte kalan miktarı aşıyor.')
                    lines.append((oi,quantity))
            if not lines:
                raise ValidationError('En az bir ürün için bu sevkte verilecek miktarı girin.')
            with transaction.atomic():
                locked_order=Order.objects.select_for_update().get(pk=order.pk)
                shipment=form.save(commit=False)
                shipment.number=next_document_number('shipment')
                shipment.order=locked_order
                shipment.customer=locked_order.customer
                shipment.created_by=request.user
                shipment.status=Shipment.Status.DRAFT
                shipment.save()
                if locked_order.status==Order.Status.APPROVED:
                    locked_order.status=Order.Status.PREPARING
                    locked_order.save(update_fields=['status','updated_at'])
                for oi,quantity in lines:
                    locked_oi=OrderItem.objects.select_for_update().get(pk=oi.pk)
                    if quantity>locked_oi.allocatable_quantity:
                        raise ValidationError(f'{locked_oi.connection_item.product.name}: başka bir sevkiyat nedeniyle kullanılabilir miktar değişti.')
                    ShipmentItem.objects.create(shipment=shipment,order_item=locked_oi,connection_item=locked_oi.connection_item,quantity_delivered=quantity)
            audit(request,'CREATE',shipment)
            messages.success(request,'Sevk taslağı oluşturuldu. Miktar, yalnızca teslimat kesinleştiğinde ilgili faturadan düşecektir.')
            return redirect('shipment_detail',shipment.pk)
        except ValidationError as exc:
            messages.error(request,' '.join(exc.messages))
    shipment_rows=[{'order_item':i,'max_quantity':i.allocatable_quantity,'quantity':i.allocatable_quantity} for i in remaining_items]
    return render(request,'operations/shipment_form.html',{'form':form,'order':order,'shipment_rows':shipment_rows,'edit_mode':False})

@role_required(ADMIN,MANAGEMENT,WAREHOUSE)
def shipment_edit(request,pk):
    shipment=get_object_or_404(visible_shipments(request),pk=pk)
    if shipment.status in [Shipment.Status.DELIVERED,Shipment.Status.CANCELLED]:
        messages.error(request,'Teslim edilmiş veya iptal edilmiş sevkiyat düzenlenemez.')
        return redirect('shipment_detail',pk)
    form=ShipmentForm(request.POST or None,request.FILES or None,instance=shipment)
    lines=list(shipment.items.select_related('order_item__connection_item__product','connection_item__connection'))
    if request.method=='POST' and form.is_valid():
        try:
            with transaction.atomic():
                shipment=form.save()
                for existing_line in lines:
                    line=ShipmentItem.objects.select_for_update().select_related('order_item__connection_item__product').get(pk=existing_line.pk)
                    locked_order_item=OrderItem.objects.select_for_update().get(pk=line.order_item_id)
                    quantity=parse_quantity(request.POST.get(f'quantity_{line.order_item_id}'),f'{line.connection_item.product.name} bu sevkte verilecek miktar')
                    other_open=locked_order_item.shipment_items.exclude(shipment=shipment).exclude(shipment__status__in=[Shipment.Status.DELIVERED,Shipment.Status.CANCELLED]).aggregate(v=Sum('quantity_delivered'))['v'] or 0
                    max_allowed=max(locked_order_item.remaining_quantity-other_open,0)
                    if quantity<=0:
                        raise ValidationError(f'{line.connection_item.product.name}: bu sevkte verilecek miktar sıfırdan büyük olmalıdır.')
                    if quantity>max_allowed:
                        raise ValidationError(f'{line.connection_item.product.name}: bu sevkte verilecek miktar siparişte kalan miktarı aşıyor.')
                    line.quantity_delivered=quantity
                    line.save(update_fields=['quantity_delivered','updated_at'])
            audit(request,'UPDATE',shipment)
            messages.success(request,'Sevkiyat taslağı güncellendi.')
            return redirect('shipment_detail',pk)
        except ValidationError as exc:
            messages.error(request,' '.join(exc.messages))
    shipment_rows=[]
    for x in lines:
        other_open=x.order_item.shipment_items.exclude(shipment=shipment).exclude(shipment__status__in=[Shipment.Status.DELIVERED,Shipment.Status.CANCELLED]).aggregate(v=Sum('quantity_delivered'))['v'] or 0
        shipment_rows.append({'order_item':x.order_item,'max_quantity':max(x.order_item.remaining_quantity-other_open,0),'quantity':x.quantity_delivered})
    return render(request,'operations/shipment_form.html',{'form':form,'order':shipment.order,'shipment_rows':shipment_rows,'edit_mode':True,'shipment':shipment})

@shipment_access_required
def shipment_detail(request,pk):
    obj=get_object_or_404(visible_shipments(request),pk=pk)
    terminal=obj.status in {Shipment.Status.DELIVERED,Shipment.Status.CANCELLED}
    can_warehouse_action=has_role(request.user,ADMIN,MANAGEMENT,WAREHOUSE)
    can_dispatch_action=has_role(request.user,ADMIN,MANAGEMENT,DISPATCH)
    context={
        'shipment':obj,
        'items':obj.items.select_related('connection_item__product','connection_item__connection','order_item'),
        'can_edit_shipment':can_warehouse_action and not terminal,
        'can_mark_preparing':can_warehouse_action and obj.status==Shipment.Status.DRAFT,
        'can_mark_loaded':can_warehouse_action and obj.status==Shipment.Status.PREPARING,
        'can_mark_on_route':can_dispatch_action and obj.status==Shipment.Status.LOADED,
        'can_deliver_shipment':can_dispatch_action and obj.status in {Shipment.Status.LOADED,Shipment.Status.ON_ROUTE},
        'can_cancel_shipment':is_manager(request.user) and not terminal,
    }
    return render(request,'operations/shipment_detail.html',context)

@role_required(ADMIN,MANAGEMENT,WAREHOUSE,DISPATCH)
@require_POST
def shipment_status(request,pk,status):
    obj=get_object_or_404(visible_shipments(request),pk=pk)
    role=get_role(request.user)
    transitions={
        Shipment.Status.DRAFT:Shipment.Status.PREPARING,
        Shipment.Status.PREPARING:Shipment.Status.LOADED,
        Shipment.Status.LOADED:Shipment.Status.ON_ROUTE,
    }
    expected=transitions.get(obj.status)
    if obj.status in {Shipment.Status.DELIVERED,Shipment.Status.CANCELLED} or status!=expected:
        messages.error(request,'Geçersiz veya sırası gelmemiş durum değişikliği.')
    elif status in {Shipment.Status.PREPARING,Shipment.Status.LOADED} and role not in {ADMIN,MANAGEMENT,WAREHOUSE} and not request.user.is_superuser:
        messages.error(request,'Bu aşama yalnızca depo veya yönetim tarafından tamamlanabilir.')
    elif status==Shipment.Status.LOADED and not obj.assigned_dispatcher_id:
        messages.error(request,'Sevkiyat personeli atanmadan sevkiyat Yüklendi durumuna geçirilemez.')
    elif status==Shipment.Status.ON_ROUTE and role not in {ADMIN,MANAGEMENT,DISPATCH} and not request.user.is_superuser:
        messages.error(request,'Sevkiyatı yola çıkarma yetkiniz bulunmuyor.')
    else:
        obj.status=status
        obj.save(update_fields=['status','updated_at'])
        audit(request,'STATUS',obj,{'status':status})
        messages.success(request,'Sevkiyat durumu güncellendi.')
    return redirect('shipment_detail',pk)

@role_required(ADMIN,MANAGEMENT,DISPATCH)
def shipment_deliver(request,pk):
    obj=get_object_or_404(visible_shipments(request),pk=pk)
    if obj.status not in {Shipment.Status.LOADED,Shipment.Status.ON_ROUTE}:
        messages.error(request,'Teslimat yalnızca yüklenmiş veya yolda durumundaki sevkiyat için kesinleştirilebilir.')
        return redirect('shipment_detail',pk)
    form=ShipmentDeliveryForm(request.POST or None,request.FILES or None,instance=obj)
    if request.method=='POST' and form.is_valid():
        try:
            with transaction.atomic():
                shipment=form.save(commit=False)
                shipment.save(update_fields=['delivery_date','delivered_to','receiver_signature','delivery_proof','delivery_notes','updated_at'])
                deliver_shipment(shipment=shipment,user=request.user)
            audit(request,'DELIVER',obj,{
                'delivered_to':shipment.delivered_to,
                'signature_photo':bool(shipment.receiver_signature),
                'delivery_photo':bool(shipment.delivery_proof),
            })
            messages.success(request,'Teslimat fotoğraflarıyla birlikte kesinleştirildi; ilgili fatura bakiyeleri düşürüldü.')
            return redirect('shipment_detail',pk)
        except ValidationError as exc:
            messages.error(request,' '.join(exc.messages))
    return render(request,'operations/shipment_delivery_form.html',{
        'form':form,
        'shipment':obj,
        'items':obj.items.select_related('connection_item__product','connection_item__connection'),
    })

@manage_required
@require_POST
def shipment_cancel(request,pk):
    obj=get_object_or_404(Shipment.objects.select_related('order'),pk=pk)
    if obj.status==Shipment.Status.DELIVERED:
        messages.error(request,'Teslim edilmiş sevkiyat silinemez veya iptal edilemez. Ters/düzeltme hareketi oluşturulmalıdır.')
    else:
        obj.status=Shipment.Status.CANCELLED
        obj.save(update_fields=['status','updated_at'])
        order=obj.order
        if order.total_delivered == 0 and not order.shipments.exclude(status=Shipment.Status.CANCELLED).exists():
            order.status=Order.Status.APPROVED if order.approved_at else Order.Status.PENDING
            order.save(update_fields=['status','updated_at'])
        audit(request,'CANCEL',obj)
        messages.success(request,'Sevkiyat iptal edildi.')
    return redirect('shipment_detail',pk)

@shipment_access_required
def shipment_pdf_view(request,pk):
    obj=get_object_or_404(visible_shipments(request),pk=pk)
    verify_url=request.build_absolute_uri(f'/verify/{obj.verification_token}/')
    return attachment_response(shipment_pdf(obj,verify_url),f'{obj.number}.pdf','application/pdf')

def verify_shipment(request,token):
    obj=get_object_or_404(Shipment.objects.select_related('customer','order'),verification_token=token)
    return render(request,'operations/verify.html',{'shipment':obj})

@report_access_required
def report_center(request):
    role=get_role(request.user)
    customers=visible_customers(request)
    if role==WAREHOUSE:
        customer_ids=visible_orders(request).values_list('customer_id',flat=True)
        customers=Customer.objects.filter(pk__in=customer_ids)
    product_summary=[]
    for product in Product.objects.filter(is_active=True):
        items=product.connection_items.filter(connection__customer__in=customers).exclude(connection__status=ConnectionSale.Status.CANCELLED)
        remaining=sum((i.remaining_quantity for i in items),0)
        reserved=sum((i.reserved_quantity for i in items),0)
        if remaining>0:
            product_summary.append({'product':product,'remaining':remaining,'reserved':reserved,'available':remaining-reserved})
    product_summary=sorted(product_summary,key=lambda x:x['remaining'],reverse=True)[:50]
    return render(request,'operations/reports.html',{
        'product_summary':product_summary,
        'open_orders':visible_orders(request).exclude(status__in=[Order.Status.COMPLETED,Order.Status.CANCELLED]).select_related('customer')[:20],
    })

@manage_required
def data_import(request,kind):
    if kind not in {'products','customers'}:raise Http404
    form=ExcelUploadForm(request.POST or None,request.FILES or None)
    if form.is_valid():
        fn=import_products if kind=='products' else import_customers
        created,updated,errors=fn(form.cleaned_data['file']);messages.success(request,f'{created} yeni, {updated} güncellenen kayıt.')
        for error in errors[:15]:messages.warning(request,error)
        audit(request,'IMPORT',CompanySettings.get_solo(),{'kind':kind,'created':created,'updated':updated,'errors':len(errors)})
        return redirect('product_list' if kind=='products' else 'customer_list')
    return render(request,'operations/import.html',{'form':form,'kind':kind})

@manage_required
def download_template(request,kind):
    data=product_template() if kind=='products' else customer_template();return attachment_response(data,f'{kind}_sablon.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@login_required
def data_export(request,kind):
    role=get_role(request.user)
    if kind=='products':
        if role not in {ADMIN,MANAGEMENT,WAREHOUSE} and not request.user.is_superuser:
            messages.error(request,'Ürün Excel çıktısı için yetkiniz bulunmuyor.')
            return redirect('dashboard')
        data,name=export_products(),'urunler.xlsx'
    elif kind=='customers':
        if role not in {ADMIN,MANAGEMENT,SALES} and not request.user.is_superuser:
            messages.error(request,'Müşteri Excel çıktısı için yetkiniz bulunmuyor.')
            return redirect('dashboard')
        data,name=export_customers(visible_customers(request)),'musteriler.xlsx'
    elif kind=='balances':
        if role not in {ADMIN,MANAGEMENT,SALES} and not request.user.is_superuser:
            messages.error(request,'Bakiye Excel çıktısı için yetkiniz bulunmuyor.')
            return redirect('dashboard')
        lines=ConnectionItem.objects.select_related('connection__customer','product').filter(connection__customer__in=visible_customers(request)).exclude(connection__status=ConnectionSale.Status.CANCELLED)
        data,name=export_balances(lines),'baglanti_bakiyeleri.xlsx'
    else:
        raise Http404
    return attachment_response(data,name,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@admin_required
def company_settings(request):
    obj=CompanySettings.get_solo();form=CompanySettingsForm(request.POST or None,request.FILES or None,instance=obj)
    if form.is_valid():obj=form.save();audit(request,'UPDATE',obj);messages.success(request,'Şirket ayarları kaydedildi.');return redirect('company_settings')
    return render(request,'operations/form.html',{'form':form,'title':'Şirket Ayarları','cancel_url':'dashboard'})

@manage_required
def warehouse_list(request):
    form=WarehouseForm(request.POST or None)
    if form.is_valid():obj=form.save();audit(request,'CREATE',obj);messages.success(request,'Depo eklendi.');return redirect('warehouse_list')
    return render(request,'operations/warehouses.html',{'form':form,'warehouses':Warehouse.objects.all()})


@manage_required
def warehouse_edit(request, pk):
    obj = get_object_or_404(Warehouse, pk=pk)
    form = WarehouseForm(request.POST or None, instance=obj)

    if form.is_valid():
        obj = form.save()
        audit(request, 'UPDATE', obj)
        messages.success(request, 'Depo bilgileri güncellendi.')
        return redirect('warehouse_list')

    return render(
        request,
        'operations/form.html',
        {
            'form': form,
            'title': 'Depoyu Düzenle',
            'subtitle': obj.name,
            'cancel_url': 'warehouse_list',
        },
    )


@manage_required
@require_POST
def warehouse_toggle(request, pk):
    obj = get_object_or_404(Warehouse, pk=pk)
    obj.is_active = not obj.is_active
    obj.save(update_fields=['is_active', 'updated_at'])

    audit(
        request,
        'STATUS',
        obj,
        {'is_active': obj.is_active},
    )
    messages.success(request, 'Depo durumu güncellendi.')
    return redirect('warehouse_list')

@admin_required
def transport_settings(request):
    vehicle_form = VehicleForm(request.POST or None)

    if vehicle_form.is_valid():
        obj = vehicle_form.save()
        audit(request, 'CREATE', obj)
        messages.success(request, 'Araç kaydedildi.')
        return redirect('transport_settings')

    return render(
        request,
        'operations/transport_settings.html',
        {
            'vehicle_form': vehicle_form,
            'vehicles': Vehicle.objects.all(),
        },
    )


@admin_required
def vehicle_edit(request, pk):
    obj = get_object_or_404(Vehicle, pk=pk)
    form = VehicleForm(request.POST or None, instance=obj)

    if form.is_valid():
        obj = form.save()
        audit(request, 'UPDATE', obj)
        messages.success(request, 'Araç bilgileri güncellendi.')
        return redirect('transport_settings')

    return render(
        request,
        'operations/form.html',
        {
            'form': form,
            'title': 'Aracı Düzenle',
            'subtitle': obj.plate,
            'cancel_url': 'transport_settings',
        },
    )


@admin_required
@require_POST
def transport_toggle(request, kind, pk):
    if kind != 'vehicle':
        raise Http404

    obj = get_object_or_404(Vehicle, pk=pk)
    obj.is_active = not obj.is_active
    obj.save(update_fields=['is_active', 'updated_at'])

    audit(
        request,
        'STATUS',
        obj,
        {'is_active': obj.is_active},
    )
    messages.success(request, 'Araç durumu güncellendi.')
    return redirect('transport_settings')


@admin_required
def user_list(request):return render(request,'operations/users.html',{'users':User.objects.select_related('profile').order_by('username')})

@admin_required
def user_create(request):
    form=UserCreateForm(request.POST or None)
    if form.is_valid():obj=form.save();audit(request,'CREATE',obj);messages.success(request,'Kullanıcı oluşturuldu.');return redirect('user_list')
    return render(request,'operations/form.html',{'form':form,'title':'Yeni Kullanıcı','cancel_url':'user_list'})

@admin_required
def user_edit(request,pk):
    obj=get_object_or_404(User,pk=pk);form=UserEditForm(request.POST or None,instance=obj)
    if form.is_valid():obj=form.save();audit(request,'UPDATE',obj);messages.success(request,'Kullanıcı güncellendi.');return redirect('user_list')
    return render(request,'operations/form.html',{'form':form,'title':'Kullanıcıyı Düzenle','cancel_url':'user_list'})

@audit_access_required
def audit_list(request):
    qs=AuditLog.objects.select_related('user')
    if not is_manager(request.user):
        qs=qs.filter(user=request.user)
    q=request.GET.get('q','').strip()
    if q:
        qs=qs.filter(Q(object_repr__icontains=q)|Q(action__icontains=q)|Q(user__username__icontains=q))
    return render(request,'operations/audit.html',{'page_obj':page(request,qs,20),'q':q,'own_only':not is_manager(request.user)})

@admin_required
def backup_download(request):
    buf=BytesIO()
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
        db=Path(settings.DATABASES['default']['NAME'])
        if db.exists():z.write(db,'db.sqlite3')
        media=Path(settings.MEDIA_ROOT)
        if media.exists():
            for path in media.rglob('*'):
                if path.is_file():z.write(path,f'media/{path.relative_to(media)}')
        env=Path(settings.BASE_DIR/'.env')
        if env.exists():z.write(env,'.env')
    buf.seek(0);audit(request,'BACKUP',CompanySettings.get_solo());return attachment_response(buf.getvalue(),f'aeco_yedek_{timezone.localdate():%Y%m%d}.zip','application/zip')
