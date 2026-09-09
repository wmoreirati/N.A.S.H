/* N.A.S.H — porta de entrada (login e pedido de acesso). */
(function () {
  "use strict";

  const $ = (sel) => document.querySelector(sel);

  const abaEntrar = $("#aba-entrar");
  const abaPedir = $("#aba-pedir");
  const formEntrar = $("#form-entrar");
  const formPedir = $("#form-pedir");
  const formEsqueci = $("#form-esqueci");
  const aviso = $("#aviso");

  function mostrarAviso(texto, tipo) {
    aviso.textContent = texto;
    aviso.className = "aviso " + (tipo || "erro");
  }

  function limparAviso() {
    aviso.textContent = "";
    aviso.className = "aviso";
  }

  function selecionarAba(destino) {
    const entrar = destino === "entrar";
    abaEntrar.setAttribute("aria-selected", String(entrar));
    abaPedir.setAttribute("aria-selected", String(!entrar));
    formEntrar.hidden = !entrar;
    formPedir.hidden = entrar;
    // Recuperação é um desvio dentro de "Entrar", não uma terceira aba:
    // trocar de aba sempre volta ao formulário principal.
    formEsqueci.hidden = true;
    limparAviso();
  }

  function mostrarEsqueci(mostrar) {
    formEntrar.hidden = mostrar;
    formEsqueci.hidden = !mostrar;
    limparAviso();
  }

  abaEntrar.addEventListener("click", () => selecionarAba("entrar"));
  abaPedir.addEventListener("click", () => selecionarAba("pedir"));

  async function enviar(url, corpo, botao) {
    botao.disabled = true;
    try {
      const resp = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(corpo),
      });
      // Resposta não-JSON (proxy, erro de plataforma) não pode virar
      // "TypeError" cru na cara de quem só queria entrar.
      let dados = {};
      try { dados = await resp.json(); } catch (_) { /* mantém {} */ }
      return { ok: resp.ok, dados };
    } catch (_) {
      return { ok: false, dados: { error: "Sem conexão com o servidor. Tente de novo." } };
    } finally {
      botao.disabled = false;
    }
  }

  formEntrar.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    limparAviso();
    const { ok, dados } = await enviar(
      "/api/auth/login",
      { email: $("#entrar-email").value, senha: $("#entrar-senha").value },
      formEntrar.querySelector("button[type=submit]")
    );
    if (ok && dados.ok) {
      window.location.href = "/";
      return;
    }
    mostrarAviso(dados.error || "Não foi possível entrar.", "erro");
  });

  $("#abrir-esqueci").addEventListener("click", () => mostrarEsqueci(true));
  $("#voltar-entrar").addEventListener("click", () => mostrarEsqueci(false));

  formEsqueci.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    limparAviso();
    const { ok, dados } = await enviar(
      "/api/auth/esqueci",
      { email: $("#esqueci-email").value },
      formEsqueci.querySelector("button[type=submit]")
    );
    if (ok && dados.ok) {
      formEsqueci.reset();
      // A resposta é a mesma exista a conta ou não -- de propósito, para esta
      // tela não virar uma forma de descobrir quem tem acesso.
      mostrarAviso(dados.mensagem || "Link enviado.", "ok");
      return;
    }
    mostrarAviso(dados.error || "Não foi possível enviar o link.", "erro");
  });

  formPedir.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    limparAviso();
    const { ok, dados } = await enviar(
      "/api/auth/registrar",
      {
        nome: $("#pedir-nome").value,
        email: $("#pedir-email").value,
        senha: $("#pedir-senha").value,
      },
      formPedir.querySelector("button[type=submit]")
    );

    if (ok && dados.ok) {
      // O administrador entra direto; qualquer outra pessoa fica aguardando.
      if (dados.liberado) {
        window.location.href = "/";
        return;
      }
      formPedir.reset();
      mostrarAviso(dados.mensagem || "Pedido enviado.", "ok");
      return;
    }
    mostrarAviso(dados.error || "Não foi possível enviar o pedido.", "erro");
  });
})();
