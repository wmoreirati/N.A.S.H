"""
N.A.S.H - Status de conexões externas.

Regra de ouro (seção 14 do briefing): NUNCA simular uma integração.
Se `connected` for False, ou se o token estiver expirado, o N.A.S.H deve
dizer claramente que o serviço não está disponível — nunca fingir sucesso.

Este módulo apenas LÊ e ATUALIZA o estado de conexão. O fluxo OAuth real
(troca de código por token) não está implementado nesta versão porque
depende de credenciais de app (client_id/client_secret) que o usuário
ainda não forneceu.

Segurança: access_token e refresh_token NUNCA são incluídos em to_dict()
(ver backend/models.py) nem em nenhum retorno desta camada — apenas o
booleano `connected` sai daqui para o restante do sistema.
"""
from datetime import datetime
from backend.models import db, Connection

SUPPORTED_SERVICES = ["spotify", "google_calendar", "gmail", "outlook", "messages"]


def _is_usable(conn: Connection) -> bool:
    """Uma conexão só é considerada usável se: existe, está marcada como
    conectada, e (se tiver expiração) o token ainda não expirou."""
    if not conn or not conn.connected:
        return False
    if conn.expires_at and conn.expires_at < datetime.utcnow():
        return False
    return True


def get_status(service: str) -> dict:
    conn = Connection.query.filter_by(service=service).first()
    if not conn:
        return {"service": service, "connected": False, "supported": False}
    usable = _is_usable(conn)
    return {"service": service, "connected": usable, "supported": True}


def list_all_status():
    return [get_status(s) for s in SUPPORTED_SERVICES]


def disconnect(service: str):
    conn = Connection.query.filter_by(service=service).first()
    if conn:
        conn.connected = False
        conn.access_token = None
        conn.refresh_token = None
        conn.expires_at = None
        db.session.commit()
    return get_status(service)


def spotify_control(action: str, **kwargs) -> dict:
    """
    Ponto único de controle do Spotify. Enquanto não houver uma conexão
    OAuth real e válida (conectada e com token não expirado), esta função
    NUNCA executa nada de verdade — apenas informa o estado real.
    """
    status = get_status("spotify")
    if not status["connected"]:
        return {
            "ok": False,
            "message": "Spotify ainda não está conectado. Configure a integração para controlar a reprodução.",
        }
    # Local reservado para chamada real à API do Spotify quando conectado e válido.
    return {
        "ok": False,
        "message": "Conexão com Spotify detectada, mas a chamada real à API ainda não foi implementada nesta instalação.",
    }


def spotify_search(query: str, **kwargs) -> dict:
    """Busca no Spotify. Mesma regra: nunca inventa resultados sem conexão real."""
    status = get_status("spotify")
    if not status["connected"]:
        return {"ok": False, "message": "Spotify ainda não está conectado."}
    return {
        "ok": False,
        "message": "Conexão com Spotify detectada, mas a busca real ainda não foi implementada nesta instalação.",
    }
