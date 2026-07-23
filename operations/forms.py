from pathlib import Path
from io import BytesIO
from django import forms
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.forms import BaseInlineFormSet, inlineformset_factory
from django.db.models import Q
from django.utils import timezone
from PIL import Image, ImageOps

from .models import (
    BalanceAdjustment,
    CompanySettings,
    ConnectionItem,
    ConnectionSale,
    Customer,
    Order,
    Product,
    Shipment,
    UserProfile,
    Vehicle,
    Warehouse,
)


class StyledFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = 'form-control'
            if isinstance(field.widget, forms.CheckboxInput):
                css = 'form-check-input'
            field.widget.attrs['class'] = f"{field.widget.attrs.get('class', '')} {css}".strip()
            if not isinstance(field.widget, (forms.CheckboxInput, forms.FileInput)):
                field.widget.attrs.setdefault('placeholder', field.label)


class DateInput(forms.DateInput):
    input_type = 'date'


class IntegerQuantityInput(forms.NumberInput):
    input_type = 'number'

    def __init__(self, *args, **kwargs):
        attrs = kwargs.setdefault('attrs', {})
        attrs.setdefault('min', '0')
        attrs.setdefault('step', '1')
        attrs.setdefault('inputmode', 'numeric')
        super().__init__(*args, **kwargs)


class ProductChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f'{obj.barcode} — {obj.name}'


class CustomerForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Customer
        fields = [
            'name', 'contact_name', 'phone', 'email',
            'assigned_salesperson', 'notes', 'is_active',
        ]
        labels = {
            'name': 'Ticari unvan',
            'contact_name': 'Yetkili kişi',
            'phone': 'Telefon',
            'email': 'E-posta',
            'assigned_salesperson': 'Satış temsilcisi',
            'notes': 'Notlar',
            'is_active': 'Aktif',
        }
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        sales_qs = User.objects.filter(
            is_active=True,
            profile__active=True,
            profile__role=UserProfile.Role.SALES,
        ).order_by('first_name', 'last_name', 'username')
        current_id = getattr(self.instance, 'assigned_salesperson_id', None)
        if current_id:
            sales_qs = User.objects.filter(
                Q(pk=current_id) | Q(pk__in=sales_qs.values('pk'))
            ).distinct().order_by('first_name', 'last_name', 'username')
        self.fields['assigned_salesperson'].queryset = sales_qs
        self.fields['assigned_salesperson'].empty_label = 'Satış temsilcisi seçiniz'


class ProductForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Product
        fields = ['barcode', 'name', 'brand', 'volume', 'is_active']
        labels = {
            'barcode': 'Barkod',
            'name': 'Ürün adı',
            'brand': 'Marka',
            'volume': 'Hacim',
            'is_active': 'Aktif',
        }
        widgets = {
            'barcode': forms.TextInput(attrs={'inputmode': 'numeric', 'autocomplete': 'off'}),
        }

    def save(self, commit=True):
        product = super().save(commit=False)
        product.base_unit = Product.Unit.PIECE
        product.units_per_case = 1
        product.category = ''
        if commit:
            product.save()
            self.save_m2m()
        return product


class WarehouseForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Warehouse
        fields = ['code', 'name', 'address', 'is_active']
        labels = {'code': 'Depo kodu', 'name': 'Depo adı', 'address': 'Adres', 'is_active': 'Aktif'}
        widgets = {'address': forms.Textarea(attrs={'rows': 3})}


class VehicleForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Vehicle
        fields = ['plate', 'description', 'is_active']
        labels = {'plate': 'Araç plakası', 'description': 'Araç açıklaması', 'is_active': 'Aktif'}

    def clean_plate(self):
        return ' '.join(self.cleaned_data['plate'].upper().split())



class ConnectionSaleForm(StyledFormMixin, forms.ModelForm):
    MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024
    ALLOWED_ATTACHMENT_EXTENSIONS = {'.pdf', '.png', '.jpg', '.jpeg'}

    def clean_invoice_attachment(self):
        file = self.cleaned_data.get('invoice_attachment')
        if not file:
            return file
        if getattr(file, 'size', 0) > self.MAX_ATTACHMENT_SIZE:
            raise forms.ValidationError('Fatura eki en fazla 10 MB olabilir.')
        extension = Path(getattr(file, 'name', '')).suffix.lower()
        if extension not in self.ALLOWED_ATTACHMENT_EXTENSIONS:
            raise forms.ValidationError('Fatura eki PDF, PNG, JPG veya JPEG olmalıdır.')
        return file

    class Meta:
        model = ConnectionSale
        fields = ['customer', 'invoice_no', 'invoice_date', 'notes', 'invoice_attachment']
        labels = {
            'customer': 'Müşteri',
            'invoice_no': 'Satış faturası numarası',
            'invoice_date': 'Fatura tarihi',
            'notes': 'Notlar',
            'invoice_attachment': 'Satış faturası eki',
        }
        widgets = {
            'invoice_date': DateInput(),
            'notes': forms.Textarea(attrs={'rows': 3}),
            'invoice_attachment': forms.FileInput(attrs={
                'accept': '.pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png',
                'data-invoice-file-input': '1',
            }),
        }


class ConnectionItemForm(StyledFormMixin, forms.ModelForm):
    product = ProductChoiceField(
        label='Ürün barkodu',
        queryset=Product.objects.none(),
        widget=forms.Select(attrs={'class': 'barcode-product-select'}),
    )
    total_amount = forms.DecimalField(
        label='Toplam tutar (KDV dahil)',
        required=False,
        disabled=True,
        decimal_places=2,
        max_digits=16,
        widget=forms.NumberInput(attrs={
            'step': '0.01',
            'tabindex': '-1',
            'data-line-total': '1',
        }),
    )

    class Meta:
        model = ConnectionItem
        fields = ['product', 'quantity', 'unit_price', 'discount_rate', 'vat_rate', 'total_amount']
        labels = {
            'quantity': 'Miktar (adet)',
            'unit_price': 'Birim fiyat',
            'discount_rate': 'İskonto (%)',
            'vat_rate': 'KDV (%)',
        }
        widgets = {
            'quantity': IntegerQuantityInput(attrs={'min': 1, 'data-line-quantity': '1'}),
            'unit_price': forms.NumberInput(attrs={
                'min': 0, 'step': '0.01', 'inputmode': 'decimal',
                'data-line-price': '1',
            }),
            'discount_rate': forms.NumberInput(attrs={
                'min': 0, 'max': 100, 'step': '0.01', 'inputmode': 'decimal',
                'data-line-discount': '1',
            }),
            'vat_rate': forms.NumberInput(attrs={
                'min': 0, 'max': 100, 'step': '0.01', 'inputmode': 'decimal',
                'data-line-vat': '1',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        queryset = Product.objects.filter(is_active=True)
        if self.instance.pk and self.instance.product_id:
            queryset = Product.objects.filter(pk=self.instance.product_id) | queryset
        self.fields['product'].queryset = queryset.distinct().order_by('name')
        self.fields['product'].help_text = 'Barkodu okutun veya barkod–ürün listesinden seçim yapın.'
        self.fields['unit_price'].required = True
        self.fields['discount_rate'].required = True
        self.fields['vat_rate'].required = True
        if self.instance.pk:
            self.fields['total_amount'].initial = self.instance.total_amount

    def clean_unit_price(self):
        value = self.cleaned_data.get('unit_price')
        if value is None:
            raise forms.ValidationError('Birim fiyat zorunludur.')
        if value < 0:
            raise forms.ValidationError('Birim fiyat negatif olamaz.')
        return value

    def clean_discount_rate(self):
        value = self.cleaned_data.get('discount_rate')
        if value is None:
            raise forms.ValidationError('İskonto oranı zorunludur.')
        if value < 0 or value > 100:
            raise forms.ValidationError('İskonto oranı 0 ile 100 arasında olmalıdır.')
        return value

    def clean_vat_rate(self):
        value = self.cleaned_data.get('vat_rate')
        if value is None:
            raise forms.ValidationError('KDV oranı zorunludur.')
        if value < 0 or value > 100:
            raise forms.ValidationError('KDV oranı 0 ile 100 arasında olmalıdır.')
        return value

    def save(self, commit=True):
        item = super().save(commit=False)
        item.unit = Product.Unit.PIECE
        if commit:
            item.save()
            self.save_m2m()
        return item


class ConnectionItemBaseFormSet(BaseInlineFormSet):
    """Aynı barkod, satış ve bedelsiz kalemleri ayırmak için bir faturada birden çok satırda bulunabilir."""
    pass


ConnectionItemFormSet = inlineformset_factory(
    ConnectionSale,
    ConnectionItem,
    form=ConnectionItemForm,
    formset=ConnectionItemBaseFormSet,
    extra=1,
    can_delete=True,
    min_num=1,
    validate_min=True,
)


class OrderHeaderForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Order
        fields = ['order_date', 'requested_delivery_date', 'delivery_address', 'notes']
        labels = {
            'order_date': 'Sipariş tarihi',
            'requested_delivery_date': 'Talep edilen teslim tarihi',
            'delivery_address': 'Teslimat adresi',
            'notes': 'Notlar',
        }
        widgets = {
            'order_date': DateInput(),
            'requested_delivery_date': DateInput(),
            'delivery_address': forms.Textarea(attrs={'rows': 3}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }


class ShipmentForm(StyledFormMixin, forms.ModelForm):
    vehicle_plate = forms.ChoiceField(
        label='Araç plakası',
        required=False,
    )
    prepared_by_name = forms.ChoiceField(
        label='Hazırlayan personel',
        required=False,
    )

    class Meta:
        model = Shipment
        fields = [
            'warehouse',
            'shipment_date',
            'vehicle_plate',
            'assigned_dispatcher',
            'prepared_by_name',
            'delivery_address',
            'notes',
        ]
        labels = {
            'warehouse': 'Depo',
            'shipment_date': 'Sevk tarihi',
            'assigned_dispatcher': 'Sevkiyat personeli',
            'delivery_address': 'Teslimat adresi',
            'notes': 'Sevk notları',
        }
        widgets = {
            'shipment_date': DateInput(),
            'delivery_address': forms.Textarea(attrs={'rows': 3}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        def with_current(choices, current):
            values = {value for value, _label in choices}
            if current and current not in values:
                choices.append((current, current))
            return [('', 'Seçiniz')] + choices

        vehicle_choices = [
            (vehicle.plate, str(vehicle))
            for vehicle in Vehicle.objects.filter(is_active=True)
        ]

        staff_choices = []
        for user in User.objects.filter(
            is_active=True,
            profile__active=True,
        ).order_by('first_name', 'last_name', 'username'):
            display = user.get_full_name().strip() or user.username
            staff_choices.append((display, display))

        self.fields['vehicle_plate'].choices = with_current(
            vehicle_choices,
            getattr(self.instance, 'vehicle_plate', ''),
        )
        self.fields['prepared_by_name'].choices = with_current(
            staff_choices,
            getattr(self.instance, 'prepared_by_name', ''),
        )

        dispatch_qs = User.objects.filter(
            is_active=True,
            profile__active=True,
            profile__role=UserProfile.Role.DISPATCH,
        ).order_by('first_name', 'last_name', 'username')

        current_dispatcher_id = getattr(
            self.instance,
            'assigned_dispatcher_id',
            None,
        )

        if current_dispatcher_id:
            dispatch_qs = User.objects.filter(
                Q(pk=current_dispatcher_id)
                | Q(pk__in=dispatch_qs.values('pk'))
            ).distinct().order_by(
                'first_name',
                'last_name',
                'username',
            )

        self.fields['assigned_dispatcher'].queryset = dispatch_qs
        self.fields[
            'assigned_dispatcher'
        ].empty_label = 'Sevkiyat personeli seçiniz'


class ShipmentDeliveryForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Shipment
        fields = [
            'delivery_date', 'delivered_to',
            'receiver_signature', 'delivery_proof', 'delivery_notes',
        ]
        labels = {
            'delivery_date': 'Teslim tarihi',
            'delivered_to': 'Teslim alan kişi',
            'receiver_signature': 'İmza fotoğrafı',
            'delivery_proof': 'Teslimat kanıt fotoğrafı',
            'delivery_notes': 'Teslimat açıklaması',
        }
        widgets = {
            'delivery_date': DateInput(),
            'delivered_to': forms.TextInput(attrs={'autocomplete': 'name'}),
            'receiver_signature': forms.FileInput(attrs={
                'accept': 'image/*', 'capture': 'environment',
                'data-camera-input': 'signature',
            }),
            'delivery_proof': forms.FileInput(attrs={
                'accept': 'image/*', 'capture': 'environment',
                'data-camera-input': 'proof',
            }),
            'delivery_notes': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': 'Yalnızca özel bir durum varsa açıklama ekleyin.',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['delivery_date'].required = True
        self.fields['delivery_date'].initial = self.instance.delivery_date or timezone.localdate()
        self.fields['delivered_to'].required = True
        self.fields['delivery_notes'].required = False
        self.fields['receiver_signature'].required = not bool(getattr(self.instance, 'receiver_signature', None))
        self.fields['delivery_proof'].required = not bool(getattr(self.instance, 'delivery_proof', None))

    @staticmethod
    def _validate_photo(file, label):
        if not file:
            return file
        if getattr(file, 'size', 0) > 12 * 1024 * 1024:
            raise forms.ValidationError(f'{label} en fazla 12 MB olabilir.')
        content_type = getattr(file, 'content_type', '')
        if content_type and not content_type.startswith('image/'):
            raise forms.ValidationError(f'{label} geçerli bir fotoğraf olmalıdır.')
        try:
            file.seek(0)
            image = ImageOps.exif_transpose(Image.open(file))
            image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
            if image.mode != 'RGB':
                background = Image.new('RGB', image.size, 'white')
                if image.mode in {'RGBA', 'LA'}:
                    background.paste(image, mask=image.getchannel('A'))
                else:
                    background.paste(image.convert('RGB'))
                image = background
            output = BytesIO()
            image.save(output, format='JPEG', quality=82, optimize=True)
            stem = Path(getattr(file, 'name', 'foto')).stem
            return ContentFile(output.getvalue(), name=f'{stem}.jpg')
        except Exception as exc:
            raise forms.ValidationError(f'{label} işlenemedi. Fotoğrafı yeniden çekin veya JPG/PNG olarak yükleyin.') from exc

    def clean_receiver_signature(self):
        return self._validate_photo(self.cleaned_data.get('receiver_signature'), 'İmza fotoğrafı')

    def clean_delivery_proof(self):
        return self._validate_photo(self.cleaned_data.get('delivery_proof'), 'Teslimat kanıt fotoğrafı')


class BalanceAdjustmentForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = BalanceAdjustment
        fields = ['signed_quantity', 'kind', 'reason', 'reference_no']
        labels = {
            'signed_quantity': 'Düzeltme miktarı',
            'kind': 'Düzeltme türü',
            'reason': 'Açıklama',
            'reference_no': 'Referans numarası',
        }
        widgets = {
            'signed_quantity': forms.NumberInput(attrs={'step': 1, 'inputmode': 'numeric'}),
            'reason': forms.Textarea(attrs={'rows': 3}),
        }


class CompanySettingsForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = CompanySettings
        fields = ['company_name', 'registration_no', 'tax_no', 'phone', 'email', 'address', 'footer_note', 'document_prefix', 'default_currency', 'logo']
        labels = {
            'company_name': 'Şirket unvanı',
            'registration_no': 'Şirket kayıt numarası',
            'tax_no': 'Vergi numarası',
            'phone': 'Telefon',
            'email': 'E-posta',
            'address': 'Adres',
            'footer_note': 'Belge alt notu',
            'document_prefix': 'Belge ön eki',
            'default_currency': 'Varsayılan para birimi',
            'logo': 'Şirket logosu',
        }
        widgets = {'address': forms.Textarea(attrs={'rows': 3})}


class UserCreateForm(StyledFormMixin, forms.ModelForm):
    password1 = forms.CharField(label='Şifre', widget=forms.PasswordInput)
    password2 = forms.CharField(label='Şifre tekrar', widget=forms.PasswordInput)
    role = forms.ChoiceField(label='Rol', choices=UserProfile.Role.choices)
    phone = forms.CharField(label='Telefon', required=False)

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'is_active']
        labels = {
            'username': 'Kullanıcı adı',
            'first_name': 'Ad',
            'last_name': 'Soyad',
            'email': 'E-posta',
            'is_active': 'Aktif',
        }

    def clean(self):
        data = super().clean()
        if data.get('password1') != data.get('password2'):
            self.add_error('password2', 'Şifreler aynı değil.')
        return data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password1'])
        if commit:
            user.save()
            profile = user.profile
            profile.role = self.cleaned_data['role']
            profile.phone = self.cleaned_data['phone']
            profile.active = user.is_active
            profile.save()
        return user


class UserEditForm(StyledFormMixin, forms.ModelForm):
    role = forms.ChoiceField(label='Rol', choices=UserProfile.Role.choices)
    phone = forms.CharField(label='Telefon', required=False)
    new_password = forms.CharField(label='Yeni şifre (isteğe bağlı)', required=False, widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'is_active']
        labels = {
            'username': 'Kullanıcı adı',
            'first_name': 'Ad',
            'last_name': 'Soyad',
            'email': 'E-posta',
            'is_active': 'Aktif',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['role'].initial = self.instance.profile.role
        self.fields['phone'].initial = self.instance.profile.phone

    def clean(self):
        data = super().clean()
        if self.instance.pk and self.instance.customers.exists():
            new_role = data.get('role')
            will_be_active = data.get('is_active')
            if new_role != UserProfile.Role.SALES or not will_be_active:
                self.add_error(
                    'role',
                    'Bu kullanıcıya atanmış müşteriler var. Önce müşterileri başka bir satış temsilcisine devredin.',
                )
        return data

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get('new_password'):
            user.set_password(self.cleaned_data['new_password'])
        if commit:
            user.save()
            profile = user.profile
            profile.role = self.cleaned_data['role']
            profile.phone = self.cleaned_data['phone']
            profile.active = user.is_active
            profile.save()
        return user


class ExcelUploadForm(StyledFormMixin, forms.Form):
    file = forms.FileField(label='Excel dosyası (.xlsx)')

    def clean_file(self):
        file = self.cleaned_data['file']
        if not file.name.lower().endswith('.xlsx'):
            raise forms.ValidationError('Yalnızca .xlsx dosyası yüklenebilir.')
        if file.size > 10 * 1024 * 1024:
            raise forms.ValidationError('Excel dosyası en fazla 10 MB olabilir.')
        return file
