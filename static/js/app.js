(() => {
  const body = document.body;
  const savedTheme = localStorage.getItem('aeco-theme');
  if (savedTheme === 'dark') body.classList.add('dark');

  document.querySelector('[data-theme-toggle]')?.addEventListener('click', () => {
    body.classList.toggle('dark');
    localStorage.setItem('aeco-theme', body.classList.contains('dark') ? 'dark' : 'light');
  });

  const mobileSheet = document.querySelector('[data-mobile-sheet]');
  const sheetBackdrop = document.querySelector('[data-sheet-close]');
  const closeSheet = () => {
    mobileSheet?.classList.remove('open', 'dragging');
    if (mobileSheet) mobileSheet.style.transform = '';
    sheetBackdrop?.classList.remove('open');
    body.classList.remove('modal-open');
  };
  document.querySelector('[data-mobile-more]')?.addEventListener('click', () => {
    if (!mobileSheet) return;
    mobileSheet.scrollTop = 0;
    mobileSheet.classList.add('open');
    sheetBackdrop?.classList.add('open');
    body.classList.add('modal-open');
  });
  sheetBackdrop?.addEventListener('click', closeSheet);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && mobileSheet?.classList.contains('open')) closeSheet();
  });
  // Geri tuşuyla dönüldüğünde menü açık kalmasın.
  window.addEventListener('pagehide', closeSheet);

  // Menüyü aşağı kaydırarak kapatma.
  let dragStartY = null;
  let dragDistance = 0;
  mobileSheet?.addEventListener('touchstart', (event) => {
    if (mobileSheet.scrollTop > 0) return;
    dragStartY = event.touches[0].clientY;
    dragDistance = 0;
  }, { passive: true });
  mobileSheet?.addEventListener('touchmove', (event) => {
    if (dragStartY === null) return;
    dragDistance = event.touches[0].clientY - dragStartY;
    if (dragDistance <= 0) {
      mobileSheet.style.transform = '';
      return;
    }
    mobileSheet.classList.add('dragging');
    mobileSheet.style.transform = `translateY(${dragDistance}px)`;
  }, { passive: true });
  mobileSheet?.addEventListener('touchend', () => {
    if (dragStartY === null) return;
    dragStartY = null;
    mobileSheet.classList.remove('dragging');
    if (dragDistance > 70) closeSheet();
    else mobileSheet.style.transform = '';
  });

  document.querySelectorAll('form[data-confirm]').forEach((form) => {
    form.addEventListener('submit', (event) => {
      if (!confirm(form.dataset.confirm)) event.preventDefault();
    });
  });

  function barcodeFromLabel(label) {
    return (label || '').split('—')[0].trim();
  }

  function enhanceBarcodeSelect(select) {
    if (!select || select.dataset.barcodeEnhanced === '1') return;
    select.dataset.barcodeEnhanced = '1';

    const datalist = document.createElement('datalist');
    const safeName = (select.name || `product-${Math.random()}`).replace(/[^a-zA-Z0-9_-]/g, '-');
    datalist.id = `barcode-list-${safeName}`;

    const byBarcode = new Map();
    [...select.options].forEach((option) => {
      if (!option.value) return;
      const barcode = barcodeFromLabel(option.textContent);
      if (!barcode) return;
      byBarcode.set(barcode, option.value);
      const item = document.createElement('option');
      item.value = barcode;
      item.label = option.textContent.replace(`${barcode} —`, '').trim();
      datalist.appendChild(item);
    });

    const input = document.createElement('input');
    input.type = 'search';
    input.className = 'form-control barcode-lookup';
    input.setAttribute('list', datalist.id);
    input.setAttribute('inputmode', 'numeric');
    input.setAttribute('autocomplete', 'off');
    input.placeholder = 'Barkodu okutun veya yazın';
    input.required = select.required;
    select.required = false;

    const selected = select.options[select.selectedIndex];
    if (selected?.value) input.value = barcodeFromLabel(selected.textContent);

    const sync = () => {
      const barcode = input.value.trim();
      const value = byBarcode.get(barcode) || '';
      select.value = value;
      input.setCustomValidity(barcode && !value ? 'Geçerli bir ürün barkodu seçin.' : '');
      select.dispatchEvent(new Event('change', { bubbles: true }));
    };
    input.addEventListener('input', sync);
    input.addEventListener('change', sync);

    select.parentNode.insertBefore(input, select);
    select.parentNode.insertBefore(datalist, select);
    select.classList.add('barcode-select-hidden');
  }

  function decimalValue(input) {
    const raw = String(input?.value || '').trim().replace(',', '.');
    const value = Number.parseFloat(raw);
    return Number.isFinite(value) ? value : 0;
  }

  function turkishMoney(value) {
    return Number(value || 0).toLocaleString('tr-TR', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }

  function rowIsDeleted(row) {
    const deleteInput = row.querySelector('input[name$="-DELETE"]');
    return Boolean(deleteInput?.checked);
  }

  function roundMoney(value) {
    return Math.round((Number(value || 0) + Number.EPSILON) * 100) / 100;
  }

  function calculateConnectionRow(row) {
    const quantity = decimalValue(row.querySelector('[data-line-quantity]'));
    const unitPrice = decimalValue(row.querySelector('[data-line-price]'));
    const discountRate = Math.min(100, Math.max(0, decimalValue(row.querySelector('[data-line-discount]'))));
    const vatRate = Math.min(100, Math.max(0, decimalValue(row.querySelector('[data-line-vat]'))));
    const totalField = row.querySelector('[data-line-total]');
    const gross = roundMoney(quantity * unitPrice);
    const discount = roundMoney(gross * (discountRate / 100));
    const net = roundMoney(gross - discount);
    const vat = roundMoney(net * (vatRate / 100));
    const total = roundMoney(net + vat);
    if (totalField) totalField.value = total.toFixed(2);
    row.dataset.calculatedTotal = String(total);
    return total;
  }

  function calculateInvoiceGrandTotal() {
    const output = document.querySelector('[data-invoice-grand-total]');
    if (!output) return;
    let total = 0;
    document.querySelectorAll('[data-formset] [data-form-row]').forEach((row) => {
      if (!rowIsDeleted(row)) total += calculateConnectionRow(row);
    });
    output.textContent = turkishMoney(roundMoney(total));
  }

  function setupConnectionCalculations(root = document) {
    const rows = [];
    if (root.matches?.('[data-form-row]')) rows.push(root);
    rows.push(...root.querySelectorAll('[data-form-row]'));
    rows.forEach((row) => {
      if (row.dataset.calculationReady === '1') return;
      row.dataset.calculationReady = '1';
      row.querySelectorAll('[data-line-quantity], [data-line-price], [data-line-discount], [data-line-vat]').forEach((input) => {
        input.addEventListener('input', calculateInvoiceGrandTotal);
        input.addEventListener('change', calculateInvoiceGrandTotal);
      });
      calculateConnectionRow(row);
    });
    calculateInvoiceGrandTotal();
  }

  function enhanceAllBarcodeSelects(root = document) {
    root.querySelectorAll('.barcode-product-select').forEach(enhanceBarcodeSelect);
  }

  enhanceAllBarcodeSelects();
  setupConnectionCalculations();

  const totalForms = document.querySelector('#id_items-TOTAL_FORMS');
  const formset = document.querySelector('[data-formset]');
  const template = document.querySelector('template[data-empty-form]');
  document.querySelector('[data-add-form]')?.addEventListener('click', () => {
    if (!totalForms || !formset || !template) return;
    const index = Number.parseInt(totalForms.value, 10);
    const wrapper = document.createElement('div');
    wrapper.innerHTML = template.innerHTML.replaceAll('__prefix__', index);
    const row = wrapper.firstElementChild;
    formset.appendChild(row);
    totalForms.value = index + 1;
    enhanceAllBarcodeSelects(row);
    setupConnectionCalculations(row);
    row.querySelector('input, select')?.focus();
  });

  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-remove-form]');
    if (!button) return;
    const row = button.closest('[data-form-row]');
    const deleteInput = row?.querySelector('input[name$="-DELETE"]');
    if (deleteInput) {
      deleteInput.checked = true;
      row.hidden = true;
    } else {
      row?.remove();
    }
    calculateInvoiceGrandTotal();
  });

  function describeFile(file) {
    if (!file) return;
    const name = document.querySelector('[data-invoice-file-name]');
    const type = document.querySelector('[data-invoice-file-type]');
    if (name) name.textContent = file.name;
    if (type) {
      const extension = file.name.includes('.') ? file.name.split('.').pop().toUpperCase() : 'DOSYA';
      const size = file.size >= 1024 * 1024
        ? `${(file.size / (1024 * 1024)).toFixed(2).replace('.', ',')} MB`
        : `${Math.max(1, Math.round(file.size / 1024))} KB`;
      type.textContent = `${extension} • ${size}`;
    }
    document.querySelector('.document-upload-card')?.classList.add('has-file');
  }

  const invoiceFileInput = document.querySelector('[data-invoice-file-input]');
  invoiceFileInput?.addEventListener('change', () => describeFile(invoiceFileInput.files?.[0]));

  const quantityInputs = [...document.querySelectorAll('.qty-input')];
  const totalOutput = document.querySelector('[data-order-total] b');
  const calculateQuantityTotal = () => {
    let total = 0;
    quantityInputs.forEach((input) => {
      let value = Number.parseInt(input.value || '0', 10);
      let maximum = Number.parseInt(input.dataset.max || '0', 10);
      if (Number.isNaN(value)) value = 0;
      if (Number.isNaN(maximum)) maximum = 0;
      if (value > maximum) {
        value = maximum;
        input.value = maximum;
      }
      if (value < 0) {
        value = 0;
        input.value = 0;
      }
      total += value;
    });
    if (totalOutput) totalOutput.textContent = total.toLocaleString('tr-TR', { maximumFractionDigits: 0 });
  };
  quantityInputs.forEach((input) => input.addEventListener('input', calculateQuantityTotal));
  calculateQuantityTotal();

  const balanceFilter = document.querySelector('[data-balance-filter]');
  if (balanceFilter) {
    const rows = [...document.querySelectorAll('[data-balance-row]')];
    balanceFilter.addEventListener('input', () => {
      const query = balanceFilter.value.trim().toLocaleLowerCase('tr-TR');
      rows.forEach((row) => {
        row.hidden = Boolean(query) && !row.dataset.search.toLocaleLowerCase('tr-TR').includes(query);
      });
    });
  }

  document.querySelectorAll('[data-camera-input]').forEach((input) => {
    input.addEventListener('change', () => {
      const file = input.files?.[0];
      const key = input.dataset.cameraInput;
      const preview = document.querySelector(`[data-camera-preview="${key}"]`);
      if (!preview || !file) return;
      preview.src = URL.createObjectURL(file);
      preview.hidden = false;
      input.closest('.camera-card')?.classList.add('has-photo');
    });
  });

  // Çift tıklamada ikinci gönderim eski güvenlik anahtarıyla gider ve 403 hatası verir.
  document.querySelectorAll('form[data-submit-once]').forEach((form) => {
    const button = form.querySelector('button[type="submit"]');
    if (!button) return;
    const label = button.textContent;
    const reset = () => {
      button.disabled = false;
      button.textContent = label;
    };
    form.addEventListener('submit', (event) => {
      if (event.defaultPrevented || button.disabled) return;
      button.disabled = true;
      button.textContent = form.dataset.submitOnce;
      window.setTimeout(reset, 15000);
    });
    window.addEventListener('pageshow', (event) => {
      if (event.persisted) reset();
    });
  });

  document.querySelectorAll('[data-password-toggle]').forEach((button) => {
    const input = button.parentElement.querySelector('input');
    if (!input) return;
    button.addEventListener('click', () => {
      const show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      button.textContent = show ? 'Gizle' : 'Göster';
      button.setAttribute('aria-label', show ? 'Şifreyi gizle' : 'Şifreyi göster');
      input.focus();
    });
    input.form?.addEventListener('submit', () => {
      input.type = 'password';
    });
  });

  document.querySelector('[data-delivery-form]')?.addEventListener('submit', (event) => {
    const button = event.currentTarget.querySelector('[data-delivery-submit]');
    if (button && !button.disabled) {
      button.disabled = true;
      button.textContent = 'Teslimat Kaydediliyor…';
    }
  });

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => navigator.serviceWorker.register('/service-worker.js').catch(() => {}));
  }
})();
