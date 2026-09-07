"""
N.A.S.H - Inicialização do banco de dados.
"""
import os
from backend.models import db, Connection


def init_db(app):
    """
    Inicializa o SQLAlchemy, cria tabelas e popula dados padrão.

    Se o app já tiver uma SQLALCHEMY_DATABASE_URI definida (por exemplo,
    passada via create_app(config_overrides=...) nos testes, com um banco
    SQLite temporário), essa URI é respeitada. Caso contrário, usa o banco
    padrão em instance/nash.db.
    """
    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        db_path = os.path.join(app.instance_path, "nash.db")
        os.makedirs(app.instance_path, exist_ok=True)
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"

    app.config.setdefault("SQLALCHEMY_TRACK_MODIFICATIONS", False)

    db.init_app(app)

    with app.app_context():
        db.create_all()
        _seed_connections()


def _seed_connections():
    """Garante que exista uma linha de status (desconectado) para cada serviço externo previsto."""
    services = ["spotify", "google_calendar", "gmail", "outlook", "messages"]
    for service in services:
        existing = Connection.query.filter_by(service=service).first()
        if not existing:
            db.session.add(Connection(service=service, connected=False))
    db.session.commit()
