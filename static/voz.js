/* ============================================================
   N.A.S.H — Modo de conversa por voz.

   Abre pelo núcleo (logo) do cabeçalho e ocupa a tela inteira: fala,
   escuta e responde em voz, num ciclo contínuo até a pessoa fechar.

   Como funciona, e por que assim:

   - Reconhecimento: Web Speech API (`SpeechRecognition`). É do navegador,
     não custa nada e não precisa de chave. Só existe em navegadores
     baseados em Chromium (Chrome, Edge, Chrome no Android) — no Firefox
     não existe. Quando falta, o modo avisa em vez de fingir que escutou.

   - Orbe reagindo à voz: o volume vem de um `AnalyserNode` do Web Audio
     sobre o mesmo microfone. Em alguns aparelhos Android abrir o
     getUserMedia junto do reconhecimento atrapalha um ou outro, então a
     animação por volume é OPCIONAL: se o microfone não puder ser aberto
     em paralelo, o orbe cai para uma pulsação por tempo e a conversa
     segue funcionando.
   ============================================================ */
(function () {
  "use strict";

  const $ = (sel) => document.querySelector(sel);

  const overlay = $("#voz-overlay");
  if (!overlay) return;

  const nucleo = $("#core-indicator");
  const orbe = $("#voz-orbe");
  const estado = $("#voz-estado");
  const transcricao = $("#voz-transcricao");
  const botaoMic = $("#voz-microfone");
  const botaoFechar = $("#voz-fechar");

  const Reconhecimento =
    window.SpeechRecognition || window.webkitSpeechRecognition;

  let reconhecedor = null;
  let escutando = false;
  let aberto = false;

  // Áudio para a animação — tudo opcional, ver cabeçalho.
  let contextoAudio = null;
  let analisador = null;
  let fluxoMic = null;
  let quadro = null;

  // ----------------------------------------------------------------
  // Aparência
  // ----------------------------------------------------------------

  function definirEstado(texto, classe) {
    estado.textContent = texto;
    orbe.className = "voz-orbe" + (classe ? " " + classe : "");
  }

  function animarPorVolume() {
    if (!analisador) return;
    const dados = new Uint8Array(analisador.frequencyBinCount);

    const passo = () => {
      if (!aberto) return;
      analisador.getByteFrequencyData(dados);
      let soma = 0;
      for (let i = 0; i < dados.length; i++) soma += dados[i];
      const media = soma / dados.length / 255; // 0..1
      // Piso em 1 para o orbe nunca "sumir" no silêncio.
      orbe.style.setProperty("--intensidade", (1 + media * 0.85).toFixed(3));
      quadro = requestAnimationFrame(passo);
    };
    quadro = requestAnimationFrame(passo);
  }

  async function ligarAnalisadorDeVolume() {
    try {
      fluxoMic = await navigator.mediaDevices.getUserMedia({ audio: true });
      contextoAudio = new (window.AudioContext || window.webkitAudioContext)();
      const fonte = contextoAudio.createMediaStreamSource(fluxoMic);
      analisador = contextoAudio.createAnalyser();
      analisador.fftSize = 256;
      fonte.connect(analisador);
      animarPorVolume();
    } catch (_) {
      // Sem permissão ou microfone ocupado: a conversa continua, só que o
      // orbe pulsa por tempo (classe CSS) em vez de por volume.
      orbe.classList.add("sem-volume");
    }
  }

  function desligarAnalisadorDeVolume() {
    if (quadro) cancelAnimationFrame(quadro);
    quadro = null;
    if (fluxoMic) fluxoMic.getTracks().forEach((t) => t.stop());
    fluxoMic = null;
    if (contextoAudio && contextoAudio.state !== "closed") contextoAudio.close();
    contextoAudio = null;
    analisador = null;
    orbe.style.removeProperty("--intensidade");
  }

  // ----------------------------------------------------------------
  // Falar
  // ----------------------------------------------------------------

  function falar(texto) {
    return new Promise((resolve) => {
      if (!window.speechSynthesis || !texto) return resolve();

      // Remove marcação e LaTeX: lidos em voz alta viram ruído.
      const limpo = texto
        .replace(/\$\$[\s\S]*?\$\$/g, " fórmula ")
        .replace(/\$[^$]*\$/g, " fórmula ")
        .replace(/[*_`#>]/g, "")
        .replace(/\s+/g, " ")
        .trim();

      if (!limpo) return resolve();

      const fala = new SpeechSynthesisUtterance(limpo);
      fala.lang = "pt-BR";
      fala.onend = resolve;
      fala.onerror = resolve;
      window.speechSynthesis.cancel();
      definirEstado("N.A.S.H respondendo…", "falando");
      window.speechSynthesis.speak(fala);
    });
  }

  // ----------------------------------------------------------------
  // Enviar ao assistente
  // ----------------------------------------------------------------

  async function perguntar(mensagem) {
    definirEstado("Pensando…", "pensando");
    try {
      const resp = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: mensagem }),
      });

      if (resp.status === 401) {
        definirEstado("Sessão encerrada. Entre de novo.", "erro");
        window.location.href = "/login";
        return;
      }

      const dados = await resp.json();

      // Ação que exige confirmação não pode ser confirmada por voz: o cartão
      // Confirmar/Cancelar é a garantia central do projeto e vive na tela.
      if (dados.type === "pending_action") {
        await falar(
          "Preparei uma ação que precisa da sua confirmação. " +
          "Vou fechar a voz para você conferir na tela."
        );
        fechar();
        return;
      }

      const texto = dados.text || "Não consegui responder agora.";
      await falar(texto);
      transcricao.textContent = texto;
    } catch (_) {
      await falar("Não consegui falar com o servidor.");
    }

    if (aberto) definirEstado("Toque para falar", "");
  }

  // ----------------------------------------------------------------
  // Escutar
  // ----------------------------------------------------------------

  function prepararReconhecedor() {
    const r = new Reconhecimento();
    r.lang = "pt-BR";
    r.interimResults = true;
    r.continuous = false;

    r.onstart = () => {
      escutando = true;
      definirEstado("Ouvindo…", "ouvindo");
    };

    r.onresult = (evento) => {
      let parcial = "";
      let final = "";
      for (let i = evento.resultIndex; i < evento.results.length; i++) {
        const trecho = evento.results[i][0].transcript;
        if (evento.results[i].isFinal) final += trecho;
        else parcial += trecho;
      }
      transcricao.textContent = final || parcial;
      if (final.trim()) perguntar(final.trim());
    };

    r.onerror = (evento) => {
      escutando = false;
      const motivo = {
        "not-allowed": "Permissão de microfone negada.",
        "service-not-allowed": "Permissão de microfone negada.",
        "no-speech": "Não ouvi nada. Toque para tentar de novo.",
        "audio-capture": "Nenhum microfone encontrado.",
      }[evento.error] || "Falha no reconhecimento de voz.";
      definirEstado(motivo, "erro");
    };

    r.onend = () => {
      escutando = false;
      // Só volta para "pronto" se não estivermos pensando ou falando.
      if (aberto && orbe.classList.contains("ouvindo")) {
        definirEstado("Toque para falar", "");
      }
    };

    return r;
  }

  function alternarEscuta() {
    if (!Reconhecimento) return;
    if (escutando) {
      reconhecedor.stop();
      return;
    }
    window.speechSynthesis && window.speechSynthesis.cancel();
    transcricao.textContent = "";
    try {
      reconhecedor.start();
    } catch (_) {
      // start() durante uma sessão ainda ativa lança; ignorar é o certo.
    }
  }

  // ----------------------------------------------------------------
  // Abrir e fechar
  // ----------------------------------------------------------------

  function abrir() {
    aberto = true;
    overlay.hidden = false;
    overlay.setAttribute("aria-hidden", "false");
    document.body.classList.add("voz-ativa");

    if (!Reconhecimento) {
      definirEstado(
        "Este navegador não reconhece voz. Use o Chrome ou o Edge.",
        "erro"
      );
      botaoMic.disabled = true;
      return;
    }

    if (!reconhecedor) reconhecedor = prepararReconhecedor();
    definirEstado("Toque para falar", "");
    ligarAnalisadorDeVolume();
  }

  function fechar() {
    aberto = false;
    overlay.hidden = true;
    overlay.setAttribute("aria-hidden", "true");
    document.body.classList.remove("voz-ativa");
    if (reconhecedor && escutando) reconhecedor.stop();
    if (window.speechSynthesis) window.speechSynthesis.cancel();
    desligarAnalisadorDeVolume();
  }

  // ----------------------------------------------------------------
  // Ligações
  // ----------------------------------------------------------------

  if (nucleo) {
    nucleo.style.cursor = "pointer";
    nucleo.setAttribute("role", "button");
    nucleo.setAttribute("tabindex", "0");
    nucleo.setAttribute("aria-label", "Abrir conversa por voz");
    nucleo.addEventListener("click", abrir);
    nucleo.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        abrir();
      }
    });
  }

  botaoMic.addEventListener("click", alternarEscuta);
  orbe.addEventListener("click", alternarEscuta);
  botaoFechar.addEventListener("click", fechar);

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && aberto) fechar();
  });
})();
