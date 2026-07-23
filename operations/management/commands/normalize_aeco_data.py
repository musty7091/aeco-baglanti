from django.core.management.base import BaseCommand
from operations.models import ConnectionItem, Product


class Command(BaseCommand):
    help = 'Ürün ve bağlantı kalemlerini adet, fiyat ve KDV yapısına göre normalleştirir.'

    def handle(self, *args, **options):
        products = Product.objects.exclude(base_unit=Product.Unit.PIECE).update(base_unit=Product.Unit.PIECE)
        Product.objects.exclude(units_per_case=1).update(units_per_case=1)
        Product.objects.exclude(category='').update(category='')
        items = ConnectionItem.objects.exclude(unit=Product.Unit.PIECE).update(unit=Product.Unit.PIECE)
        missing_prices = ConnectionItem.objects.filter(unit_price__isnull=True).update(unit_price=0)
        self.stdout.write(self.style.SUCCESS(
            f'Adet/fiyat yapısı normalleştirildi. Güncellenen ürün: {products}, '
            f'bağlantı kalemi: {items}, fiyatı sıfırlanan eski kalem: {missing_prices}'
        ))
