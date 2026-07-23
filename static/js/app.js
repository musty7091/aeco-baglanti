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
    mobileSheet?.classList.remove('open');
    sheetBackdrop?.classList.remove('open');
  };
  document.querySelector('[data-mobile-more]')?.addEventListener('click', () => {
    mobileSheet?.classList.add('open');
    sheetBackdrop?.classList.add('open');
  });
  sheetBackdrop?.addEventListener('click', closeSheet);

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

  function setupScannerPanel() {
    const panel = document.querySelector('[data-scanner-panel]');
    const modal = document.querySelector('[data-scanner-modal]');
    const openButton = document.querySelector('[data-open-scanner]');
    if (!panel || !modal || !openButton || !invoiceFileInput) return;

    const serviceUrl = panel.dataset.scannerUrl?.replace(/\/$/, '');
    const token = panel.dataset.scannerToken;
    const status = modal.querySelector('[data-scanner-status]');
    const deviceSelect = modal.querySelector('[data-scanner-device]');
    const scanButton = modal.querySelector('[data-scan-page]');
    const finishButton = modal.querySelector('[data-finish-scan]');
    const pageCountOutput = modal.querySelector('[data-scanner-page-count]');
    const mobileNote = panel.querySelector('[data-scanner-mobile-note]');
    const mobileDevice = /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent);
    let sessionId = null;
    let pageCount = 0;
    let busy = false;

    const setStatus = (message, kind = '') => {
      status.textContent = message;
      status.className = `scanner-status ${kind ? `scanner-status-${kind}` : ''}`.trim();
    };

    const setBusy = (value) => {
      busy = value;
      deviceSelect.disabled = value || !deviceSelect.options.length;
      scanButton.disabled = value || !deviceSelect.value;
      finishButton.disabled = value || pageCount < 1;
    };

    async function scannerFetch(path, options = {}) {
      const response = await fetch(`${serviceUrl}${path}`, {
        ...options,
        cache: 'no-store',
        credentials: 'omit',
        headers: {
          'X-AECO-Scanner-Token': token,
          ...(options.body ? { 'Content-Type': 'application/json' } : {}),
          ...(options.headers || {}),
        },
      });
      const contentType = response.headers.get('content-type') || '';
      if (!response.ok) {
        let message = 'Tarama servisi isteği tamamlanamadı.';
        if (contentType.includes('application/json')) {
          const payload = await response.json().catch(() => ({}));
          message = payload.error || message;
        }
        throw new Error(message);
      }
      return response;
    }

    async function cancelSession() {
      if (!sessionId) return;
      const current = sessionId;
      sessionId = null;
      try {
        await scannerFetch(`/sessions/${current}`, { method: 'DELETE' });
      } catch (_) {
        // Süresi dolmuş oturumlar servis tarafından da temizlenir.
      }
    }

    async function closeModal() {
      if (busy) return;
      await cancelSession();
      modal.hidden = true;
      body.classList.remove('modal-open');
      pageCount = 0;
      pageCountOutput.textContent = '0';
      finishButton.disabled = true;
    }

    async function loadDevices() {
      setBusy(true);
      setStatus('Windows tarama servisine bağlanılıyor…');
      deviceSelect.innerHTML = '<option value="">Tarayıcılar yükleniyor…</option>';
      try {
        const response = await scannerFetch('/devices');
        const payload = await response.json();
        deviceSelect.innerHTML = '';
        if (!payload.devices?.length) {
          deviceSelect.innerHTML = '<option value="">Fiziksel tarayıcı bulunamadı</option>';
          setStatus('Bağlı ve açık bir WIA tarayıcısı bulunamadı. Dosyadan Seç seçeneğini kullanabilirsiniz.', 'error');
          setBusy(false);
          return;
        }
        deviceSelect.append(new Option('Tarayıcı seçiniz', ''));
        payload.devices.forEach((device) => {
          const label = device.description ? `${device.name} — ${device.description}` : device.name;
          deviceSelect.append(new Option(label, device.id));
        });
        setStatus('Tarayıcıyı seçin ve ilk sayfayı tarayın.', 'success');
      } catch (error) {
        deviceSelect.innerHTML = '<option value="">Servise ulaşılamadı</option>';
        setStatus(`${error.message} SCANNER_SERVICE.bat veya RUN_WINDOWS.bat dosyasını çalıştırın.`, 'error');
      } finally {
        setBusy(false);
      }
    }

    openButton.addEventListener('click', async () => {
      if (mobileDevice) return;
      modal.hidden = false;
      body.classList.add('modal-open');
      pageCount = 0;
      pageCountOutput.textContent = '0';
      await loadDevices();
    });

    deviceSelect.addEventListener('change', async () => {
      await cancelSession();
      pageCount = 0;
      pageCountOutput.textContent = '0';
      finishButton.disabled = true;
      scanButton.disabled = !deviceSelect.value;
      if (deviceSelect.value) setStatus('Belgeyi tarayıcıya yerleştirin ve “Sayfa Tara” düğmesine basın.');
    });

    scanButton.addEventListener('click', async () => {
      if (!deviceSelect.value || busy) return;
      setBusy(true);
      setStatus('Sayfa taranıyor… Tarayıcı işlemi tamamlanana kadar bekleyin.');
      try {
        if (!sessionId) {
          const response = await scannerFetch('/sessions', {
            method: 'POST',
            body: JSON.stringify({ device_id: deviceSelect.value }),
          });
          const payload = await response.json();
          sessionId = payload.session_id;
        }
        const response = await scannerFetch(`/sessions/${sessionId}/pages`, {
          method: 'POST',
          body: '{}',
        });
        const payload = await response.json();
        pageCount = payload.page_count;
        pageCountOutput.textContent = String(pageCount);
        setStatus(`${pageCount}. sayfa başarıyla tarandı. Yeni sayfa ekleyebilir veya PDF oluşturabilirsiniz.`, 'success');
      } catch (error) {
        setStatus(error.message, 'error');
      } finally {
        setBusy(false);
      }
    });

    finishButton.addEventListener('click', async () => {
      if (!sessionId || pageCount < 1 || busy) return;
      setBusy(true);
      setStatus('Sayfalar tek PDF dosyasında birleştiriliyor…');
      try {
        const response = await scannerFetch(`/sessions/${sessionId}/finish`, {
          method: 'POST',
          body: '{}',
        });
        const payload = await response.json();
        const pdfResponse = await scannerFetch(payload.download_url);
        const blob = await pdfResponse.blob();
        const file = new File([blob], payload.filename || 'taranan-fatura.pdf', {
          type: 'application/pdf',
          lastModified: Date.now(),
        });
        const transfer = new DataTransfer();
        transfer.items.add(file);
        invoiceFileInput.files = transfer.files;
        invoiceFileInput.dispatchEvent(new Event('change', { bubbles: true }));
        sessionId = null;
        modal.hidden = true;
        body.classList.remove('modal-open');
        setStatus('Taranan PDF faturaya eklendi.', 'success');
      } catch (error) {
        setStatus(error.message, 'error');
      } finally {
        setBusy(false);
      }
    });

    modal.querySelectorAll('[data-close-scanner]').forEach((button) => {
      button.addEventListener('click', closeModal);
    });

    if (mobileDevice) {
      openButton.disabled = true;
      openButton.title = 'Fiziksel tarama yalnızca Windows bilgisayarda kullanılabilir.';
      mobileNote.hidden = false;
    }
  }

  setupScannerPanel();

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
