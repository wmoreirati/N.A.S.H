"""
N.A.S.H - Sincroniza a tabela local de conexões com o estado real do Composio.

Uso:
    python scripts/sync_composio_connections.py
    python scripts/sync_composio_connections.py --sem-verificar-tls   # proxy local

Por que existe: o system prompt manda o modelo confiar SÓ no status da tabela
local ("nunca finja que Gmail/Agenda estão conectados"). Enquanto essa tabela
dizia "desconectado", o modelo se recusava — corretamente — a usar ações que
já funcionavam. O bug não era do modelo nem da integração: era a aplicação
afirmando algo falso sobre si mesma.

Rode depois de conectar ou desconectar qualquer serviço no Composio.
"""
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

VERIFICAR_TLS = "--sem-verificar-tls" not in sys.argv

from app import create_app  # noqa: E402
from backend.models import db, Connection  # noqa: E402
from backend.tools import composio_tools  # noqa: E402


def main() -> int:
    if not composio_tools.is_configured():
        print("  COMPOSIO_API_KEY não definida — nada a sincronizar.")
        return 1

    if not VERIFICAR_TLS:
        import urllib3
        urllib3.disable_warnings()
        print("  AVISO: verificação de TLS desligada (proxy local).")

    ativos = composio_tools.contas_ativas(verificar_tls=VERIFICAR_TLS)
    if not ativos:
        print("  Nenhuma conexão ATIVA encontrada no Composio.")
        return 1

    # Só interessam os serviços cujas ações o N.A.S.H realmente expõe. Marcar
    # como conectado algo que o assistente não sabe usar seria outra forma de
    # mentir para o usuário.
    usaveis = {slug.split("_", 1)[0].lower() for slug in composio_tools.ACOES}

    app = create_app()
    with app.app_context():
        criados = atualizados = 0
        for servico in ativos:
            if servico not in usaveis:
                continue
            linha = Connection.query.filter_by(service=servico).first()
            if not linha:
                db.session.add(Connection(service=servico, connected=True))
                criados += 1
            elif not linha.connected:
                linha.connected = True
                atualizados += 1

        # Serviço que saiu do ar no Composio precisa voltar a aparecer como
        # desconectado — a promessa do projeto vale nos dois sentidos.
        for linha in Connection.query.all():
            if linha.service in usaveis and linha.service not in ativos and linha.connected:
                linha.connected = False
                atualizados += 1

        # A semente antiga usava "google_calendar"; o Composio usa
        # "googlecalendar". Sem remover, a aba Conexoes mostraria os dois.
        legado = Connection.query.filter_by(service="google_calendar").first()
        if legado and Connection.query.filter_by(service="googlecalendar").first():
            db.session.delete(legado)
            print("  Removida linha legada 'google_calendar' (duplicava googlecalendar)")

        db.session.commit()

        print(f"\n  Ativos no Composio : {', '.join(ativos)}")
        print(f"  Expostos pelo N.A.S.H: {', '.join(sorted(usaveis & set(ativos)))}")
        print(f"  Linhas criadas={criados}  atualizadas={atualizados}\n")
        for linha in Connection.query.order_by(Connection.service).all():
            marca = "conectado" if linha.connected else "-"
            print(f"    {linha.service:<18} {marca}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
