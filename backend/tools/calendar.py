"""
N.A.S.H - Agenda / Calendário.

IMPORTANTE (seção 14/27 do briefing): esta é a agenda LOCAL, baseada nas
tarefas com data/hora. A integração real com Google Calendar depende de
OAuth e de credenciais configuradas pelo usuário (ver backend/tools/connections.py).
Enquanto não houver uma conexão real, o N.A.S.H deve deixar isso explícito
e nunca fingir que está sincronizado com o Google Calendar.
"""
from backend.models import Task, Connection
from backend.security.auth import escopar


def get_local_calendar(date: str | None = None):
    """Retorna as tarefas com data/hora definidas (agenda local), opcionalmente filtradas por dia."""
    query = escopar(Task.query, Task).filter(Task.deleted_at.is_(None), Task.date.isnot(None))
    if date:
        query = query.filter_by(date=date)
    tasks = query.order_by(Task.date.asc(), Task.time.asc()).all()
    return [t.to_dict() for t in tasks]


def google_calendar_status() -> dict:
    conn = Connection.query.filter_by(service="google_calendar").first()
    connected = bool(conn and conn.connected)
    return {
        "service": "google_calendar",
        "connected": connected,
        "message": (
            "Google Calendar conectado." if connected
            else "Google Calendar ainda não está conectado. Estou usando apenas a agenda local."
        ),
    }
