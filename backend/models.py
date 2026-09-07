"""
N.A.S.H - Modelos de banco de dados (SQLAlchemy)
Banco local SQLite para desenvolvimento.
"""
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Preference(db.Model):
    """Preferências do usuário (chave/valor)."""
    __tablename__ = "preferences"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(120), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "key": self.key,
            "value": self.value,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Memory(db.Model):
    """Memórias de longo prazo, salvas somente com autorização do usuário."""
    __tablename__ = "memories"

    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(60), default="geral")  # preferencia, projeto, estudo, contexto...
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "category": self.category,
            "content": self.content,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Task(db.Model):
    """Tarefas / agenda local."""
    __tablename__ = "tasks"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, default="")
    date = db.Column(db.String(20), nullable=True)   # YYYY-MM-DD
    time = db.Column(db.String(10), nullable=True)   # HH:MM
    priority = db.Column(db.String(20), default="normal")  # baixa, normal, alta
    status = db.Column(db.String(20), default="pendente")  # pendente, concluida, excluida
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    deleted_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "date": self.date,
            "time": self.time,
            "priority": self.priority,
            "status": self.status,
            "project_id": self.project_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }


class Project(db.Model):
    """Projetos do usuário."""
    __tablename__ = "projects"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, default="")
    objectives = db.Column(db.Text, default="")
    notes = db.Column(db.Text, default="")
    progress = db.Column(db.Integer, default=0)  # 0-100
    status = db.Column(db.String(20), default="ativo")  # ativo, concluido, arquivado
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tasks = db.relationship("Task", backref="project", lazy=True)

    def to_dict(self, include_tasks=False):
        data = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "objectives": self.objectives,
            "notes": self.notes,
            "progress": self.progress,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_tasks:
            data["tasks"] = [t.to_dict() for t in self.tasks if not t.deleted_at]
        return data


class Message(db.Model):
    """Histórico de conversa (para contexto e auditoria)."""
    __tablename__ = "messages"

    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(20), nullable=False)  # user, assistant, tool, system
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Log(db.Model):
    """Log de ações do sistema (auditoria de segurança)."""
    __tablename__ = "logs"

    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(120), nullable=False)
    detail = db.Column(db.Text, default="")
    permission = db.Column(db.String(60), nullable=True)
    success = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "action": self.action,
            "detail": self.detail,
            "permission": self.permission,
            "success": self.success,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Connection(db.Model):
    """Estado real de integrações externas (Spotify, Google Calendar, etc.)."""
    __tablename__ = "connections"

    id = db.Column(db.Integer, primary_key=True)
    service = db.Column(db.String(60), unique=True, nullable=False)  # spotify, google_calendar, gmail...
    connected = db.Column(db.Boolean, default=False)
    access_token = db.Column(db.Text, nullable=True)
    refresh_token = db.Column(db.Text, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    meta = db.Column(db.Text, default="{}")
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        # NUNCA expor tokens no JSON retornado ao frontend
        return {
            "id": self.id,
            "service": self.service,
            "connected": self.connected,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class PendingAction(db.Model):
    """
    Ações propostas pela IA que exigem confirmação explícita do usuário
    antes de serem executadas (WRITE, DELETE, CALENDAR, EXTERNAL_SERVICE...).
    """
    __tablename__ = "pending_actions"

    id = db.Column(db.Integer, primary_key=True)
    tool_name = db.Column(db.String(80), nullable=False)
    arguments = db.Column(db.Text, nullable=False)  # JSON serializado
    description = db.Column(db.Text, nullable=False)  # texto amigável mostrado ao usuário
    permission = db.Column(db.String(60), nullable=False)
    status = db.Column(db.String(20), default="pendente")  # pendente, confirmada, cancelada, expirada
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        import json
        return {
            "id": self.id,
            "tool_name": self.tool_name,
            "arguments": json.loads(self.arguments),
            "description": self.description,
            "permission": self.permission,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }
