"""
N.A.S.H - Pesquisa em artigos científicos (Consensus, via Composio).

NÃO é busca na internet. O Consensus procura em artigos revisados por pares --
o que serve muito bem a um parceiro de estudos de exatas (resposta com fonte
citável) e não serve para "que horas abre a loja". A ferramenta se chama
`tool_search_papers` justamente para o modelo não achar que tem web aberta.

POR QUE ENXUGAR É OBRIGATÓRIO AQUI: uma busca real devolveu 43.622 caracteres
(20 resultados com resumo inteiro) -- cerca de 11 mil tokens, quase o dobro do
teto de 6.000 tokens/minuto da camada gratuita do provedor. Mandar isso para o
modelo derrubaria a resposta em vez de embasá-la. Por isso ficam poucos
resultados e um trecho de cada resumo.
"""
import logging
import os

import requests

logger = logging.getLogger("nash.pesquisa")

BASE_URL = "https://backend.composio.dev/api/v3"
TIMEOUT = 60

# Medidos contra a resposta real: 5 artigos com 320 caracteres de resumo dão
# ~2.500 caracteres no total, folgados dentro do orçamento.
MAX_RESULTADOS = 5
MAX_RESUMO = 320


def esta_configurado() -> bool:
    return bool(
        (os.environ.get("COMPOSIO_API_KEY") or "").strip()
        and (os.environ.get("COMPOSIO_USER_ID") or "").strip()
    )


def _texto(valor, limite: int) -> str:
    texto = " ".join(str(valor or "").split())
    if len(texto) <= limite:
        return texto
    # Corta na última palavra inteira: cortar no meio de uma palavra faz o
    # modelo tratar o fragmento como termo técnico.
    return texto[:limite].rsplit(" ", 1)[0] + "…"


def _enxugar(bruto: dict) -> list[dict]:
    """
    Fica só o que embasa uma resposta: o que o artigo conclui, quem publicou,
    quando, e o link para conferir.

    Prefere `takeaway` -- uma síntese de uma linha que o próprio Consensus
    produz -- ao resumo completo. É mais curto E mais útil: o resumo cortado
    em 320 caracteres costuma terminar antes da conclusão, que é justamente a
    parte que interessa.
    """
    artigos = []
    for item in (bruto.get("results") or [])[:MAX_RESULTADOS]:
        autores = item.get("authors") or []
        artigos.append({
            "titulo": _texto(item.get("title"), 160),
            "ano": item.get("publish_year"),
            "publicacao": _texto(item.get("journal_name"), 80),
            "autor": _texto(autores[0] if autores else "", 60) or None,
            "conclusao": _texto(item.get("takeaway") or item.get("abstract"), MAX_RESUMO),
            "tipo_de_estudo": item.get("study_type") or None,
            "citacoes": item.get("citation_count"),
            "link": item.get("url") or None,
        })
    return artigos


def buscar_artigos(query: str, ano_minimo: int | None = None) -> dict:
    """
    Procura artigos e devolve o essencial. Nunca levanta exceção: o agente
    trata a resposta como resultado de ferramenta.
    """
    query = (query or "").strip()
    if not query:
        return {"ok": False, "message": "Diga o que devo procurar."}

    if not esta_configurado():
        return {
            "ok": False,
            "message": "A pesquisa em artigos não está configurada neste servidor.",
        }

    argumentos = {"query": query}
    if ano_minimo:
        argumentos["year_min"] = int(ano_minimo)

    try:
        resposta = requests.post(
            f"{BASE_URL}/tools/execute/CONSENSUS_SEARCH_PAPERS",
            headers={"x-api-key": os.environ["COMPOSIO_API_KEY"].strip()},
            json={
                "user_id": os.environ["COMPOSIO_USER_ID"].strip(),
                "arguments": argumentos,
            },
            timeout=TIMEOUT,
        )
        dados = resposta.json()
    except Exception:  # noqa: BLE001 — falha de rede vira mensagem, não traceback
        logger.exception("Falha ao pesquisar artigos")
        return {
            "ok": False,
            "message": "Não consegui alcançar o serviço de pesquisa agora.",
        }

    if resposta.status_code != 200 or not dados.get("successful"):
        logger.error("Consensus recusou a busca: %s", str(dados.get("error"))[:300])
        return {"ok": False, "message": "O serviço de pesquisa recusou a consulta."}

    artigos = _enxugar(dados.get("data") or {})
    if not artigos:
        return {
            "ok": True,
            "artigos": [],
            "message": f"Nenhum artigo encontrado para “{query}”.",
        }

    return {
        "ok": True,
        "artigos": artigos,
        "aviso": "Fonte: artigos científicos (Consensus). Não é busca na internet aberta.",
    }
