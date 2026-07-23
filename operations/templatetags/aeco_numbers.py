from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from django import template

register = template.Library()


@register.filter
def adet(value):
    """Tam sayı miktarları Türkçe binlik ayırıcıyla gösterir: 1770 -> 1.770."""
    try:
        number = Decimal(str(value or 0))
        return f'{int(number):,}'.replace(',', '.')
    except (InvalidOperation, TypeError, ValueError):
        return value


@register.filter
def para(value):
    """Parasal değerleri Türkçe biçimde gösterir: 1234.5 -> 1.234,50."""
    try:
        number = Decimal(str(value or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        whole, fraction = f'{number:.2f}'.split('.')
        whole = f'{int(whole):,}'.replace(',', '.')
        return f'{whole},{fraction}'
    except (InvalidOperation, TypeError, ValueError):
        return value


@register.filter
def oran(value):
    """KDV oranını gereksiz sıfırlar olmadan gösterir."""
    try:
        number = Decimal(str(value or 0)).normalize()
        return format(number, 'f')
    except (InvalidOperation, TypeError, ValueError):
        return value
