"""
N.A.S.H - Redefine a senha de qualquer conta, inclusive a do administrador.

Uso:
    python scripts/redefinir_senha.py                      # lista as contas
    python scripts/redefinir_senha.py alguem@exemplo.com   # sorteia uma senha
    python scripts/redefinir_senha.py alguem@exemplo.com --senha "minha-senha"
    python scripts/redefinir_senha.py alguem@exemplo.com --promover-admin

Por que existe, sendo que o administrador já redefine senha pelo painel:
o painel não socorre o próprio administrador. Se ele esquecer a senha, não há
ninguém acima para liberar, e não existe envio de e-mail neste projeto -- a
conta ficaria trancada e o único caminho seria editar o banco à mão.

Este script é esse caminho, feito direito: valida, avisa em qual banco está
mexendo e nunca imprime hash.

Roda contra o banco de DATABASE_URL. Confira o destino que ele mostra antes de
confirmar -- em produção, é o banco real.
"""
import os
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from werkzeug.security import generate_password_hash  # noqa: E402

from app import create_app  # noqa: E402
from backend.db import is_postgres  # noqa: E402
from backend.models import APROVADO, User, db  # noqa: E402
from backend.security.auth import (  # noqa: E402
    TAMANHO_MINIMO_SENHA,
    gerar_senha_temporaria,
)


def _destino(uri: str) -> str:
    """Descreve o banco sem nunca imprimir a senha da conexão."""
    if not is_postgres(uri):
        return f"SQLite -> {uri.replace('sqlite:///', '')}"
    p = urlparse(uri)
    return f"Postgres -> {p.username or '?'}@{p.hostname or '?'}:{p.port or 5432}"


def main() -> int:
    argumentos = [a for a in sys.argv[1:] if not a.startswith("--")]
    promover = "--promover-admin" in sys.argv

    senha_escolhida = None
    if "--senha" in sys.argv:
        i = sys.argv.index("--senha")
        if i + 1 >= len(sys.argv):
            print("  --senha exige um valor.")
            return 1
        senha_escolhida = sys.argv[i + 1]
        if senha_escolhida in argumentos:
            argumentos.remove(senha_escolhida)

    app = create_app()
    print()
    print("  Destino:", _destino(app.config["SQLALCHEMY_DATABASE_URI"]))
    print()

    with app.app_context():
        if not argumentos:
            contas = User.query.order_by(User.id).all()
            if not contas:
                print("  Nenhuma conta cadastrada ainda.")
                return 1
            print(f"  Contas ({len(contas)}):")
            for u in contas:
                marca = " [admin]" if u.is_admin else ""
                print(f"    {u.id:>3}  {u.email:<34} {u.status}{marca}")
            print()
            print("  Informe o e-mail para redefinir a senha.")
            return 1

        email = argumentos[0].strip().lower()
        usuario = User.query.filter_by(email=email).first()
        if not usuario:
            print(f"  Não existe conta com o e-mail {email!r}.")
            return 1

        if senha_escolhida is not None:
            if len(senha_escolhida) < TAMANHO_MINIMO_SENHA:
                print(f"  A senha precisa ter ao menos {TAMANHO_MINIMO_SENHA} caracteres.")
                return 1
            nova = senha_escolhida
            origem = "definida por você"
        else:
            nova = gerar_senha_temporaria()
            origem = "sorteada agora"

        usuario.password_hash = generate_password_hash(nova)

        # Conta trancada em "pendente" não entra nem com a senha certa.
        if usuario.status != APROVADO:
            anterior = usuario.status
            usuario.status = APROVADO
            print(f"  Conta estava '{anterior}' -- liberada junto.")

        if promover and not usuario.is_admin:
            usuario.is_admin = True
            print("  Conta promovida a administradora.")

        db.session.commit()

        print(f"  Senha de {usuario.email} redefinida ({origem}):")
        print()
        print(f"      {nova}")
        print()
        print("  Guarde agora: ela não fica salva em lugar nenhum além do hash.")
        print("  Entre com ela e troque em Ajustes.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
