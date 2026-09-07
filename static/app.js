/* ============================================================
   N.A.S.H — Frontend
   Chat, tarefas, projetos, memória, conexões, voz.
   ============================================================ */

(() => {
  "use strict";

  // ---------------------------------------------------------
  // Utilitários
  // ---------------------------------------------------------

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  function escapeHtml(str) {
    return (str || "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  /**
   * Renderizador de Markdown leve (sem dependência externa):
   * blocos de código, código inline, negrito, itálico, listas, parágrafos.
   * Preserva $...$ e $$...$$ para o MathJax processar depois.
   */
  function renderMarkdown(raw) {
    if (!raw) return "";
    const codeBlocks = [];
    let text = raw.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
      const idx = codeBlocks.length;
      codeBlocks.push(`<pre><code class="lang-${escapeHtml(lang)}">${escapeHtml(code.trim())}</code></pre>`);
      return `\u0000CODEBLOCK${idx}\u0000`;
    });

    text = escapeHtml(text);

    text = text.replace(/`([^`]+)`/g, (_, c) => `<code>${c}</code>`);
    text = text.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    text = text.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, "<em>$1</em>");

    // Listas simples (- item / 1. item)
    const lines = text.split("\n");
    let html = "";
    let inUl = false, inOl = false;
    for (const line of lines) {
      const ulMatch = line.match(/^\s*[-*]\s+(.*)/);
      const olMatch = line.match(/^\s*\d+\.\s+(.*)/);
      if (ulMatch) {
        if (!inUl) { html += "<ul>"; inUl = true; }
        html += `<li>${ulMatch[1]}</li>`;
        continue;
      }
      if (inUl) { html += "</ul>"; inUl = false; }
      if (olMatch) {
        if (!inOl) { html += "<ol>"; inOl = true; }
        html += `<li>${olMatch[1]}</li>`;
        continue;
      }
      if (inOl) { html += "</ol>"; inOl = false; }
      if (line.trim() === "") { html += ""; }
      else { html += `<p>${line}</p>`; }
    }
    if (inUl) html += "</ul>";
    if (inOl) html += "</ol>";

    html = html.replace(/\u0000CODEBLOCK(\d+)\u0000/g, (_, i) => codeBlocks[Number(i)]);
    return html;
  }

  function toast(message, type = "info") {
    const area = $("#toast-area");
    const el = document.createElement("div");
    el.className = `toast ${type}`;
    el.textContent = message;
    area.appendChild(el);
    setTimeout(() => el.remove(), 4200);
  }

  async function api(path, options = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    let data;
    try {
      data = await res.json();
    } catch {
      throw new Error("Resposta inválida do servidor.");
    }
    if (!res.ok || data.ok === false) {
      throw new Error(data.error || `Erro (${res.status})`);
    }
    return data;
  }

  // ---------------------------------------------------------
  // Navegação entre views
  // ---------------------------------------------------------

  const PAGE_TITLES = {
    central: "Command Center · Central de comando",
    agenda: "Command Center · Agenda",
    study: "Command Center · Estudo",
    lab: "Command Center · Laboratório",
    projects: "Command Center · Projetos",
    apps: "Command Center · Apps",
    memory: "Command Center · Memória",
    activity: "Command Center · Atividade",
    settings: "Command Center · Ajustes",
  };

  function initNav() {
    $$(".nav-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        $$(".nav-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        const view = btn.dataset.view;
        $$(".view").forEach((v) => v.classList.remove("active"));
        $(`#view-${view}`).classList.add("active");
        const titleEl = $("#header-page-title");
        if (titleEl && PAGE_TITLES[view]) titleEl.textContent = PAGE_TITLES[view];
        if (view === "agenda") { loadCalendar(); loadTasks(); }
        if (view === "projects") loadProjects();
        if (view === "memory") loadMemory();
        if (view === "apps") loadConnections();
        if (view === "activity") loadActivity();
        if (view === "settings") loadSettings();
      });
    });
  }

  // ---------------------------------------------------------
  // CHAT
  // ---------------------------------------------------------

  const core = $("#core-indicator");
  const dashCore = $("#dash-core");
  const chatScroll = $("#chat-scroll");
  const chatInput = $("#chat-input");
  const composer = $("#composer");

  function setThinking(on) {
    core.classList.toggle("thinking", on);
    if (dashCore) dashCore.classList.toggle("thinking", on);
    if (on) setCoreStatus("processando");
  }

  function setCoreStatus(label) {
    const el = $("#chat-core-status");
    if (el) el.textContent = label;
  }

  function scrollChatToBottom() {
    chatScroll.scrollTop = chatScroll.scrollHeight;
  }

  function typesetMath() {
    if (window.MathJax && window.MathJax.typesetPromise) {
      window.MathJax.typesetPromise([chatScroll]).catch(() => {});
    }
  }

  function appendMessage(role, text, { pendingAction = null } = {}) {
    const wrap = document.createElement("div");
    wrap.className = `msg ${role}`;

    const avatar = document.createElement("div");
    avatar.className = "msg-avatar";
    avatar.textContent = role === "user" ? "EU" : "N";

    const bubble = document.createElement("div");
    bubble.className = "msg-bubble";
    bubble.innerHTML = renderMarkdown(text);

    if (pendingAction) {
      const card = document.createElement("div");
      card.className = "confirm-card";
      card.innerHTML = `
        <span class="confirm-label">⚠ Ação requer confirmação · ${escapeHtml(pendingAction.permission)}</span>
        <div class="confirm-actions">
          <button class="btn primary small" data-action="confirm">Confirmar</button>
          <button class="btn small" data-action="cancel">Cancelar</button>
        </div>
      `;
      card.querySelector('[data-action="confirm"]').addEventListener("click", (e) => {
        resolvePendingAction(pendingAction.id, true, card, e.target);
      });
      card.querySelector('[data-action="cancel"]').addEventListener("click", (e) => {
        resolvePendingAction(pendingAction.id, false, card, e.target);
      });
      bubble.appendChild(card);
    }

    if (role === "user") {
      wrap.appendChild(bubble);
      wrap.appendChild(avatar);
    } else {
      wrap.appendChild(avatar);
      wrap.appendChild(bubble);
    }

    chatScroll.appendChild(wrap);
    scrollChatToBottom();
    typesetMath();
    return wrap;
  }

  function appendTypingIndicator() {
    const wrap = document.createElement("div");
    wrap.className = "msg assistant";
    wrap.id = "typing-indicator";
    wrap.innerHTML = `
      <div class="msg-avatar">N</div>
      <div class="msg-bubble"><div class="typing-dots"><span></span><span></span><span></span></div><span class="typing-label">N.A.S.H está pensando...</span></div>
    `;
    chatScroll.appendChild(wrap);
    scrollChatToBottom();
  }

  function removeTypingIndicator() {
    const el = $("#typing-indicator");
    if (el) el.remove();
  }

  async function resolvePendingAction(pendingId, confirmed, cardEl, btnEl) {
    $$("button", cardEl).forEach((b) => (b.disabled = true));
    try {
      const endpoint = confirmed
        ? `/api/pending-actions/${pendingId}/confirm`
        : `/api/pending-actions/${pendingId}/cancel`;
      const data = await api(endpoint, { method: "POST" });
      cardEl.outerHTML = `<div class="confirm-card" style="border-color: var(--border); background: transparent;">
        <span style="color: var(--text-muted); font-size: 13px;">${confirmed ? "✔ Confirmado" : "✕ Cancelado"}</span>
      </div>`;
      appendMessage("assistant", data.text);
      refreshStatus();
      if (document.querySelector("#view-tasks.active")) loadTasks();
      if (document.querySelector("#view-projects.active")) loadProjects();
      if (document.querySelector("#view-memory.active")) loadMemory();
      if (document.querySelector("#view-calendar.active")) loadCalendar();
    } catch (err) {
      toast(err.message, "error");
      $$("button", cardEl).forEach((b) => (b.disabled = false));
    }
  }

  async function sendMessage(text) {
    appendMessage("user", text);
    appendTypingIndicator();
    setThinking(true);
    composer.querySelector("#send-btn").disabled = true;

    try {
      const data = await api("/api/chat", {
        method: "POST",
        body: JSON.stringify({ message: text }),
      });
      removeTypingIndicator();

      if (data.type === "confirmation_required") {
        appendMessage("assistant", data.text, { pendingAction: data.pending_action });
        setCoreStatus("aguardando confirmação");
      } else if (data.type === "error") {
        appendMessage("error", data.text);
        setCoreStatus("erro");
      } else {
        appendMessage("assistant", data.text);
        speakIfEnabled(data.text);
        setCoreStatus("pronto");
      }
    } catch (err) {
      removeTypingIndicator();
      appendMessage("error", `Não consegui falar com o servidor: ${err.message}`);
      setCoreStatus("erro");
    } finally {
      setThinking(false);
      composer.querySelector("#send-btn").disabled = false;
      refreshStatus();
    }
  }

  composer.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = chatInput.value.trim();
    if (!text) return;
    chatInput.value = "";
    chatInput.style.height = "auto";
    sendMessage(text);
  });

  chatInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      composer.requestSubmit();
    }
  });

  chatInput.addEventListener("input", () => {
    chatInput.style.height = "auto";
    chatInput.style.height = Math.min(chatInput.scrollHeight, 140) + "px";
  });

  async function loadHistory() {
    try {
      const data = await api("/api/history");
      if (data.messages.length === 0) {
        appendMessage(
          "assistant",
          "Olá. Eu sou o **N.A.S.H**. Seu assistente pessoal, parceiro de estudos e centro de comando. Como posso ajudá-lo?"
        );
        return;
      }
      data.messages.forEach((m) => appendMessage(m.role === "user" ? "user" : "assistant", m.content));
    } catch (err) {
      toast("Não foi possível carregar o histórico de conversa.", "error");
    }
  }

  // ---------------------------------------------------------
  // VOZ (Web Speech API)
  // ---------------------------------------------------------

  let recognition = null;
  let listening = false;
  let voiceOutputEnabled = false;

  function initSpeech() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const micBtn = $("#mic-btn");

    if (!SpeechRecognition) {
      micBtn.disabled = true;
      micBtn.title = "Reconhecimento de voz não é suportado neste navegador.";
      return;
    }

    recognition = new SpeechRecognition();
    recognition.lang = "pt-BR";
    recognition.continuous = false;
    recognition.interimResults = false;

    recognition.onstart = () => { listening = true; micBtn.classList.add("active"); };
    recognition.onend = () => { listening = false; micBtn.classList.remove("active"); };
    recognition.onerror = () => { listening = false; micBtn.classList.remove("active"); };
    recognition.onresult = (event) => {
      const transcript = event.results[0][0].transcript;
      chatInput.value = transcript;
      chatInput.dispatchEvent(new Event("input"));
    };

    micBtn.addEventListener("click", () => {
      if (listening) { recognition.stop(); return; }
      try { recognition.start(); } catch { /* já iniciado */ }
    });
  }

  function speakIfEnabled(text) {
    if (!voiceOutputEnabled || !window.speechSynthesis) return;
    const clean = text.replace(/[*_`#$]/g, "").replace(/\n+/g, ". ");
    const utter = new SpeechSynthesisUtterance(clean);
    utter.lang = "pt-BR";
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utter);
  }

  function initVoiceOutputToggle() {
    const btn = $("#voice-output-toggle");
    if (!window.speechSynthesis) {
      btn.disabled = true;
      btn.title = "Síntese de voz não é suportada neste navegador.";
      return;
    }
    btn.addEventListener("click", () => {
      voiceOutputEnabled = !voiceOutputEnabled;
      btn.classList.toggle("on", voiceOutputEnabled);
      const settingsBtn = $("#settings-voice-toggle");
      if (settingsBtn) settingsBtn.textContent = voiceOutputEnabled ? "Desativar" : "Ativar";
      toast(voiceOutputEnabled ? "Leitura por voz ativada." : "Leitura por voz desativada.");
      if (!voiceOutputEnabled) window.speechSynthesis.cancel();
    });
  }

  // ---------------------------------------------------------
  // TAREFAS
  // ---------------------------------------------------------

  function priorityLabel(p) { return { alta: "Alta", normal: "Normal", baixa: "Baixa" }[p] || p; }
  function statusLabel(s) { return { pendente: "Pendente", concluida: "Concluída", excluida: "Excluída" }[s] || s; }

  async function loadTasks() {
    const filter = $("#tasks-filter").value;
    const includeDeleted = filter === "excluida" || filter === "";
    try {
      const data = await api(`/api/tasks?include_deleted=${includeDeleted ? "1" : "0"}`);
      let tasks = data.tasks;
      if (filter) tasks = tasks.filter((t) => t.status === filter);
      renderTasks(tasks);
      $("#tasks-count").textContent = tasks.length;
    } catch (err) {
      toast(err.message, "error");
    }
  }

  function renderTasks(tasks) {
    const list = $("#tasks-list");
    list.innerHTML = "";
    if (tasks.length === 0) {
      list.innerHTML = `<div class="empty-state">Nenhuma tarefa aqui.</div>`;
      return;
    }
    tasks.forEach((t) => {
      const card = document.createElement("div");
      card.className = "item-card";
      card.innerHTML = `
        <div class="item-top">
          <div class="item-title">${escapeHtml(t.title)}</div>
          <div style="display:flex; gap:6px;">
            <span class="badge ${t.status}">${statusLabel(t.status)}</span>
            <span class="badge ${t.priority}">${priorityLabel(t.priority)}</span>
          </div>
        </div>
        ${t.description ? `<div class="item-desc">${escapeHtml(t.description)}</div>` : ""}
        <div class="item-meta">
          ${t.date ? `<span>📅 ${t.date}</span>` : ""}
          ${t.time ? `<span>🕐 ${t.time}</span>` : ""}
        </div>
        <div class="item-actions">
          ${t.status === "pendente" ? `<button class="btn small" data-act="complete">Concluir</button>` : ""}
          ${t.status !== "excluida" ? `<button class="btn small danger" data-act="delete">Excluir</button>` : ""}
          ${t.status === "excluida" ? `<button class="btn small" data-act="restore">Restaurar</button>` : ""}
        </div>
      `;
      const completeBtn = card.querySelector('[data-act="complete"]');
      const deleteBtn = card.querySelector('[data-act="delete"]');
      const restoreBtn = card.querySelector('[data-act="restore"]');
      if (completeBtn) completeBtn.addEventListener("click", () => taskAction(t.id, "complete"));
      if (deleteBtn) deleteBtn.addEventListener("click", () => {
        if (confirm(`Excluir a tarefa "${t.title}"?`)) taskAction(t.id, "delete");
      });
      if (restoreBtn) restoreBtn.addEventListener("click", () => taskAction(t.id, "restore"));
      list.appendChild(card);
    });
  }

  async function taskAction(id, action) {
    try {
      if (action === "complete") await api(`/api/tasks/${id}/complete`, { method: "POST" });
      if (action === "restore") await api(`/api/tasks/${id}/restore`, { method: "POST" });
      if (action === "delete") await api(`/api/tasks/${id}`, { method: "DELETE" });
      toast("Tarefa atualizada.", "success");
      loadTasks();
      refreshStatus();
    } catch (err) {
      toast(err.message, "error");
    }
  }

  function initTasksView() {
    $("#tasks-filter").addEventListener("change", loadTasks);
    $("#tasks-new-btn").addEventListener("click", () => {
      $("#task-form").style.display = $("#task-form").style.display === "none" ? "flex" : "none";
    });
    $("#task-cancel-btn").addEventListener("click", () => { $("#task-form").style.display = "none"; });
    $("#task-save-btn").addEventListener("click", async () => {
      const title = $("#task-title").value.trim();
      if (!title) { toast("O título é obrigatório.", "error"); return; }
      try {
        await api("/api/tasks", {
          method: "POST",
          body: JSON.stringify({
            title,
            description: $("#task-description").value.trim(),
            date: $("#task-date").value || null,
            time: $("#task-time").value || null,
            priority: $("#task-priority").value,
          }),
        });
        $("#task-title").value = "";
        $("#task-description").value = "";
        $("#task-date").value = "";
        $("#task-time").value = "";
        $("#task-form").style.display = "none";
        toast("Tarefa criada.", "success");
        loadTasks();
        refreshStatus();
      } catch (err) {
        toast(err.message, "error");
      }
    });
  }

  // ---------------------------------------------------------
  // PROJETOS
  // ---------------------------------------------------------

  async function loadProjects() {
    try {
      const data = await api("/api/projects");
      renderProjects(data.projects);
      $("#projects-count").textContent = data.projects.length;
    } catch (err) {
      toast(err.message, "error");
    }
  }

  function renderProjects(projects) {
    const list = $("#projects-list");
    list.innerHTML = "";
    if (projects.length === 0) {
      list.innerHTML = `<div class="empty-state">Nenhum projeto ainda.</div>`;
      return;
    }
    projects.forEach((p) => {
      const activeTasks = (p.tasks || []).filter((t) => t.status !== "excluida");
      const card = document.createElement("div");
      card.className = "item-card";
      card.innerHTML = `
        <div class="item-top">
          <div class="item-title">${escapeHtml(p.name)}</div>
          <button class="btn small danger" data-act="delete">Excluir</button>
        </div>
        ${p.description ? `<div class="item-desc">${escapeHtml(p.description)}</div>` : ""}
        <div class="item-meta">
          <span>${activeTasks.length} tarefa(s)</span>
          <span>Progresso: ${p.progress}%</span>
        </div>
      `;
      card.querySelector('[data-act="delete"]').addEventListener("click", async () => {
        if (!confirm(`Excluir permanentemente o projeto "${p.name}"?`)) return;
        try {
          await api(`/api/projects/${p.id}`, { method: "DELETE" });
          toast("Projeto excluído.", "success");
          loadProjects();
          refreshStatus();
        } catch (err) {
          toast(err.message, "error");
        }
      });
      list.appendChild(card);
    });
  }

  function initProjectsView() {
    $("#projects-new-btn").addEventListener("click", () => {
      $("#project-form").style.display = $("#project-form").style.display === "none" ? "flex" : "none";
    });
    $("#project-cancel-btn").addEventListener("click", () => { $("#project-form").style.display = "none"; });
    $("#project-save-btn").addEventListener("click", async () => {
      const name = $("#project-name").value.trim();
      if (!name) { toast("O nome do projeto é obrigatório.", "error"); return; }
      try {
        await api("/api/projects", {
          method: "POST",
          body: JSON.stringify({
            name,
            description: $("#project-description").value.trim(),
            objectives: $("#project-objectives").value.trim(),
          }),
        });
        $("#project-name").value = "";
        $("#project-description").value = "";
        $("#project-objectives").value = "";
        $("#project-form").style.display = "none";
        toast("Projeto criado.", "success");
        loadProjects();
        refreshStatus();
      } catch (err) {
        toast(err.message, "error");
      }
    });
  }

  // ---------------------------------------------------------
  // MEMÓRIA
  // ---------------------------------------------------------

  async function loadMemory() {
    try {
      const data = await api("/api/memories");
      renderMemory(data.memories);
      $("#memory-count").textContent = data.memories.length;
    } catch (err) {
      toast(err.message, "error");
    }
  }

  function renderMemory(memories) {
    const list = $("#memory-list");
    list.innerHTML = "";
    if (memories.length === 0) {
      list.innerHTML = `<div class="empty-state">Nenhuma memória salva ainda.</div>`;
      return;
    }
    memories.forEach((m) => {
      const card = document.createElement("div");
      card.className = "item-card";
      card.innerHTML = `
        <div class="item-top">
          <span class="badge normal">${escapeHtml(m.category)}</span>
          <button class="btn small danger" data-act="delete">Excluir</button>
        </div>
        <div class="item-desc" style="color: var(--text);">${escapeHtml(m.content)}</div>
      `;
      card.querySelector('[data-act="delete"]').addEventListener("click", async () => {
        if (!confirm("Excluir esta memória?")) return;
        try {
          await api(`/api/memories/${m.id}`, { method: "DELETE" });
          toast("Memória excluída.", "success");
          loadMemory();
          refreshStatus();
        } catch (err) {
          toast(err.message, "error");
        }
      });
      list.appendChild(card);
    });
  }

  function initMemoryView() {
    $("#memory-new-btn").addEventListener("click", () => {
      $("#memory-form").style.display = $("#memory-form").style.display === "none" ? "flex" : "none";
    });
    $("#memory-cancel-btn").addEventListener("click", () => { $("#memory-form").style.display = "none"; });
    $("#memory-save-btn").addEventListener("click", async () => {
      const content = $("#memory-content").value.trim();
      if (!content) { toast("Escreva o que devo lembrar.", "error"); return; }
      try {
        await api("/api/memories", {
          method: "POST",
          body: JSON.stringify({ content, category: $("#memory-category").value }),
        });
        $("#memory-content").value = "";
        $("#memory-form").style.display = "none";
        toast("Memória salva.", "success");
        loadMemory();
        refreshStatus();
      } catch (err) {
        toast(err.message, "error");
      }
    });
    $("#memory-clear-btn").addEventListener("click", async () => {
      if (!confirm("Apagar TODAS as memórias? Esta ação não pode ser desfeita.")) return;
      try {
        await api("/api/memories/clear_all", { method: "POST" });
        toast("Todas as memórias foram apagadas.", "success");
        loadMemory();
        refreshStatus();
      } catch (err) {
        toast(err.message, "error");
      }
    });
  }

  // ---------------------------------------------------------
  // CALENDÁRIO
  // ---------------------------------------------------------

  async function loadCalendar() {
    try {
      const data = await api("/api/calendar");
      const badge = $("#calendar-google-status");
      badge.textContent = data.google_calendar.connected ? "google conectado" : "local";

      const list = $("#calendar-list");
      list.innerHTML = "";
      if (data.local_calendar.length === 0) {
        list.innerHTML = `<div class="empty-state">Nenhuma tarefa com data agendada.</div>`;
        return;
      }
      // Agrupa por data
      const byDate = {};
      data.local_calendar.forEach((t) => {
        (byDate[t.date] = byDate[t.date] || []).push(t);
      });
      Object.keys(byDate).sort().forEach((date) => {
        const group = document.createElement("div");
        group.innerHTML = `<div style="font-family: var(--font-ui); color: var(--cyan); font-size: 13px; margin: 8px 0 4px; letter-spacing: 0.5px;">${date}</div>`;
        byDate[date].forEach((t) => {
          const card = document.createElement("div");
          card.className = "item-card";
          card.innerHTML = `
            <div class="item-top">
              <div class="item-title">${escapeHtml(t.title)}</div>
              <span class="badge ${t.priority}">${priorityLabel(t.priority)}</span>
            </div>
            <div class="item-meta">${t.time ? `<span>🕐 ${t.time}</span>` : "<span>sem horário definido</span>"}</div>
          `;
          group.appendChild(card);
        });
        list.appendChild(group);
      });
    } catch (err) {
      toast(err.message, "error");
    }
  }

  // ---------------------------------------------------------
  // CONFIGURAÇÕES
  // ---------------------------------------------------------

  async function loadSettings() {
    try {
      const data = await api("/api/health");
      $("#settings-ai-model").textContent = data.ai_configured ? data.ai_model : "não configurado";
      $("#settings-history-limit").textContent = data.max_history_messages;
      $("#settings-voice-toggle").textContent = voiceOutputEnabled ? "Desativar" : "Ativar";
    } catch (err) {
      toast(err.message, "error");
    }
  }

  function initSettingsView() {
    $("#settings-voice-toggle").addEventListener("click", () => {
      $("#voice-output-toggle").click();
      $("#settings-voice-toggle").textContent = voiceOutputEnabled ? "Desativar" : "Ativar";
    });
  }

  // ---------------------------------------------------------
  // CONEXÕES
  // ---------------------------------------------------------

  const SERVICE_LABELS = {
    spotify: "Spotify",
    google_calendar: "Google Calendar",
    gmail: "Gmail",
    outlook: "Outlook",
    messages: "Mensagens",
  };

  async function loadConnections() {
    try {
      const data = await api("/api/connections");
      const list = $("#connections-list");
      list.innerHTML = "";
      data.connections.forEach((c) => {
        const row = document.createElement("div");
        row.className = "item-card";
        row.innerHTML = `
          <div class="item-top">
            <div class="item-title">${SERVICE_LABELS[c.service] || c.service}</div>
            <span class="badge ${c.connected ? "concluida" : "excluida"}">${c.connected ? "Conectado" : "Não conectado"}</span>
          </div>
        `;
        list.appendChild(row);
      });
      renderAsideConnections(data.connections);
    } catch (err) {
      toast(err.message, "error");
    }
  }

  function renderAsideConnections(connections) {
    const el = $("#aside-connections");
    el.innerHTML = "";
    connections.forEach((c) => {
      const row = document.createElement("div");
      row.className = "conn-row";
      row.innerHTML = `<span>${SERVICE_LABELS[c.service] || c.service}</span><span class="dot ${c.connected ? "on" : "off"}"></span>`;
      el.appendChild(row);
    });
  }

  // ---------------------------------------------------------
  // ATIVIDADE
  // ---------------------------------------------------------

  // Não existe endpoint de log de atividade exposto pelo backend nesta
  // instalação (o modelo Log existe, mas não há rota /api/... para lê-lo).
  // Por isso, em vez de inventar registros, mostramos isso com honestidade.
  let activityLoaded = false;
  function loadActivity() {
    if (activityLoaded) return;
    activityLoaded = true;
    const el = $("#activity-list");
    if (!el) return;
    el.innerHTML = `<div class="empty-state">Nenhum endpoint de atividade disponível nesta instalação.<br>O backend registra logs internamente, mas ainda não expõe uma rota de leitura para o frontend.</div>`;
  }

  // ---------------------------------------------------------
  // SUGESTÕES RÁPIDAS DO CHAT
  // ---------------------------------------------------------

  function initQuickSuggestions() {
    $$(".suggestion-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        const text = chip.dataset.suggestion || chip.textContent.trim();
        sendMessage(text);
      });
    });
  }

  // ---------------------------------------------------------
  // RELÓGIO DA TOPBAR
  // ---------------------------------------------------------

  function initClock() {
    const el = $("#header-clock");
    if (!el) return;
    function tick() {
      el.textContent = new Date().toLocaleTimeString("pt-BR", { hour12: false });
    }
    tick();
    setInterval(tick, 1000);
  }

  // ---------------------------------------------------------
  // ESTUDO
  // ---------------------------------------------------------

  function initStudyView() {
    const btn = $("#study-plan-btn");
    if (!btn) return;
    btn.addEventListener("click", () => {
      $('.nav-btn[data-view="central"]').click();
      sendMessage("Monte um plano de estudos para mim.");
    });
  }

  // ---------------------------------------------------------
  // STATUS GERAL (header + aside)
  // ---------------------------------------------------------

  async function refreshStatus() {
    try {
      const data = await api("/api/health");

      const aiChip = $("#chip-ai");
      $("#chip-ai-text").textContent = data.ai_configured ? `IA online (${data.ai_model})` : "IA offline";
      aiChip.querySelector(".dot").className = `dot ${data.ai_configured ? "on" : "off"}`;

      $("#chip-tasks-text").textContent = `${data.tasks_active} tarefa(s)`;

      $("#aside-ai-model").textContent = data.ai_configured ? data.ai_model : "não configurado";
      $("#aside-tasks").textContent = data.tasks_active;
      $("#aside-projects").textContent = data.projects_count;
      $("#aside-memories").textContent = data.memories_count;

      const dashStatus = $("#dash-system-status");
      const dashSub = dashStatus ? dashStatus.nextElementSibling : null;
      if (dashStatus && dashSub) {
        dashStatus.textContent = data.ai_configured ? "ONLINE" : "LIMITADO";
        dashSub.textContent = data.ai_configured ? "Operacional" : "IA não configurada";
      }

      renderAsideConnections(data.connections);
    } catch (err) {
      // Silencioso: não interrompe o uso do app se o status falhar momentaneamente.
      console.warn("Falha ao atualizar status:", err.message);
    }
  }

  // ---------------------------------------------------------
  // INIT
  // ---------------------------------------------------------

  function init() {
    initNav();
    initTasksView();
    initProjectsView();
    initMemoryView();
    initSettingsView();
    initStudyView();
    initQuickSuggestions();
    initClock();
    initSpeech();
    initVoiceOutputToggle();
    loadHistory();
    refreshStatus();
    setInterval(refreshStatus, 20000);
  }

  document.addEventListener("DOMContentLoaded", init);
})();
