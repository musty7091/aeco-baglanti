from functools import wraps

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

from .models import Customer, Order, Shipment, UserProfile


ADMIN = UserProfile.Role.ADMIN
MANAGEMENT = UserProfile.Role.MANAGEMENT
SALES = UserProfile.Role.SALES
WAREHOUSE = UserProfile.Role.WAREHOUSE
DISPATCH = UserProfile.Role.DISPATCH

MANAGER_ROLES = {ADMIN, MANAGEMENT}
CUSTOMER_ROLES = {ADMIN, MANAGEMENT, SALES}
ORDER_ROLES = {ADMIN, MANAGEMENT, SALES, WAREHOUSE}
SHIPMENT_ROLES = {ADMIN, MANAGEMENT, SALES, WAREHOUSE, DISPATCH}
PRODUCT_ROLES = {ADMIN, MANAGEMENT, SALES, WAREHOUSE}
REPORT_ROLES = {ADMIN, MANAGEMENT, SALES, WAREHOUSE}


def get_profile(user):
    if not getattr(user, 'is_authenticated', False):
        return None
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile


def get_role(user):
    if getattr(user, 'is_superuser', False):
        return ADMIN
    profile = get_profile(user)
    if not profile or not profile.active or not user.is_active:
        return None
    return profile.role


def has_role(user, *roles):
    if not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_superuser', False):
        return True
    profile = get_profile(user)
    return bool(profile and profile.active and user.is_active and profile.role in roles)


def is_manager(user):
    return has_role(user, ADMIN, MANAGEMENT)


def role_required(*roles):
    def decorator(view_func):
        @login_required
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if has_role(request.user, *roles):
                return view_func(request, *args, **kwargs)
            if get_role(request.user) is None:
                logout(request)
                messages.error(request, 'Kullanıcı hesabınız pasif veya yetkisiz durumda.')
                return redirect('login')
            messages.error(request, 'Bu ekran veya işlem için yetkiniz bulunmuyor.')
            return redirect('dashboard')
        return wrapper
    return decorator


manage_required = role_required(ADMIN, MANAGEMENT)
admin_required = role_required(ADMIN)
customer_access_required = role_required(ADMIN, MANAGEMENT, SALES)
order_access_required = role_required(ADMIN, MANAGEMENT, SALES, WAREHOUSE)
shipment_access_required = role_required(ADMIN, MANAGEMENT, SALES, WAREHOUSE, DISPATCH)
product_access_required = role_required(ADMIN, MANAGEMENT, SALES, WAREHOUSE)
report_access_required = role_required(ADMIN, MANAGEMENT, SALES, WAREHOUSE)
audit_access_required = role_required(ADMIN, MANAGEMENT, SALES, WAREHOUSE, DISPATCH)


def customers_for_user(user):
    qs = Customer.objects.all()
    if getattr(user, 'is_superuser', False) or has_role(user, ADMIN, MANAGEMENT):
        return qs
    if has_role(user, SALES):
        # Satış temsilcisi yalnızca açıkça kendisine atanmış müşterileri görür.
        return qs.filter(assigned_salesperson=user)
    return qs.none()


def orders_for_user(user):
    qs = Order.objects.select_related('customer', 'created_by', 'approved_by')
    if getattr(user, 'is_superuser', False) or has_role(user, ADMIN, MANAGEMENT):
        return qs
    if has_role(user, SALES):
        return qs.filter(customer__assigned_salesperson=user)
    if has_role(user, WAREHOUSE):
        # Depo yalnızca onay sürecini geçmiş operasyonel siparişleri görür.
        return qs.filter(status__in=[
            Order.Status.APPROVED,
            Order.Status.PREPARING,
            Order.Status.PARTIAL,
            Order.Status.COMPLETED,
            Order.Status.CANCELLED,
        ])
    if has_role(user, DISPATCH):
        return qs.filter(shipments__in=shipments_for_user(user)).distinct()
    return qs.none()


def shipments_for_user(user):
    qs = Shipment.objects.select_related(
        'customer', 'order', 'warehouse', 'created_by', 'delivered_by',
        'assigned_dispatcher',
    )
    if getattr(user, 'is_superuser', False) or has_role(user, ADMIN, MANAGEMENT):
        return qs
    if has_role(user, SALES):
        return qs.filter(customer__assigned_salesperson=user)
    if has_role(user, WAREHOUSE):
        return qs
    if has_role(user, DISPATCH):
        # Sevkiyatlar personele atanmaz; sevkiyat personeli tüm sevkiyatları görür ve teslim eder.
        return qs
    return qs.none()


def customer_allowed(user, customer):
    return customers_for_user(user).filter(pk=customer.pk).exists()


def order_allowed(user, order):
    return orders_for_user(user).filter(pk=order.pk).exists()


def shipment_allowed(user, shipment):
    return shipments_for_user(user).filter(pk=shipment.pk).exists()


def access_flags(user):
    role = get_role(user)
    manager = getattr(user, 'is_superuser', False) or role in MANAGER_ROLES
    admin = getattr(user, 'is_superuser', False) or role == ADMIN
    return {
        'role': role,
        'is_admin': admin,
        'is_manager': manager,
        'is_sales': role == SALES,
        'is_warehouse': role == WAREHOUSE,
        'is_dispatch': role == DISPATCH,
        'can_view_customers': role in CUSTOMER_ROLES or getattr(user, 'is_superuser', False),
        'can_manage_customers': manager,
        'can_view_connections': role in CUSTOMER_ROLES or getattr(user, 'is_superuser', False),
        'can_manage_connections': manager,
        'can_view_orders': role in ORDER_ROLES or getattr(user, 'is_superuser', False),
        'can_create_orders': role in {ADMIN, MANAGEMENT, SALES} or getattr(user, 'is_superuser', False),
        'can_approve_orders': manager,
        'can_view_shipments': role in SHIPMENT_ROLES or getattr(user, 'is_superuser', False),
        'can_create_shipments': role in {ADMIN, MANAGEMENT, WAREHOUSE} or getattr(user, 'is_superuser', False),
        'can_deliver_shipments': role in {ADMIN, MANAGEMENT, DISPATCH} or getattr(user, 'is_superuser', False),
        'can_view_products': role in PRODUCT_ROLES or getattr(user, 'is_superuser', False),
        'can_manage_products': manager,
        'can_view_reports': role in REPORT_ROLES or getattr(user, 'is_superuser', False),
        'can_view_audit': role in {ADMIN, MANAGEMENT, SALES, WAREHOUSE, DISPATCH} or getattr(user, 'is_superuser', False),
        'can_view_all_audit': manager,
        'can_export_customers': role in {ADMIN, MANAGEMENT, SALES} or getattr(user, 'is_superuser', False),
        'can_export_balances': role in {ADMIN, MANAGEMENT, SALES} or getattr(user, 'is_superuser', False),
        'can_export_products': role in {ADMIN, MANAGEMENT, WAREHOUSE} or getattr(user, 'is_superuser', False),
        'can_manage_system': admin,
    }
