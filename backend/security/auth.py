"""
N.A.S.H - Autenticação por e-mail e senha, com liberação pelo administrador.

Regra do projeto: qualquer pessoa pode PEDIR acesso, ninguém entra sem que o
administrador aprove. O cadastro nasce `pendente` e só vira `aprovado` por ação
explícita do adm.

Por que isso é obrigatório aqui: o assistente tem contas externas reais
conectadas (Gmail, Agenda, Drive de uma pessoa). Sem porta, quem descobrisse a
URL leria o e-mail dela. Por isso as ações externas ficam restritas ao adm,
mesmo entre usuários já aprovados.
"""
import os
import re
from datetime import datetime
from functools import wraps

from flask import has_request_context, jsonify, session
from werkzeug.security import check_password_hash, generate_password_hash

from backend.models import APROVADO, PENDENTE, RECUSADO, User, db

CHAVE_SESSAO = "user_id"

# Exigência mínima de senha. Curta demais é convite a força bruta; exigir
# símbolos costuma empurrar a pessoa para senhas piores e anotadas.
TAMANHO_MINIMO_SENHA = 8

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AuthError(Exception):
    """Falha de autenticação/cadastro com mensagem própria para o usuário."""

    def __init__(self, mensagem: str, status: int = 400):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.status = status


# ---------------------------------------------------------------------------
# Administrador
# ---------------------------------------------------------------------------

def emails_admin() -> set[str]:
    """
    E-mails que viram administradores ao se cadastrarem.

    Vem do ambiente (`ADMIN_EMAIL`, aceitando lista separada por vírgula) para
    que nenhuma credencial de dono fique escrita no código.
    """
    bruto = (os.environ.get("ADMIN_EMAIL") or "").strip()
    return {e.strip().lower() for e in bruto.split(",") if e.strip()}


def _normaliza_email(email: str) -> str:
    return (email or "").strip().lower()


# ---------------------------------------------------------------------------
# Cadastro e login
# ---------------------------------------------------------------------------

def registrar(email: str, senha: str, nome: str = "") -> User:
    """Cria um pedido de acesso. Devolve o usuário criado, já persistido."""
    email = _normaliza_email(email)
    nome = (nome or "").strip()[:120]

    if not _EMAIL.match(email):
        raise AuthError("Informe um e-mail válido.")
    if len(senha or "") < TAMANHO_MINIMO_SENHA:
        raise AuthError(
            f"A senha precisa ter pelo menos {TAMANHO_MINIMO_SENHA} caracteres."
        )
    if User.query.filter_by(email=email).first():
        raise AuthError("Já existe um cadastro com esse e-mail.", status=409)

    e_admin = email in emails_admin()

    usuario = User(
        email=email,
        name=nome,
        password_hash=generate_password_hash(senha),
        # O adm não pede permissão a ninguém: entra aprovado.
        status=APROVADO if e_admin else PENDENTE,
        is_admin=e_admin,
        approved_at=datetime.utcnow() if e_admin else None,
    )
    db.session.add(usuario)
    db.session.commit()

    if e_admin:
        adotar_orfaos(usuario)

    return usuario


def autenticar(email: str, senha: str) -> User:
    """
    Valida credenciais e o estado do cadastro.

    A mensagem de credencial errada é a mesma para e-mail inexistente e senha
    errada, de propósito: distinguir os dois casos entrega a quem tenta invadir
    a lista de quem tem conta aqui.
    """
    email = _normaliza_email(email)
    usuario = User.query.filter_by(email=email).first()

    if not usuario or not check_password_hash(usuario.password_hash, senha or ""):
        raise AuthError("E-mail ou senha incorretos.", status=401)

    if usuario.status == PENDENTE:
        raise AuthError(
            "Seu pedido de acesso ainda está aguardando liberação do administrador.",
            status=403,
        )
    if usuario.status == RECUSADO:
        raise AuthError("Seu pedido de acesso não foi liberado.", status=403)

    return usuario


# ---------------------------------------------------------------------------
# Aprovação (somente administrador)
# ---------------------------------------------------------------------------

def aprovar(user_id: int) -> User:
    usuario = User.query.get(user_id)
    if not usuario:
        raise AuthError("Usuário não encontrado.", status=404)
    usuario.status = APROVADO
    usuario.approved_at = datetime.utcnow()
    db.session.commit()
    return usuario


def recusar(user_id: int) -> User:
    usuario = User.query.get(user_id)
    if not usuario:
        raise AuthError("Usuário não encontrado.", status=404)
    if usuario.is_admin:
        raise AuthError("Não é possível recusar um administrador.", status=400)
    usuario.status = RECUSADO
    db.session.commit()
    return usuario


def listar_usuarios() -> list[dict]:
    """Pendentes primeiro — é o que o adm precisa ver e resolver."""
    ordem = {PENDENTE: 0, APROVADO: 1, RECUSADO: 2}
    usuarios = User.query.order_by(User.created_at.desc()).all()
    usuarios.sort(key=lambda u: (ordem.get(u.status, 9), u.email))
    return [u.to_dict() for u in usuarios]


def adotar_orfaos(usuario: User) -> int:
    """
    Passa para o adm os registros criados antes de existir login (user_id NULL).

    Sem isto, as tarefas, memórias e o histórico que já estavam em produção
    ficariam invisíveis para todo mundo — e visíveis para ninguém é melhor que
    visíveis para qualquer um, mas ainda é perda de dado da dona do projeto.
    """
    from backend.models import Memory, Message, PendingAction, Project, Task

    total = 0
    for Modelo in (Task, Project, Memory, Message, PendingAction):
        total += Modelo.query.filter(Modelo.user_id.is_(None)).update(
            {"user_id": usuario.id}, synchronize_session=False
        )
    db.session.commit()
    return total


# ---------------------------------------------------------------------------
# Sessão
# ---------------------------------------------------------------------------

def iniciar_sessao(usuario: User) -> None:
    session.clear()
    session[CHAVE_SESSAO] = usuario.id
    session.permanent = True


def encerrar_sessao() -> None:
    session.clear()


def usuario_atual() -> User | None:
    """
    Usuário logado nesta requisição, ou None.

    Resolve SEMPRE a partir do cookie de sessão, sem memória entre chamadas.
    Já houve cache em `flask.g` aqui e ele causou escalada de privilégio: `g`
    vive no contexto de APLICAÇÃO, não no de requisição, e quando um contexto
    de aplicação já está ativo o Flask o reaproveita entre requisições. O
    administrador ficava em cache e a requisição seguinte, de outra pessoa,
    era atendida como se fosse ele. Consultar por chave primária é barato
    (cai no mapa de identidade do SQLAlchemy); identidade errada, não.
    """
    # Fora de requisição (script de manutenção, teste, tarefa agendada) não
    # existe sessão: devolve None em vez de estourar. Quem consulta dado
    # continua protegido, porque `escopar` trata None como "nada".
    if not has_request_context():
        return None

    uid = session.get(CHAVE_SESSAO)
    usuario = User.query.get(uid) if uid else None

    # Cadastro revogado depois do login não pode continuar valendo.
    if usuario and not usuario.aprovado:
        return None

    return usuario


def usuario_atual_id() -> int | None:
    usuario = usuario_atual()
    return usuario.id if usuario else None


def e_admin() -> bool:
    usuario = usuario_atual()
    return bool(usuario and usuario.is_admin)


# ---------------------------------------------------------------------------
# Escopo de dados
# ---------------------------------------------------------------------------

def escopar(query, Modelo):
    """
    Restringe uma consulta ao dono da sessão atual.

    Sem ninguém logado devolve VAZIO, nunca a tabela inteira. É a diferença
    entre uma falha que aparece e um vazamento silencioso: se algum caminho
    esquecer de exigir login, o pior resultado é uma lista vazia.
    """
    uid = usuario_atual_id()
    if uid is None:
        return query.filter(db.false())
    return query.filter(Modelo.user_id == uid)


def marcar_dono(instancia):
    """Carimba o dono num registro novo, antes de gravar."""
    instancia.user_id = usuario_atual_id()
    return instancia


# ---------------------------------------------------------------------------
# Decoradores de rota
# ---------------------------------------------------------------------------

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not usuario_atual():
            return jsonify({"ok": False, "error": "Faça login para continuar."}), 401
        return fn(*args, **kwargs)

    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        usuario = usuario_atual()
        if not usuario:
            return jsonify({"ok": False, "error": "Faça login para continuar."}), 401
        if not usuario.is_admin:
            return jsonify({"ok": False, "error": "Acesso restrito ao administrador."}), 403
        return fn(*args, **kwargs)

    return wrapper
