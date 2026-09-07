"""
N.A.S.H - Criação do schema no banco configurado.

Uso:
    python scripts/init_db.py            # mostra o destino e pede confirmação
    python scripts/init_db.py --sim      # cria sem perguntar (para automação)

Cria as tabelas que ainda não existem e popula os status de conexão externa.
NUNCA apaga nem altera tabela existente: `create_all` só acrescenta o que falta,
então rodar de novo em um banco já povoado é seguro.

Em SQLite isso acontece sozinho ao subir o servidor. Este script existe para o
Postgres (Supabase), onde criar schema é uma decisão explícita e não algo que
deva rodar a cada partida a frio de uma função serverless.
"""
import os
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app import create_app  # noqa: E402
from backend.db import create_schema, is_postgres  # noqa: E402
from backend.models import db  # noqa: E402


def _destino_legivel(uri: str) -> str:
    """Descreve o banco de destino sem nunca imprimir a senha."""
    if not is_postgres(uri):
        return f"SQLite -> {uri.replace('sqlite:///', '')}"

    parsed = urlparse(uri)
    usuario = parsed.username or "?"
    host = parsed.hostname or "?"
    porta = parsed.port or 5432
    banco = (parsed.path or "/").lstrip("/") or "?"

    modo = "pooler / transação" if porta == 6543 else "conexão direta"
    return f"Postgres -> {usuario}@{host}:{porta}/{banco}  ({modo})"


def main() -> int:
    confirmado = "--sim" in sys.argv

    app = create_app()
    uri = app.config["SQLALCHEMY_DATABASE_URI"]

    print()
    print("  Destino:", _destino_legivel(uri))
    print()

    if is_postgres(uri) and urlparse(uri).port != 6543:
        print("  AVISO: esta nao e a porta do pooler (6543).")
        print("  Para uso na Vercel, prefira a string de 'Transaction pooler'.")
        print()

    if not confirmado:
        resposta = input("  Criar o schema neste banco? [s/N] ").strip().lower()
        if resposta not in ("s", "sim", "y", "yes"):
            print("  Cancelado. Nada foi alterado.")
            return 1

    with app.app_context():
        antes = set(db.inspect(db.engine).get_table_names())
        create_schema()
        depois = set(db.inspect(db.engine).get_table_names())

    novas = sorted(depois - antes)
    print()
    if novas:
        print(f"  Tabelas criadas ({len(novas)}):")
        for t in novas:
            print(f"    + {t}")
    else:
        print("  Nenhuma tabela nova — o schema ja estava completo.")

    print(f"  Total no banco agora: {len(depois)} tabela(s).")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
