"""
N.A.S.H - Migração do banco para o login com aprovação pelo administrador.

Uso:
    python scripts/migrate_login.py          # mostra o destino e pede confirmação
    python scripts/migrate_login.py --sim    # aplica sem perguntar

O que faz, nesta ordem:
  1. cria a tabela `users` (via create_all, que só acrescenta o que falta);
  2. acrescenta a coluna `user_id` nas tabelas de dado pessoal;
  3. acrescenta em `users` as colunas de recuperação de senha.

Por que um script à parte do `init_db.py`: `create_all` cria tabela que não
existe, mas NUNCA altera tabela que já existe. As tabelas de produção já
estavam lá sem a coluna de dono — só um ALTER TABLE resolve.

É idempotente: cada passo verifica antes se já foi feito. Rodar duas vezes não
quebra nada e não duplica coluna.

A coluna nasce NULA de propósito. As linhas que já existem em produção não têm
dono ainda; quem as adota é o primeiro cadastro feito com o e-mail de
`ADMIN_EMAIL` (ver `adotar_orfaos` em backend/security/auth.py). Até lá elas
ficam invisíveis para todos, que é o lado seguro do erro.
"""
import os
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from sqlalchemy import text  # noqa: E402

from app import create_app  # noqa: E402
from backend.db import create_schema, is_postgres  # noqa: E402
from backend.models import db  # noqa: E402

# Tabela -> nome da coluna de dono a acrescentar.
TABELAS_COM_DONO = ("tasks", "projects", "memories", "messages", "pending_actions")


def _destino_legivel(uri: str) -> str:
    """Descreve o banco de destino sem nunca imprimir a senha."""
    if not is_postgres(uri):
        return f"SQLite -> {uri.replace('sqlite:///', '')}"

    parsed = urlparse(uri)
    porta = parsed.port or 5432
    modo = "pooler / transação" if porta == 6543 else "conexão direta"
    return (f"Postgres -> {parsed.username or '?'}@{parsed.hostname or '?'}:{porta}"
            f"/{(parsed.path or '/').lstrip('/') or '?'}  ({modo})")


def main() -> int:
    confirmado = "--sim" in sys.argv

    app = create_app()
    uri = app.config["SQLALCHEMY_DATABASE_URI"]

    print()
    print("  Destino:", _destino_legivel(uri))
    print()
    print("  Vai criar a tabela `users` e acrescentar `user_id` em:")
    print("   ", ", ".join(TABELAS_COM_DONO))
    print()

    if not confirmado:
        resposta = input("  Aplicar neste banco? [s/N] ").strip().lower()
        if resposta not in ("s", "sim", "y", "yes"):
            print("  Cancelado. Nada foi alterado.")
            return 1

    with app.app_context():
        inspetor = db.inspect(db.engine)

        # --- 1. tabela users -------------------------------------------
        if "users" in inspetor.get_table_names():
            print("  = tabela `users` já existe")
        else:
            create_schema()
            print("  + tabela `users` criada")

        # O inspetor guarda o estado de quando foi criado; depois de mexer no
        # schema é preciso um novo, senão os passos seguintes leem o passado.
        inspetor = db.inspect(db.engine)
        tabelas = set(inspetor.get_table_names())

        # --- 2. coluna user_id nas tabelas de dado pessoal --------------
        adicionadas, ja_tinham, ausentes = [], [], []

        for tabela in TABELAS_COM_DONO:
            if tabela not in tabelas:
                ausentes.append(tabela)
                continue

            colunas = {c["name"] for c in inspetor.get_columns(tabela)}
            if "user_id" in colunas:
                ja_tinham.append(tabela)
                continue

            # Sem NOT NULL e sem valor padrão: as linhas existentes ficam
            # órfãs até o administrador se cadastrar e adotá-las.
            with db.engine.begin() as conexao:
                conexao.execute(text(
                    f"ALTER TABLE {tabela} ADD COLUMN user_id INTEGER "
                    f"REFERENCES users(id)"
                ))
            adicionadas.append(tabela)

        print()
        for t in adicionadas:
            print(f"  + user_id acrescentada em `{t}`")
        for t in ja_tinham:
            print(f"  = `{t}` já tinha user_id")
        for t in ausentes:
            print(f"  ! `{t}` não existe neste banco — pulada")

        # --- 3. colunas de recuperação de senha em `users` ---------------
        # Vieram depois do login, quando a recuperação por e-mail entrou.
        # Guardam o HASH do token e a validade -- nunca o token em si.
        colunas_users = {c["name"] for c in inspetor.get_columns("users")}
        for coluna, tipo in (("reset_token_hash", "TEXT"),
                             ("reset_expira_em", "TIMESTAMP")):
            if coluna in colunas_users:
                print(f"  = `users` já tinha {coluna}")
                continue
            with db.engine.begin() as conexao:
                conexao.execute(text(f"ALTER TABLE users ADD COLUMN {coluna} {tipo}"))
            print(f"  + {coluna} acrescentada em `users`")

        # --- 4. quanto ficou órfão --------------------------------------
        print()
        total_orfao = 0
        for tabela in TABELAS_COM_DONO:
            if tabela in ausentes:
                continue
            with db.engine.connect() as conexao:
                n = conexao.execute(
                    text(f"SELECT COUNT(*) FROM {tabela} WHERE user_id IS NULL")
                ).scalar() or 0
            total_orfao += n
            if n:
                print(f"    {tabela}: {n} registro(s) sem dono")

        if total_orfao:
            print()
            print(f"  {total_orfao} registro(s) aguardam adoção.")
            print("  Eles passam a ser do administrador no primeiro cadastro")
            print("  feito com o e-mail definido em ADMIN_EMAIL.")
        else:
            print("  Nenhum registro órfão.")

    print()
    print("  Pronto. Cadastre ADMIN_EMAIL no ambiente antes de abrir o app.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
