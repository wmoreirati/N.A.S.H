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

  // A sintese so pode ser iniciada a partir de um gesto do usuario no Chrome
  // do Android: uma fala disparada dentro do retorno de um fetch e engolida em
  // silencio. Falando uma vez (vazio) durante o toque, o navegador libera as
  // falas seguintes daquela aba.
  let vozLiberada = false;

  function liberarVoz() {
    if (vozLiberada || !window.speechSynthesis) return;
    try {
      const mudo = new SpeechSynthesisUtterance("");
      mudo.volume = 0;
      window.speechSynthesis.speak(mudo);
      vozLiberada = true;
    } catch (_) {
      /* navegador sem sintese: o modo segue funcionando por texto */
    }
  }

  function vozPortugues() {
    const vozes = window.speechSynthesis.getVoices() || [];
    return vozes.find((v) => v.lang && v.lang.toLowerCase().startsWith("pt-br"))
        || vozes.find((v) => v.lang && v.lang.toLowerCase().startsWith("pt"))
        || null;
  }

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

      // Resolve UMA vez, venha de onde vier: fim normal, erro, ou o cao de
      // guarda. Sem isto, uma fala que nunca comeca trava o ciclo inteiro --
      // e o pior e que trava calado.
      let encerrado = false;
      let guarda = null;
      const terminar = () => {
        if (encerrado) return;
        encerrado = true;
        if (guarda) clearInterval(guarda);
        resolve();
      };

      const fala = new SpeechSynthesisUtterance(limpo);
      fala.lang = "pt-BR";
      const voz = vozPortugues();
      if (voz) fala.voice = voz;
      fala.onend = terminar;
      fala.onerror = terminar;

      window.speechSynthesis.cancel();
      definirEstado("N.A.S.H respondendo…", "falando");
      window.speechSynthesis.speak(fala);

      // Cao de guarda: se em 1,5s nada comecou a tocar, a sintese foi engolida
      // (tipicamente por falta de gesto do usuario) e seguimos sem ela. Depois
      // de comecar, acompanha ate parar de falar.
      let carencia = 0;
      guarda = setInterval(() => {
        carencia += 300;
        const falando = window.speechSynthesis.speaking;
        if (!falando && carencia >= 1500) terminar();
        if (falando && carencia > 1500 && !window.speechSynthesis.pending) {
          // Chrome corta falas longas por volta dos 15s; cutucar mantem viva.
          window.speechSynthesis.pause();
          window.speechSynthesis.resume();
        }
        if (carencia > 120000) terminar();
      }, 300);
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
      // O texto vai para a tela ANTES de falar. Se a sintese de voz falhar (o
      // navegador pode recusar sem avisar), a resposta ainda aparece -- antes
      // era o contrário, e uma fala engolida deixava a tela muda tambem.
      transcricao.textContent = texto;
      await falar(texto);
    } catch (_) {
      const erro = "Não consegui falar com o servidor.";
      transcricao.textContent = erro;
      await falar(erro);
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
    // Este clique e o gesto do usuario: e aqui, e so aqui, que da para
    // destravar a sintese de voz para o resto da conversa.
    liberarVoz();
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

    // Abrir tambem e um gesto: aproveita para destravar a fala e pedir a
    // lista de vozes, que em varios navegadores so chega de forma assincrona.
    liberarVoz();
    if (window.speechSynthesis) window.speechSynthesis.getVoices();

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
