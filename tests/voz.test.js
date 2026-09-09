/* ============================================================
   N.A.S.H — Testes do modo de voz (roda com: node --test tests/)

   Duas funções de static/voz.js decidem coisas com consequência e não tinham
   teste permanente:

   1. `interpretarResposta` — é a ÚNICA coisa entre falar e executar uma ação
      de escrita. Entender "não" como "sim" cria tarefa que a pessoa recusou.

   2. a limpeza do texto antes de falar — sem ela o sintetizador pronuncia
      "aspas", "asterisco", "hashtag".

   Os dois trechos são EXTRAÍDOS do arquivo real em vez de copiados. Teste
   sobre uma cópia passa a valer para a cópia, não para o que está no ar.
   ============================================================ */
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const FONTE = fs.readFileSync(
  path.join(__dirname, "..", "static", "voz.js"), "utf8"
);

/** Recorta um trecho do voz.js e devolve como função executável. */
function extrair(inicio, fim, corpo) {
  const i = FONTE.indexOf(inicio);
  const j = FONTE.indexOf(fim, i);
  assert.ok(i !== -1 && j !== -1,
    `não achei o trecho ${inicio!== -1 ? JSON.stringify(inicio) : ""} em voz.js — ` +
    "o arquivo mudou e este teste precisa acompanhar");
  return FONTE.slice(i, j) + corpo;
}

// ---------------------------------------------------------------------------
// interpretarResposta
// ---------------------------------------------------------------------------

const interpretar = new Function(
  "texto",
  extrair(
    "  const SIM = [",
    "  function limparConfirmacao",
    "\n  return interpretarResposta(texto);"
  )
);

test("confirma com as palavras usuais", () => {
  for (const frase of ["sim", "Sim!", "confirmar", "confirma", "pode",
                       "ok", "claro", "isso", "positivo"]) {
    assert.strictEqual(interpretar(frase), true, frase);
  }
});

test("nega com as palavras usuais", () => {
  for (const frase of ["não", "nao", "Não.", "cancelar", "cancela",
                       "negativo", "esquece", "deixa"]) {
    assert.strictEqual(interpretar(frase), false, frase);
  }
});

test("negação que CONTÉM palavra de confirmação continua sendo negação", () => {
  // O caso perigoso: "pode" está dentro de "não pode". Se a afirmação fosse
  // testada primeiro, uma recusa viraria execução.
  for (const frase of ["não pode", "nao pode", "não, pode deixar",
                       "melhor não", "não confirma"]) {
    assert.strictEqual(interpretar(frase), false, frase);
  }
});

test("hesitação com 'não' dentro é lida como negação", () => {
  // "não sei" contém "não". Ler como negação é o lado seguro do erro: não
  // executa nada e a pessoa pode pedir de novo.
  assert.strictEqual(interpretar("não sei"), false);
});

test("resposta que não dá para entender devolve null, nunca um palpite", () => {
  // null faz o modo perguntar de novo. Qualquer palpite aqui executaria ou
  // descartaria uma ação sem a pessoa ter decidido.
  for (const frase of ["abacaxi", "talvez", "", "   ", "hmmm", "sei la"]) {
    assert.strictEqual(interpretar(frase), null, JSON.stringify(frase));
  }
});

test("acento não muda o resultado", () => {
  assert.strictEqual(interpretar("não"), interpretar("nao"));
});

// ---------------------------------------------------------------------------
// Limpeza do texto falado
// ---------------------------------------------------------------------------

const limpar = new Function(
  "texto",
  "return texto" +
    extrair("const limpo = texto", ".trim();", ".trim();").replace(
      "const limpo = texto", ""
    )
);

test("não sobra pontuação decorativa para o sintetizador pronunciar", () => {
  const casos = [
    ['Vou criar a tarefa: "comprar pilhas". Confirmar?', '"'],
    ["O resultado é **100**.", "*"],
    ["# Título", "#"],
    ["> citação", ">"],
    ["tabela | com | pipes", "|"],
  ];
  for (const [entrada, proibido] of casos) {
    assert.ok(!limpar(entrada).includes(proibido),
      `${JSON.stringify(entrada)} -> ${JSON.stringify(limpar(entrada))}`);
  }
});

test("marcadores de lista e numeração somem, o conteúdo fica", () => {
  const saida = limpar("- item um\n- item dois");
  assert.ok(!saida.includes("-"), saida);
  assert.ok(saida.includes("item um") && saida.includes("item dois"), saida);

  const numerada = limpar("1. primeiro\n2. segundo");
  assert.ok(numerada.includes("primeiro") && numerada.includes("segundo"), numerada);
});

test("link vira o texto, sem ler a URL em voz alta", () => {
  const saida = limpar("Veja [a documentação](https://exemplo.com/x) aqui.");
  assert.ok(saida.includes("a documentação"), saida);
  assert.ok(!saida.includes("http"), saida);
});

test("fórmula LaTeX não é soletrada", () => {
  const saida = limpar("A energia é $$E = mc^2$$ nesse caso");
  assert.ok(!saida.includes("$"), saida);
  assert.ok(saida.includes("fórmula"), saida);
});

test("texto comum atravessa sem estrago", () => {
  const frase = "Cem. Precisa de mais alguma coisa?";
  assert.strictEqual(limpar(frase), frase);
});
