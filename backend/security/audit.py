"""
N.A.S.H - Auditoria (Log).

Toda ação importante (criação, edição, exclusão, confirmação, cancelamento,
erro de ferramenta) passa por aqui. NUNCA registre API keys, tokens ou
qualquer segredo — apenas nome da ação, um detalhe textual curto e o
resultado.
"""
import logging
from backend.models import db, Log

logger = logging.getLogger("nash.audit")

# Palavras que, se aparecerem no texto de detalhe, são mascaradas por segurança.
_SENSITIVE_HINTS = ("api_key", "apikey", "access_token", "refresh_token", "secret", "password", "senha")


def _sanitize(detail: str) -> str:
    if not detail:
        return ""
    lowered = detail.lower()
    for hint in _SENSITIVE_HINTS:
        if hint in lowered:
            return "[detalhe omitido: possível dado sensível]"
    return detail[:500]


def log_action(action: str, detail: str = "", permission: str | None = None, success: bool = True):
    """Grava uma entrada de log. Nunca lança exceção — auditoria não pode derrubar o app."""
    try:
        entry = Log(
            action=action,
            detail=_sanitize(detail),
            permission=permission,
            success=success,
        )
        db.session.add(entry)
        db.session.commit()
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao gravar log de auditoria (ação=%s)", action)
        db.session.rollback()
