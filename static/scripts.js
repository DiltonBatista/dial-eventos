// Dial Eventos — interações do lado do cliente.
// Sem dependências externas; funciona como aprimoramento progressivo
// (o formulário e o catálogo continuam funcionando sem JS).
//
// Changelog desta revisão:
// - Corrigido bug de fuso horário na data mínima do evento
// - Delegação de eventos nos inputs de quantidade (suporta linhas adicionadas dinamicamente)
// - Acessibilidade: aria-live no total, role=tablist/tab, navegação por teclado nas abas
// - Estado vazio quando um filtro não retorna itens
// - Persistência do filtro selecionado (sessionStorage)
// - Subtotal por item (opcional/progressivo — só ativa se o HTML tiver o elemento)
// - Validação de data também no submit (defesa em profundidade, não só no atributo min)

// Diagnostic: log when the script file is fetched (helps when console filters hide debug)
console.log('static/scripts.js loaded');

(function () {
  "use strict";

  // ---- Configuração central --------------------------------------------
  // Centralizar aqui facilita customizar sem caçar strings espalhadas pelo arquivo.
  const CONFIG = {
    selectors: {
      form: "#pedido-form",
      totalEl: "#total-estimado",
      qtyInput: ".qty-input",
      itemRow: ".item-row",
      tabsContainer: "#pedido-tabs",
      fieldset: ".catalog-fieldset",
      dataEventoInput: "#pedido-form input[name='data_evento']",
    },
    classes: {
      selecionado: "selecionado",
      tabAtiva: "active",
    },
    mensagens: {
      dataNoPassado: "A data do evento não pode estar no passado.",
      semItensCategoria: "Nenhum item nesta categoria.",
    },
    storageKeyFiltro: "dial-eventos:filtro-ativo",
  };

  function formatMoney(value) {
    return "R$ " + value.toLocaleString("pt-BR", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }

  // Retorna a data local (não UTC) no formato YYYY-MM-DD.
  // Bug corrigido: `new Date().toISOString()` converte para UTC. Para fusos
  // atrás de UTC (ex.: Brasil, UTC-3), perto da meia-noite isso podia gerar
  // a data de AMANHÃ como mínimo, bloqueando o próprio dia de hoje.
  function getLocalISODate(date) {
    date = date || new Date();
    const offsetMs = date.getTimezoneOffset() * 60000;
    return new Date(date.getTime() - offsetMs).toISOString().slice(0, 10);
  }

  // ---- Total estimado do pedido, em tempo real ------------------------
  function setupTotalEstimado() {
    const form = document.querySelector(CONFIG.selectors.form);
    const totalEl = document.querySelector(CONFIG.selectors.totalEl);
    if (!form || !totalEl) return;

    // aria-live avisa leitores de tela sobre a mudança do total sem
    // precisar que o usuário navegue até o elemento de novo.
    if (!totalEl.hasAttribute("aria-live")) {
      totalEl.setAttribute("aria-live", "polite");
    }

    let frameAgendado = false;

    function recalcular() {
      let total = 0;
      const qtyInputs = form.querySelectorAll(CONFIG.selectors.qtyInput);

      qtyInputs.forEach((input) => {
        const qtyBruta = parseInt(input.value, 10);
        const qty = Number.isFinite(qtyBruta) ? Math.max(qtyBruta, 0) : 0;
        const price = parseFloat(input.dataset.price) || 0;

        const row = input.closest(CONFIG.selectors.itemRow);
        if (row) {
          row.classList.toggle(CONFIG.classes.selecionado, qty > 0);
          // Subtotal por item: só atualiza se o HTML fornecer o elemento.
          // Isso mantém o recurso opcional e não quebra páginas existentes.
          const subtotalEl = row.querySelector(".item-subtotal");
          if (subtotalEl) subtotalEl.textContent = formatMoney(qty * price);
        }

        total += qty * price;
      });

      totalEl.textContent = formatMoney(total);
      frameAgendado = false;
    }

    // Agrupa recálculos em um único frame (requestAnimationFrame) para
    // evitar layout thrashing quando o catálogo tem muitas linhas.
    function agendarRecalculo() {
      if (frameAgendado) return;
      frameAgendado = true;
      requestAnimationFrame(recalcular);
    }

    // Delegação de eventos: um único listener no formulário cobre também
    // inputs de quantidade adicionados dinamicamente depois do load.
    form.addEventListener("input", (event) => {
      if (event.target.matches(CONFIG.selectors.qtyInput)) {
        agendarRecalculo();
      }
    });

    // Corrige valores negativos apenas ao sair do campo (blur), não a cada
    // tecla digitada — evita atrapalhar o usuário enquanto ele ainda digita.
    form.addEventListener(
      "blur",
      (event) => {
        if (!event.target.matches(CONFIG.selectors.qtyInput)) return;
        const qty = parseInt(event.target.value, 10);
        if (!Number.isFinite(qty) || qty < 0) {
          event.target.value = 0;
          agendarRecalculo();
        }
      },
      true // captura, pois "blur" não borbulha
    );

    recalcular();
  }

  // ---- Filtro de categorias no formulário de pedido --------------------
  function setupFiltroPedido() {
    const tabs = document.querySelector(CONFIG.selectors.tabsContainer);
    if (!tabs) return;

    const fieldsets = Array.from(document.querySelectorAll(CONFIG.selectors.fieldset));
    const listaTabs = Array.from(tabs.querySelectorAll(".tab"));

    // Semântica de abas para leitores de tela.
    tabs.setAttribute("role", "tablist");
    listaTabs.forEach((tab) => {
      tab.setAttribute("role", "tab");
      tab.setAttribute("tabindex", tab.classList.contains(CONFIG.classes.tabAtiva) ? "0" : "-1");
      tab.setAttribute("aria-selected", tab.classList.contains(CONFIG.classes.tabAtiva) ? "true" : "false");
    });

    // Mensagem de "sem itens", criada uma vez e reutilizada.
    let vazioEl = document.getElementById("pedido-empty-state");
    if (!vazioEl) {
      vazioEl = document.createElement("p");
      vazioEl.id = "pedido-empty-state";
      vazioEl.className = "pedido-empty-state";
      vazioEl.hidden = true;
      vazioEl.textContent = CONFIG.mensagens.semItensCategoria;
      tabs.insertAdjacentElement("afterend", vazioEl);
    }

    function aplicarFiltro(categoria, tabAtiva) {
      listaTabs.forEach((t) => {
        const ativa = t === tabAtiva;
        t.classList.toggle(CONFIG.classes.tabAtiva, ativa);
        t.setAttribute("aria-selected", ativa ? "true" : "false");
        t.setAttribute("tabindex", ativa ? "0" : "-1");
      });

      let algumVisivel = false;
      fieldsets.forEach((fs) => {
        const mostrar = categoria === "__all__" || fs.dataset.categoria === categoria;
        fs.style.display = mostrar ? "" : "none";
        if (mostrar) algumVisivel = true;
      });

      vazioEl.hidden = algumVisivel;

      try {
        sessionStorage.setItem(CONFIG.storageKeyFiltro, categoria);
      } catch (e) {
        // sessionStorage pode falhar em modo privado/restrito — não é crítico, ignora.
      }
    }

    tabs.addEventListener("click", (event) => {
      const tab = event.target.closest(".tab");
      if (!tab) return;
      event.preventDefault();
      aplicarFiltro(tab.dataset.categoria, tab);
    });

    // Navegação por teclado entre abas (seta esquerda/direita), padrão
    // esperado pelo papel ARIA "tablist".
    tabs.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
      const atual = listaTabs.findIndex((t) => t.classList.contains(CONFIG.classes.tabAtiva));
      if (atual === -1) return;
      event.preventDefault();
      const delta = event.key === "ArrowRight" ? 1 : -1;
      const proximo = listaTabs[(atual + delta + listaTabs.length) % listaTabs.length];
      proximo.focus();
      aplicarFiltro(proximo.dataset.categoria, proximo);
    });

    // Restaura o último filtro usado na sessão, se existir e ainda for válido.
    try {
      const salvo = sessionStorage.getItem(CONFIG.storageKeyFiltro);
      const tabSalva = salvo && listaTabs.find((t) => t.dataset.categoria === salvo);
      if (tabSalva) aplicarFiltro(salvo, tabSalva);
    } catch (e) {
      // Ignora se sessionStorage não estiver disponível.
    }
  }

  // ---- Confirmação extra ao excluir item do catálogo (defesa dupla) ---
  function setupConfirmacoes() {
    document.querySelectorAll("form[data-confirm]").forEach((form) => {
      form.addEventListener("submit", (event) => {
        const mensagem = form.dataset.confirm || "Tem certeza?";
        if (!window.confirm(mensagem)) {
          event.preventDefault();
        }
      });
    });
  }

  // ---- Validação de data (não permitir data no passado) ---------------
  function setupValidacaoData() {
    const dataInput = document.querySelector(CONFIG.selectors.dataEventoInput);
    if (!dataInput) return;

    const hoje = getLocalISODate();
    dataInput.setAttribute("min", hoje);

    // O atributo "min" pode ser contornado (DevTools, navegadores antigos,
    // autofill). Revalidar no submit é uma segunda camada de proteção no
    // cliente — a validação real e definitiva continua sendo no servidor.
    const form = dataInput.closest("form");
    if (!form) return;

    form.addEventListener("submit", (event) => {
      if (dataInput.value && dataInput.value < hoje) {
        event.preventDefault();
        dataInput.setCustomValidity(CONFIG.mensagens.dataNoPassado);
        dataInput.reportValidity();
      }
    });

    dataInput.addEventListener("input", () => {
      dataInput.setCustomValidity("");
    });
  }

  function setupPlannerPanel() {
    const options = document.querySelectorAll('.planner-option');
    const titleEl = document.getElementById('planner-title');
    const textEl = document.getElementById('planner-text');
    const linkEl = document.getElementById('planner-link');
    const countEl = document.getElementById('planner-count');

    if (!options.length || !titleEl || !textEl || !linkEl || !countEl) return;

    const summaries = {
      Casamento: 'Materiais essenciais',
      Aniversários: 'Itens para festa',
      Corporativo: 'Estrutura para evento',
    };

    options.forEach((option) => {
      option.addEventListener('click', () => {
        options.forEach((btn) => btn.classList.toggle('is-active', btn === option));
        titleEl.textContent = option.dataset.title || option.dataset.category;
        textEl.textContent = option.dataset.text || '';
        linkEl.href = option.dataset.url || '/catalogo';
        countEl.textContent = summaries[option.dataset.category] || 'Materiais essenciais';
      });
    });
  }

  function setupHeroSlider() {
    const gallery = document.querySelector('.hero-gallery');
    if (!gallery) return;

    const slides = Array.from(gallery.querySelectorAll('.hero-slide'));
    const dots = Array.from(document.querySelectorAll('.hero-dot'));
    if (!slides.length) return;

    let activeIndex = 0;
    let intervalId = null;

    function renderSlide(index) {
      activeIndex = (index + slides.length) % slides.length;
      slides.forEach((slide, slideIndex) => {
        slide.classList.toggle('is-active', slideIndex === activeIndex);
      });
      dots.forEach((dot, dotIndex) => {
        dot.classList.toggle('is-active', dotIndex === activeIndex);
        dot.setAttribute('aria-pressed', dotIndex === activeIndex ? 'true' : 'false');
      });
    }

    function startLoop() {
      if (intervalId) clearInterval(intervalId);
      intervalId = setInterval(() => renderSlide(activeIndex + 1), 3200);
    }

    dots.forEach((dot) => {
      dot.addEventListener('click', () => {
        renderSlide(Number(dot.dataset.slide) || 0);
        startLoop();
      });
    });

    renderSlide(0);
    startLoop();
  }

  document.addEventListener("DOMContentLoaded", () => {
    setupTotalEstimado();
    setupFiltroPedido();
    setupConfirmacoes();
    setupValidacaoData();
    setupPlannerPanel();
    setupHeroSlider();
    setupTestimonialsModal();
  });

  // ---- Modal de depoimentos (abre o conteúdo de testimonials em modal)
  function setupTestimonialsModal() {
    console.debug('setupTestimonialsModal: init');
    const overlay = document.querySelector('.hero-video-overlay');
    const testimonials = document.querySelector('#testimonials');
    if (!overlay || !testimonials) return;
    console.debug('setupTestimonialsModal: overlay and testimonials found', { overlay: !!overlay, testimonials: !!testimonials });

    function buildModal() {
      const backdrop = document.createElement('div');
      backdrop.className = 'modal-backdrop';
      backdrop.tabIndex = -1;

      const modal = document.createElement('div');
      modal.className = 'modal';
      modal.setAttribute('role', 'dialog');
      modal.setAttribute('aria-modal', 'true');
      modal.setAttribute('aria-label', 'Depoimentos dos clientes');

      const close = document.createElement('button');
      close.className = 'close-btn';
      close.innerHTML = '✕';
      close.addEventListener('click', () => closeModal());

      // clone testimonials content to modal
      const content = testimonials.cloneNode(true);
      content.id = '';
      modal.appendChild(close);
      modal.appendChild(content);
      backdrop.appendChild(modal);

      backdrop.addEventListener('click', (ev) => {
        if (ev.target === backdrop) closeModal();
      });

      document.addEventListener('keydown', onKeyDown);

      function onKeyDown(ev) {
        if (ev.key === 'Escape') closeModal();
      }

      function openModal() {
        document.body.appendChild(backdrop);
        // focus first focusable element inside modal
        const focusable = modal.querySelector('button, [href], input, textarea, select, [tabindex]');
        if (focusable) focusable.focus();
      }

      function closeModal() {
        try {
          document.removeEventListener('keydown', onKeyDown);
          backdrop.remove();
        } catch (e) {}
      }

      return { openModal, closeModal };
    }

    const modalApi = buildModal();

    overlay.addEventListener('click', (ev) => {
      console.debug('hero overlay clicked', ev);
      // prefer abrir modal em vez de navegar; mantém href como fallback
      ev.preventDefault();
      modalApi.openModal();
    });
  }
})();
