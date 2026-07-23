from django.contrib import admin
from .models import *


class ConnectionItemInline(admin.TabularInline):
    model = ConnectionItem
    extra = 0
    fields = ('product', 'quantity', 'unit_price', 'discount_rate', 'vat_rate')


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0


class ShipmentItemInline(admin.TabularInline):
    model = ShipmentItem
    extra = 0


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'contact_name', 'phone', 'assigned_salesperson', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('code', 'name', 'contact_name', 'phone', 'email')
    customer_fields = (
        'name', 'contact_name', 'phone', 'email',
        'assigned_salesperson', 'notes', 'is_active',
    )

    def get_fields(self, request, obj=None):
        return (('code',) + self.customer_fields) if obj else self.customer_fields

    def get_readonly_fields(self, request, obj=None):
        return ('code',) if obj else ()


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('barcode', 'name', 'brand', 'volume', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('barcode', 'name', 'brand')
    fields = ('barcode', 'name', 'brand', 'volume', 'is_active')


@admin.register(ConnectionSale)
class ConnectionSaleAdmin(admin.ModelAdmin):
    list_display = ('number', 'customer', 'invoice_no', 'invoice_date', 'status')
    list_filter = ('status', 'invoice_date')
    search_fields = ('number', 'invoice_no', 'customer__name')
    inlines = [ConnectionItemInline]


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('number', 'customer', 'order_date', 'status')
    list_filter = ('status', 'order_date')
    search_fields = ('number', 'customer__name')
    inlines = [OrderItemInline]


@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = ('number', 'customer', 'shipment_date', 'status', 'vehicle_plate')
    list_filter = ('status', 'shipment_date')
    search_fields = ('number', 'customer__name')
    inlines = [ShipmentItemInline]


for model in [CompanySettings, UserProfile, Warehouse, Vehicle, BalanceAdjustment, AuditLog, DocumentCounter]:
    admin.site.register(model)

admin.site.site_header = 'AECO Bağlantılı Satış Yönetimi'
admin.site.site_title = 'AECO Yönetim'
