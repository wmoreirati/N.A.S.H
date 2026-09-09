"""
N.A.S.H - Integrações externas via Composio.

O Composio cuida do OAuth de Gmail, Google Calendar, Drive, Docs, Sheets,
Notion e YouTube. Isso resolve um problema concreto: sem ele, usar Gmail
exigiria um aplicativo Google próprio, com verificação e auditoria de
segurança anual. Aqui o consentimento passa pelo aplicativo do Composio.

DUAS DECISÕES DE ESCOPO, ambas deliberadas:

1. Nem toda ação entra. Os serviços conectados somam ~500 ações; o esquema
   das 21 ferramentas nativas já custa 1.789 tokens EM TODA MENSAGEM, e o
   Groq gratuito corta em 6.000 tokens por minuto. Expor tudo estouraria o
   limite a cada pergunta. O catálogo abaixo é curado à mão.

2. Supabase e GitHub ficam de fora mesmo estando conectados. O Supabase é o
   banco do próprio N.A.S.H — dar acesso a ele pelo chat permitiria alterar
   tarefas e memórias POR FORA da validação e do cartão de confirmação, que
   é justamente a garantia central deste projeto.

Toda ação que escreve entra no fluxo de confirmação como qualquer outra:
o modelo propõe, o sistema intercepta, o usuário confirma.
"""
import os
import json
import logging
from pathlib import Path

import requests

from backend.security import permissions

logger = logging.getLogger("nash.tools.composio")

BASE_URL = "https://backend.composio.dev/api/v3"
TIMEOUT = 45

# Arquivo com os esquemas já baixados. Ler daqui em vez de consultar a API na
# subida evita uma ida à rede a cada partida a frio de função serverless.
# Regerado por `python scripts/sync_composio_tools.py`.
CATALOGO_PATH = Path(__file__).resolve().parent.parent / "ai" / "composio_catalog.json"

# slug -> categoria de permissão. Leitura executa direto; o resto pede confirmação.
ACOES = {
    # --- Gmail ---
    "GMAIL_FETCH_EMAILS":                 permissions.READ,
    "GMAIL_SEND_EMAIL":                   permissions.EMAIL,
    "GMAIL_CREATE_EMAIL_DRAFT":           permissions.EMAIL,

    # --- Google Calendar ---
    "GOOGLECALENDAR_EVENTS_LIST":         permissions.READ,
    "GOOGLECALENDAR_FIND_FREE_SLOTS":     permissions.READ,
    "GOOGLECALENDAR_CREATE_EVENT":        permissions.CALENDAR,
    "GOOGLECALENDAR_QUICK_ADD":           permissions.CALENDAR,

    # --- Google Drive ---
    "GOOGLEDRIVE_LIST_FILES":             permissions.READ,
    "GOOGLEDRIVE_FIND_FILE":              permissions.READ,

    # --- Google Docs ---
    "GOOGLEDOCS_SEARCH_DOCUMENTS":        permissions.READ,
    "GOOGLEDOCS_GET_DOCUMENT_BY_ID":      permissions.READ,
    "GOOGLEDOCS_CREATE_DOCUMENT_MARKDOWN": permissions.FILES,

    # --- Google Sheets ---
    "GOOGLESHEETS_SEARCH_SPREADSHEETS":   permissions.READ,
    "GOOGLESHEETS_BATCH_GET":             permissions.READ,

    # --- Notion ---
    "NOTION_SEARCH_NOTION_PAGE":          permissions.READ,
    "NOTION_FETCH_DATA":                  permissions.READ,

    # --- YouTube (útil para estudo) ---
    "YOUTUBE_SEARCH_YOU_TUBE":            permissions.READ,
    "YOUTUBE_LOAD_CAPTIONS":              permissions.READ,
}

# Texto do cartão de confirmação. Sem isto, a pessoa veria o slug cru.
DESCRICOES = {
    "GMAIL_SEND_EMAIL":                    "enviar um e-mail pelo Gmail",
    "GMAIL_CREATE_EMAIL_DRAFT":            "criar um rascunho de e-mail no Gmail",
    "GOOGLECALENDAR_CREATE_EVENT":         "criar um evento no Google Agenda",
    "GOOGLECALENDAR_QUICK_ADD":            "criar um evento rápido no Google Agenda",
    "GOOGLEDOCS_CREATE_DOCUMENT_MARKDOWN": "criar um documento no Google Docs",
}

_cache_schemas = None


def is_configured() -> bool:
    return bool((os.environ.get("COMPOSIO_API_KEY") or "").strip())


def _user_id() -> str:
    return (os.environ.get("COMPOSIO_USER_ID") or "").strip()


def get_schemas() -> list[dict]:
    """
    Esquemas das ações curadas, no formato de function calling.

    Devolve lista vazia (sem levantar exceção) quando o Composio não está
    configurado ou o catálogo não foi gerado — uma integração externa
    indisponível não pode impedir o assistente de funcionar.
    """
    global _cache_schemas
    if _cache_schemas is not None:
        return _cache_schemas

    if not is_configured() or not CATALOGO_PATH.exists():
        _cache_schemas = []
        return _cache_schemas

    try:
        dados = json.loads(CATALOGO_PATH.read_text(encoding="utf-8"))
        _cache_schemas = [t for t in dados.get("tools", []) if t["function"]["name"] in ACOES]
    except Exception:  # noqa: BLE001
        logger.exception("Catálogo do Composio ilegível — integrações desligadas nesta execução")
        _cache_schemas = []

    return _cache_schemas


def nomes_disponiveis() -> set[str]:
    return {t["function"]["name"] for t in get_schemas()}


def descreve(slug: str, args: dict) -> str:
    """Frase do cartão de confirmação para uma ação externa."""
    base = DESCRICOES.get(slug)
    if not base:
        base = f"executar {slug} em um serviço externo"

    detalhe = ""
    for campo in ("recipient_email", "to", "summary", "title", "subject", "text"):
        valor = args.get(campo)
        if valor:
            detalhe = f' — "{str(valor)[:70]}"'
            break
    return f"Vou {base}{detalhe}. Confirmar?"


def executar(slug: str, args: dict) -> dict:
    """
    Executa uma ação no Composio.

    Nunca levanta exceção para fora: devolve sempre um dicionário com `ok`,
    porque o agente trata a resposta como resultado de ferramenta.
    """
    if not is_configured():
        return {"ok": False, "message": "COMPOSIO_API_KEY não configurada neste servidor."}

    usuario = _user_id()
    if not usuario:
        return {
            "ok": False,
            "message": (
                "COMPOSIO_USER_ID não configurada. Sem ela o Composio não sabe "
                "de qual conta conectada estamos falando."
            ),
        }

    if slug not in ACOES:
        return {"ok": False, "message": f"Ação '{slug}' não faz parte do catálogo habilitado."}

    try:
        resp = requests.post(
            f"{BASE_URL}/tools/execute/{slug}",
            headers={
                "x-api-key": os.environ["COMPOSIO_API_KEY"].strip(),
                "Content-Type": "application/json",
            },
            json={"user_id": usuario, "arguments": args or {}},
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.error("Falha de rede ao chamar o Composio (%s): %s", slug, exc)
        return {"ok": False, "message": "Não foi possível contatar o serviço externo agora."}

    if resp.status_code >= 400:
        logger.error("Composio devolveu %s para %s: %s", resp.status_code, slug, resp.text[:400])
        if resp.status_code in (401, 403):
            return {"ok": False, "message": "O Composio recusou a credencial deste servidor."}
        return {"ok": False, "message": f"O serviço externo recusou a ação ({resp.status_code})."}

    try:
        dados = resp.json()
    except ValueError:
        return {"ok": False, "message": "O serviço externo devolveu uma resposta ilegível."}

    # O Composio responde 200 mesmo quando a ação falhou; quem diz a verdade
    # é o campo `successful`.
    if dados.get("successful") is False:
        erro = dados.get("error") or "motivo não informado"
        return {"ok": False, "message": f"A ação não foi concluída: {erro}"}

    return {"ok": True, "data": dados.get("data")}


def contas_ativas(verificar_tls: bool = True) -> list[str]:
    """
    Serviços com conexão ATIVA no Composio.

    Usado para sincronizar a tabela local de conexões. Sem isso o system
    prompt segue afirmando que Gmail e Agenda estão desconectados — e o
    modelo, obedecendo corretamente a uma informação falsa, se recusa a usar
    as ações que já existem.
    """
    if not is_configured():
        return []
    try:
        resp = requests.get(
            f"{BASE_URL}/connected_accounts",
            headers={"x-api-key": os.environ["COMPOSIO_API_KEY"].strip()},
            params={"limit": 100},
            timeout=TIMEOUT,
            verify=verificar_tls,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Não foi possível listar conexões do Composio: %s", exc)
        return []

    ativos = set()
    for conta in resp.json().get("items", []):
        if (conta.get("status") or "").upper() != "ACTIVE":
            continue
        slug = (conta.get("toolkit") or {}).get("slug")
        if slug:
            ativos.add(slug)
    return sorted(ativos)
