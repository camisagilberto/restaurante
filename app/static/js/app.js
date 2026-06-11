(function () {
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';

  async function requestJSON(url, payload) {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Requested-With': 'XMLHttpRequest',
        'X-CSRFToken': csrfToken,
      },
      body: JSON.stringify({ ...payload, csrf_token: csrfToken }),
    });

    let data = {};
    try {
      data = await response.json();
    } catch (_) {}
    return { response, data };
  }

  function formatMoney(value) {
    return Number(value || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function setFeedback(node, message, kind) {
    if (!node) return;
    node.textContent = message || '';
    node.dataset.state = kind || '';
  }

  function updateMoneyTargets(amount, selectors) {
    selectors.forEach((selector) => {
      const node = document.querySelector(selector);
      if (node) node.textContent = `R$ ${formatMoney(amount ?? 0)}`;
    });
  }

  function updateQuantityTargets(quantity, selectors) {
    selectors.forEach((selector) => {
      const node = document.querySelector(selector);
      if (node) node.textContent = String(quantity ?? 0);
    });
  }

  function updateMenuSummary(data) {
    updateQuantityTargets(data.cart_quantity ?? 0, ['#cart-count', '#menu-cart-quantity']);
    updateMoneyTargets(data.cart_total ?? 0, ['#menu-cart-total']);
  }

  function updateCartSummary(data) {
    updateQuantityTargets(data.cart_quantity ?? 0, ['#cart-quantity']);
    updateMoneyTargets(data.cart_total ?? 0, ['#cart-total']);
    updateMenuSummary(data);
  }

  function parseServerDate(value) {
    if (!value) return null;
    const normalized = /[zZ]|[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`;
    const parsed = new Date(normalized);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }

  function tableSessionGuard() {
    return document.querySelector('[data-table-session-guard]');
  }

  function tableSessionExpired() {
    const guard = tableSessionGuard();
    if (!guard) return false;
    const expiresAt = parseServerDate(guard.dataset.expiresAt || '');
    return !expiresAt || Date.now() >= expiresAt.getTime();
  }

  function tableSessionExpiredMessage() {
    const guard = tableSessionGuard();
    return guard?.dataset.expiredMessage || 'Sua sessão da mesa expirou. Escaneie novamente o QR Code da mesa para fazer um novo pedido.';
  }

  function disableOrderingBecauseSessionExpired() {
    if (!tableSessionExpired()) return false;

    document.querySelectorAll('[data-qty-dec], [data-qty-inc], [data-qty-input], [data-cart-dec], [data-cart-inc], [data-cart-qty], [data-cart-remove], [data-cart-update], [data-cart-addon], [data-cart-flavor], #finalize-order-form button[type="submit"]').forEach((node) => {
      node.disabled = true;
    });

    document.querySelectorAll('[data-feedback]').forEach((node) => {
      if (!node.textContent) setFeedback(node, tableSessionExpiredMessage(), 'error');
    });

    return true;
  }

  function initTableSessionGuard() {
    const guard = tableSessionGuard();
    if (!guard) return;

    const run = () => disableOrderingBecauseSessionExpired();
    run();

    const expiresAt = parseServerDate(guard.dataset.expiresAt || '');
    if (expiresAt) {
      const delay = Math.max(0, expiresAt.getTime() - Date.now()) + 250;
      window.setTimeout(run, delay);
    }

    document.addEventListener('visibilitychange', run);
    window.addEventListener('pageshow', run);
    window.addEventListener('focus', run);
  }



  function initPrivacyBanner() {
    const banner = document.querySelector('[data-privacy-banner]');
    if (!banner) return;

    const storageKey = 'qrtotem_privacy_choice_v1';
    const currentChoice = window.localStorage.getItem(storageKey);
    if (currentChoice) return;

    banner.hidden = false;

    banner.querySelectorAll('[data-privacy-choice]').forEach((button) => {
      button.addEventListener('click', () => {
        window.localStorage.setItem(storageKey, button.dataset.privacyChoice || 'selected');
        banner.hidden = true;
      });
    });
  }

  function initMenuGroups() {
    const picker = document.querySelector('[data-menu-group-picker]');
    const groupCards = document.querySelectorAll('[data-menu-group-card]');
    const panels = document.querySelectorAll('[data-menu-group-panel]');
    const backButtons = document.querySelectorAll('[data-menu-back-groups]');
    const headerSwitch = document.querySelector('[data-menu-header-switch]');
    const activeLabel = document.querySelector('[data-menu-active-label]');

    if (!picker || groupCards.length === 0 || panels.length === 0) return;

    const centerFirstCategory = (panel) => {
      const scroller = panel?.querySelector('.menu-category-columns');
      const firstColumn = scroller?.querySelector('.menu-category-column');
      if (!scroller || !firstColumn) return;

      window.setTimeout(() => {
        const target = Math.max(0, firstColumn.offsetLeft - ((scroller.clientWidth - firstColumn.clientWidth) / 2));
        scroller.scrollTo({ left: target, behavior: 'auto' });
      }, 60);
    };

    const showPicker = () => {
      picker.hidden = false;
      if (headerSwitch) headerSwitch.hidden = true;
      panels.forEach((panel) => {
        panel.hidden = true;
      });
      window.scrollTo({ top: picker.offsetTop - 16, behavior: 'smooth' });
    };

    const showGroup = (groupName) => {
      picker.hidden = true;
      let activePanel = null;

      panels.forEach((panel) => {
        const isActive = panel.dataset.menuGroupPanel === groupName;
        panel.hidden = !isActive;
        if (isActive) activePanel = panel;
      });

      if (activeLabel && activePanel) {
        activeLabel.textContent = activePanel.dataset.menuGroupLabel || groupName;
      }
      if (headerSwitch) headerSwitch.hidden = false;

      if (activePanel) {
        window.scrollTo({ top: activePanel.offsetTop - 12, behavior: 'smooth' });
        centerFirstCategory(activePanel);
      }
    };

    groupCards.forEach((card) => {
      card.addEventListener('click', () => showGroup(card.dataset.menuGroupCard));
    });

    backButtons.forEach((button) => {
      button.addEventListener('click', showPicker);
    });
  }

  function initMenu() {
    document.querySelectorAll('[data-product-id]').forEach((card) => {
      const input = card.querySelector('[data-qty-input]');
      const dec = card.querySelector('[data-qty-dec]');
      const inc = card.querySelector('[data-qty-inc]');
      const feedback = card.querySelector('[data-feedback]');
      const productId = card.dataset.productId;
      let updateTimer = null;
      let isSaving = false;

      const persistQuantity = async () => {
        if (disableOrderingBecauseSessionExpired()) {
          setFeedback(feedback, tableSessionExpiredMessage(), 'error');
          return;
        }

        const quantity = Math.max(0, parseInt(input?.value || '0', 10) || 0);
        isSaving = true;
        card.dataset.cartSyncing = 'true';
        setFeedback(feedback, quantity > 0 ? 'Atualizando carrinho...' : 'Removendo do carrinho...', 'loading');

        try {
          const { response, data } = await requestJSON('/carrinho/adicionar', {
            product_id: Number(productId),
            quantity,
            replace_product_variants: true,
          });

          if (!response.ok || !data.success) {
            throw new Error(data.message || 'Falha ao atualizar o carrinho.');
          }

          updateMenuSummary(data);
          if (input) input.value = String(data.quantity ?? quantity);
          setFeedback(feedback, quantity > 0 ? 'Carrinho atualizado.' : '', 'success');
        } catch (error) {
          setFeedback(feedback, error.message || 'Não foi possível atualizar.', 'error');
        } finally {
          isSaving = false;
          card.dataset.cartSyncing = 'false';
          window.setTimeout(() => {
            if (!isSaving) setFeedback(feedback, '', '');
          }, 1400);
        }
      };

      const schedulePersist = () => {
        window.clearTimeout(updateTimer);
        updateTimer = window.setTimeout(persistQuantity, 250);
      };

      const sync = (delta) => {
        if (disableOrderingBecauseSessionExpired()) {
          setFeedback(feedback, tableSessionExpiredMessage(), 'error');
          return;
        }

        const current = parseInt(input?.value || '0', 10) || 0;
        if (input) {
          input.value = String(Math.max(0, current + delta));
          schedulePersist();
        }
      };

      dec?.addEventListener('click', () => sync(-1));
      inc?.addEventListener('click', () => sync(1));
      input?.addEventListener('change', schedulePersist);
      input?.addEventListener('blur', schedulePersist);
    });
  }

  function initCart() {
    const form = document.getElementById('finalize-order-form');

    if (disableOrderingBecauseSessionExpired() && form) {
      form.addEventListener('submit', (event) => {
        event.preventDefault();
        alert(tableSessionExpiredMessage());
      });
    }

    document.querySelectorAll('[data-cart-item]').forEach((itemCard) => {
      const input = itemCard.querySelector('[data-cart-qty]');
      const dec = itemCard.querySelector('[data-cart-dec]');
      const inc = itemCard.querySelector('[data-cart-inc]');
      const updateButton = itemCard.querySelector('[data-cart-update]');
      const removeButton = itemCard.querySelector('[data-cart-remove]');
      const productId = itemCard.dataset.productId;
      const lineKey = itemCard.dataset.lineKey || '';
      const basePrice = Number(itemCard.dataset.basePrice || 0);
      const addonInputs = Array.from(itemCard.querySelectorAll('[data-cart-addon]'));
      const flavorSelect = itemCard.querySelector('[data-cart-flavor]');
      const unitPriceNode = itemCard.querySelector('[data-cart-unit-price]');

      let updateTimer = null;
      let optionTimer = null;

      const selectedCartAddonIds = () => addonInputs.filter((checkbox) => checkbox.checked).map((checkbox) => checkbox.value);

      const selectedCartAddonTotal = () => addonInputs.reduce((total, checkbox) => {
        return total + (checkbox.checked ? Number(checkbox.dataset.addonPrice || 0) : 0);
      }, 0);

      const updateCartItemDisplayedPrice = () => {
        if (!unitPriceNode || !basePrice) return;
        unitPriceNode.textContent = `R$ ${formatMoney(basePrice + selectedCartAddonTotal())}`;
      };

      const persistOptions = async () => {
        setFeedback(itemCard.querySelector('[data-feedback]'), 'Atualizando opções...', 'loading');
        try {
          const { response, data } = await requestJSON('/carrinho/atualizar', {
            product_id: Number(productId),
            line_key: lineKey,
            quantity: 1,
            addons: selectedCartAddonIds(),
            flavor_id: flavorSelect?.value || '',
          });

          if (!response.ok || !data.success) {
            throw new Error(data.message || 'Não foi possível atualizar as opções.');
          }

          updateCartSummary(data);
          updateCartItemDisplayedPrice();
          setFeedback(itemCard.querySelector('[data-feedback]'), 'Opções atualizadas.', 'success');
        } catch (error) {
          setFeedback(itemCard.querySelector('[data-feedback]'), error.message || 'Erro ao atualizar.', 'error');
        } finally {
          window.setTimeout(() => setFeedback(itemCard.querySelector('[data-feedback]'), '', ''), 1600);
        }
      };

      const scheduleOptionUpdate = () => {
        window.clearTimeout(optionTimer);
        optionTimer = window.setTimeout(persistOptions, 250);
      };

      addonInputs.forEach((checkbox) => {
        checkbox.addEventListener('change', () => {
          updateCartItemDisplayedPrice();
          scheduleOptionUpdate();
        });
      });
      flavorSelect?.addEventListener('change', scheduleOptionUpdate);
      updateCartItemDisplayedPrice();


      const removeCardIfEmpty = () => {
        const remaining = document.querySelectorAll('[data-cart-item]').length;
        if (remaining === 0) {
          window.location.reload();
        }
      };

      const persistQuantity = async () => {
        if (disableOrderingBecauseSessionExpired()) {
          setFeedback(feedback, tableSessionExpiredMessage(), 'error');
          return;
        }

        const quantity = Math.max(0, parseInt(input?.value || '0', 10) || 0);

        if (updateButton) updateButton.disabled = true;
        if (removeButton) removeButton.disabled = true;
        setFeedback(itemCard.querySelector('[data-feedback]'), 'Atualizando...', 'loading');

        try {
          const { response, data } = await requestJSON('/carrinho/atualizar', {
            product_id: Number(productId),
            line_key: lineKey,
            quantity,
          });

          if (!response.ok || !data.success) {
            throw new Error(data.message || 'Não foi possível atualizar.');
          }

          updateCartSummary(data);

          if (data.removed || quantity <= 0) {
            itemCard.remove();
            removeCardIfEmpty();
          } else if (input) {
            input.value = String(data.quantity ?? quantity);
          }

          setFeedback(itemCard.querySelector('[data-feedback]'), 'Carrinho atualizado.', 'success');
        } catch (error) {
          setFeedback(itemCard.querySelector('[data-feedback]'), error.message || 'Erro ao atualizar.', 'error');
        } finally {
          if (updateButton) updateButton.disabled = false;
          if (removeButton) removeButton.disabled = false;
          window.setTimeout(() => setFeedback(itemCard.querySelector('[data-feedback]'), '', ''), 1800);
        }
      };

      const scheduleUpdate = () => {
        window.clearTimeout(updateTimer);
        updateTimer = window.setTimeout(() => {
          persistQuantity();
        }, 350);
      };

      const sync = (delta) => {
        if (disableOrderingBecauseSessionExpired()) {
          setFeedback(feedback, tableSessionExpiredMessage(), 'error');
          return;
        }

        const current = parseInt(input?.value || '0', 10) || 0;
        if (input) {
          input.value = String(Math.max(0, current + delta));
          scheduleUpdate();
        }
      };

      dec?.addEventListener('click', () => sync(-1));
      inc?.addEventListener('click', () => sync(1));
      input?.addEventListener('change', scheduleUpdate);
      input?.addEventListener('blur', scheduleUpdate);

      updateButton?.addEventListener('click', persistQuantity);

      removeButton?.addEventListener('click', async () => {
        updateButton && (updateButton.disabled = true);
        removeButton.disabled = true;
        setFeedback(itemCard.querySelector('[data-feedback]'), 'Removendo...', 'loading');

        try {
          const { response, data } = await requestJSON('/carrinho/excluir', {
            product_id: Number(productId),
            line_key: lineKey,
          });

          if (!response.ok || !data.success) {
            throw new Error(data.message || 'Não foi possível remover.');
          }

          updateCartSummary(data);
          itemCard.remove();
          removeCardIfEmpty();
        } catch (error) {
          setFeedback(itemCard.querySelector('[data-feedback]'), error.message || 'Erro ao remover.', 'error');
        } finally {
          updateButton && (updateButton.disabled = false);
          removeButton.disabled = false;
          window.setTimeout(() => setFeedback(itemCard.querySelector('[data-feedback]'), '', ''), 2500);
        }
      });
    });

    form?.addEventListener('submit', async (event) => {
      event.preventDefault();

      const notes = form.querySelector('[name="notes"]')?.value || '';
      const customerName = form.querySelector('[name="customer_name"]')?.value || '';
      const submitButton = event.submitter || form.querySelector('button[type="submit"]');
      const paymentMethod = submitButton?.value || 'offline';
      const termsAccepted = form.querySelector('[name="terms_accepted"]')?.checked ? '1' : '';
      const originalButtonText = submitButton.textContent;

      if (!customerName.trim()) {
        alert('Informe seu nome para identificar o pedido.');
        form.querySelector('[name="customer_name"]')?.focus();
        return;
      }

      const missingFlavor = Array.from(document.querySelectorAll('[data-cart-flavor]')).find((select) => !select.value);
      if (missingFlavor) {
        event.preventDefault();
        missingFlavor.focus();
        alert('Escolha o sabor dos produtos antes de finalizar o pedido.');
        return;
      }

      submitButton.disabled = true;
      submitButton.textContent = 'Enviando pedido...';

      try {
        const { response, data } = await requestJSON('/pedido/finalizar', {
          notes,
          customer_name: customerName,
          payment_method: paymentMethod,
          terms_accepted: termsAccepted,
        });

        if (!response.ok || !data.success) {
          throw new Error(data.message || 'Não foi possível enviar o pedido.');
        }

        window.location.href = data.payment_url || data.redirect_url || '/mesa/1';
      } catch (error) {
        alert(error.message || 'Erro ao enviar pedido.');
      } finally {
        submitButton.disabled = false;
        submitButton.textContent = originalButtonText;
      }
    });
  }

  function initCouponCodeConfirm() {
    document.querySelectorAll('[data-coupon-code-confirm]').forEach((form) => {
      form.addEventListener('submit', (event) => {
        const confirmed = confirm('O código numérico terá validade de apenas 10 minutos. Gere o código somente se você for fazer o pagamento neste intervalo. Tem certeza que deseja gerar o código agora?');
        if (!confirmed) {
          event.preventDefault();
        }
      });
    });
  }

  function initTableEditor() {
    const trigger = document.querySelector('[data-open-table-editor]');
    if (!trigger) return;

    trigger.addEventListener('click', async () => {
      const password = prompt('Digite a senha do admin para editar a mesa:');
      if (!password) return;

      const currentTable = document.getElementById('table-number-label')?.textContent?.trim() || '';
      const tableNumber = prompt('Informe o novo número da mesa:', currentTable);
      if (!tableNumber) return;

      try {
        const { response, data } = await requestJSON('/mesa/editar', {
          table_number: tableNumber,
          manager_password: password,
        });

        if (!response.ok || !data.success) {
          throw new Error(data.message || 'Não foi possível editar a mesa.');
        }

        window.location.href = data.redirect_url || `/mesa/${encodeURIComponent(data.table_number || tableNumber)}`;
      } catch (error) {
        alert(error.message || 'Erro ao editar a mesa.');
      }
    });
  }

  function askPasswordModal(message) {
    return new Promise((resolve) => {
      const overlay = document.createElement('div');
      overlay.className = 'password-modal-overlay';
      overlay.innerHTML = `
        <div class="password-modal" role="dialog" aria-modal="true" aria-labelledby="password-modal-title">
          <h3 id="password-modal-title">Senha necessária</h3>
          <p>${message}</p>
          <input type="password" autocomplete="current-password" placeholder="Digite a senha" />
          <div class="password-modal-actions">
            <button type="button" class="btn btn-secondary" data-cancel>Cancelar</button>
            <button type="button" class="btn btn-primary" data-confirm>Continuar</button>
          </div>
        </div>
      `;

      document.body.appendChild(overlay);
      const input = overlay.querySelector('input');
      const cancel = overlay.querySelector('[data-cancel]');
      const confirm = overlay.querySelector('[data-confirm]');

      const close = (value) => {
        overlay.remove();
        resolve(value);
      };

      cancel?.addEventListener('click', () => close(''));
      overlay.addEventListener('click', (event) => {
        if (event.target === overlay) close('');
      });
      confirm?.addEventListener('click', () => close((input?.value || '').trim()));
      input?.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') close((input.value || '').trim());
        if (event.key === 'Escape') close('');
      });

      window.setTimeout(() => input?.focus(), 50);
    });
  }

  function initNavigationAccordion() {
    document.querySelectorAll('[data-nav-accordion]').forEach((nav) => {
      const groups = Array.from(nav.querySelectorAll('details'));
      groups.forEach((group) => {
        group.removeAttribute('open');
        group.addEventListener('toggle', () => {
          if (!group.open) return;
          groups.forEach((other) => {
            if (other !== group) other.removeAttribute('open');
          });
        });
      });
    });
  }

  
  function initPasswordConfirmForms() {
    document.querySelectorAll('[data-password-confirm]').forEach((form) => {
      form.addEventListener('submit', (event) => {
        const message = form.dataset.passwordConfirm || 'Digite sua senha para confirmar.';
        const confirmed = confirm('Tem certeza que deseja continuar?');
        if (!confirmed) {
          event.preventDefault();
          return;
        }

        const password = prompt(message);
        if (!password) {
          event.preventDefault();
          return;
        }

        const input = form.querySelector('[name="manager_password"]');
        if (input) input.value = password;
      });
    });
  }



  function initProductAddonEditor() {
    const editor = document.querySelector('[data-product-addon-editor]');
    if (!editor) return;

    const countInput = editor.querySelector('[data-addon-count]');
    const list = editor.querySelector('[data-addon-list]');
    if (!countInput || !list) return;

    const rowTemplate = (index) => {
      const row = document.createElement('div');
      row.className = 'product-addon-editor-row';
      row.dataset.addonRow = 'true';
      row.innerHTML = `
        <div>
          <label>Adicional ${index}</label>
          <input type="text" name="addon_label_${index}" placeholder="Ex.: Adicional de leite">
        </div>
        <div>
          <label>Valor</label>
          <input type="text" name="addon_price_${index}" placeholder="3,00">
        </div>
      `;
      return row;
    };

    const syncRows = () => {
      const target = Math.max(0, Math.min(12, parseInt(countInput.value || '0', 10) || 0));
      let rows = Array.from(list.querySelectorAll('[data-addon-row]'));

      rows.forEach((row, index) => {
        if (index >= target) row.remove();
      });

      rows = Array.from(list.querySelectorAll('[data-addon-row]'));
      for (let index = rows.length + 1; index <= target; index += 1) {
        list.appendChild(rowTemplate(index));
      }
    };

    countInput.addEventListener('input', syncRows);
    countInput.addEventListener('change', syncRows);
    syncRows();
  }

  function initProductFlavorEditor() {
    const editor = document.querySelector('[data-product-flavor-editor]');
    if (!editor) return;

    const countInput = editor.querySelector('[data-flavor-count]');
    const list = editor.querySelector('[data-flavor-list]');
    if (!countInput || !list) return;

    const rowTemplate = (index) => {
      const row = document.createElement('div');
      row.className = 'product-addon-editor-row';
      row.dataset.flavorRow = 'true';
      row.innerHTML = `
        <div>
          <label>Sabor ${index}</label>
          <input type="text" name="flavor_label_${index}" placeholder="Ex.: Abacaxi">
        </div>
      `;
      return row;
    };

    const syncRows = () => {
      const target = Math.max(0, Math.min(20, parseInt(countInput.value || '0', 10) || 0));
      let rows = Array.from(list.querySelectorAll('[data-flavor-row]'));

      rows.forEach((row, index) => {
        if (index >= target) row.remove();
      });

      rows = Array.from(list.querySelectorAll('[data-flavor-row]'));
      for (let index = rows.length + 1; index <= target; index += 1) {
        list.appendChild(rowTemplate(index));
      }
    };

    countInput.addEventListener('input', syncRows);
    countInput.addEventListener('change', syncRows);
    syncRows();
  }

  function initKitchenDelete() {
    const deleteButton = document.querySelector('[data-delete-orders]');
    if (!deleteButton) return;

    deleteButton.addEventListener('click', async () => {
      const confirmed = confirm('Tem certeza que deseja apagar todo histórico de pedidos?');
      if (!confirmed) return;

      const password = prompt('Digite a senha do admin para apagar o histórico de pedidos:');
      if (!password) return;

      try {
        const { response, data } = await requestJSON('/cozinha/apagar-pedidos', { password });

        if (!response.ok || !data.success) {
          throw new Error(data.message || 'Não foi possível apagar os pedidos.');
        }

        window.location.href = data.redirect_url || '/cozinha/';
      } catch (error) {
        alert(error.message || 'Erro ao apagar pedidos.');
      }
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    initPrivacyBanner();
    initTableSessionGuard();
    initMenuGroups();
    initMenu();
    initCart();
    initTableEditor();
    initNavigationAccordion();
    initPasswordConfirmForms();
    initKitchenDelete();
    initCouponCodeConfirm();
    initProductAddonEditor();
    initProductFlavorEditor();
  });
})();

// Confirmação para gerar código de cupom rastreável QRTotem.
document.addEventListener('submit', function (event) {
  const form = event.target;
  if (!form || !form.matches('[data-confirm-coupon-code]')) {
    return;
  }

  const message = form.getAttribute('data-confirm-coupon-code') || 'Tem certeza que deseja gerar o código agora?';
  if (!window.confirm(message)) {
    event.preventDefault();
  }
});

// Validação do campo "Indicado por" no primeiro cadastro do restaurante.
document.addEventListener('DOMContentLoaded', function () {
  const input = document.querySelector('[data-referrer-lookup-url]');
  const status = document.getElementById('indicated_by_status');
  if (!input || !status) return;

  let timer = null;
  const setStatus = (message, type) => {
    status.textContent = message || '';
    status.classList.remove('success', 'error', 'info');
    status.classList.add(type || 'info');
  };

  const validate = async () => {
    const value = (input.value || '').trim();
    if (!value) {
      setStatus('', 'info');
      return;
    }

    setStatus('Verificando cliente...', 'info');

    try {
      const url = new URL(input.getAttribute('data-referrer-lookup-url'), window.location.origin);
      url.searchParams.set('identifier', value);
      const response = await fetch(url.toString(), { headers: { 'Accept': 'application/json' } });
      const data = await response.json();
      if (data.found) {
        setStatus(data.message || 'Cliente encontrado.', 'success');
      } else {
        setStatus(data.message || 'Cliente ainda não criado.', 'error');
      }
    } catch (error) {
      setStatus('Não foi possível verificar agora. O cadastro validará ao avançar.', 'info');
    }
  };

  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(validate, 500);
  });

  input.addEventListener('blur', validate);
});
