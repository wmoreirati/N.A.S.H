"""
N.A.S.H - Inicialização do banco de dados.

O banco é escolhido pela variável de ambiente DATABASE_URL:

    definida   -> Postgres (Supabase em produção)
    ausente    -> SQLite local em instance/nash.db

Isso permite rodar o mesmo código nos dois modos: SQLite na máquina do
desenvolvedor, Postgres no servidor, sem alterar nada além do .env.

IMPORTANTE (Vercel + Supabase): use a string do **pooler em modo transação**
(porta 6543), nunca a conexão direta (5432). Dois motivos independentes:

  1. Cada função serverless abre a própria conexão. A conexão direta esgota
     o limite do Postgres rapidamente; o pooler existe para esse padrão.
  2. A conexão direta do Supabase é IPv6. Sem o add-on pago de IPv4 ela
     simplesmente não conecta de vários ambientes. O pooler sempre é IPv4.

Com o pooler em modo transação, o SQLAlchemy NÃO deve manter pool próprio
(usamos NullPool): quem faz o pooling é o Supavisor, do outro lado.
"""
import os
import logging

from sqlalchemy.pool import NullPool

from backend.models import db, Connection

logger = logging.getLogger("nash.db")

EXTERNAL_SERVICES = ["spotify", "google_calendar", "gmail", "outlook", "messages"]


def _normalize_postgres_uri(uri: str) -> str:
    """
    Ajusta a URI de Postgres para o que o SQLAlchemy espera.

    - `postgres://` (formato antigo, que vários painéis ainda entregam) não é
      reconhecido pelo SQLAlchemy moderno.
    - Sem driver explícito, o SQLAlchemy assume `psycopg2`, que não tem wheel
      para Python 3.14 e falha ao instalar. Este projeto usa o psycopg 3, então
      apontamos o driver na própria URI: `postgresql+psycopg://`.
    - Sem `sslmode`, a conexão com o Supabase pode ser recusada. Só
      acrescentamos se quem configurou não tiver definido um valor próprio.

    Um driver escolhido explicitamente (ex.: `postgresql+psycopg2://`) é
    respeitado — só preenchemos quando está omisso.
    """
    if uri.startswith("postgres://"):
        uri = "postgresql://" + uri[len("postgres://"):]

    if uri.startswith("postgresql://"):
        uri = "postgresql+psycopg://" + uri[len("postgresql://"):]

    if uri.startswith("postgresql") and "sslmode=" not in uri:
        uri += ("&" if "?" in uri else "?") + "sslmode=require"

    return uri


def resolve_database_uri(app) -> str:
    """
    Descobre qual banco usar, na ordem de precedência:

    1. SQLALCHEMY_DATABASE_URI já presente na config (usado pelos testes,
       que passam um SQLite temporário via create_app(config_overrides=...))
    2. DATABASE_URL do ambiente (Postgres/Supabase)
    3. SQLite local em instance/nash.db
    """
    existing = app.config.get("SQLALCHEMY_DATABASE_URI")
    if existing:
        return existing

    database_url = (os.environ.get("DATABASE_URL") or "").strip()
    if database_url:
        return _normalize_postgres_uri(database_url)

    db_path = os.path.join(app.instance_path, "nash.db")
    os.makedirs(app.instance_path, exist_ok=True)
    return f"sqlite:///{db_path}"


def is_postgres(uri: str) -> bool:
    return uri.startswith("postgresql")


def init_db(app):
    """
    Inicializa o SQLAlchemy e, quando apropriado, cria as tabelas.

    Em SQLite o schema é criado automaticamente — é um arquivo descartável e
    recriá-lo é barato. Em Postgres, NÃO: rodar create_all() a cada partida a
    frio de uma função serverless custa uma ida ao banco só para descobrir que
    as tabelas já existem. Lá o schema é criado uma única vez, de propósito,
    por `scripts/init_db.py`.

    Para forçar um comportamento diferente, use DB_AUTO_CREATE=1 ou 0.
    """
    uri = resolve_database_uri(app)
    app.config["SQLALCHEMY_DATABASE_URI"] = uri
    app.config.setdefault("SQLALCHEMY_TRACK_MODIFICATIONS", False)

    if is_postgres(uri):
        # Quem faz o pooling é o Supavisor (pooler do Supabase), não nós.
        app.config.setdefault("SQLALCHEMY_ENGINE_OPTIONS", {"poolclass": NullPool})

    db.init_app(app)

    auto_create_env = os.environ.get("DB_AUTO_CREATE", "").strip()
    if auto_create_env:
        auto_create = auto_create_env == "1"
    else:
        auto_create = not is_postgres(uri)

    if auto_create:
        with app.app_context():
            create_schema()

    logger.info(
        "Banco: %s (schema criado automaticamente: %s)",
        "Postgres" if is_postgres(uri) else "SQLite",
        auto_create,
    )


def create_schema():
    """
    Cria as tabelas que ainda não existem e popula os dados padrão.

    Nunca apaga nem altera tabela existente — `create_all` só acrescenta o
    que falta. É seguro rodar de novo em um banco já povoado.

    Precisa ser chamada dentro de um app context.
    """
    db.create_all()
    _seed_connections()


def _seed_connections():
    """Garante que exista uma linha de status (desconectado) para cada serviço externo previsto."""
    created = 0
    for service in EXTERNAL_SERVICES:
        existing = Connection.query.filter_by(service=service).first()
        if not existing:
            db.session.add(Connection(service=service, connected=False))
            created += 1
    if created:
        db.session.commit()
    return created
