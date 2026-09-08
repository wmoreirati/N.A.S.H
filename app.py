"""
N.A.S.H - Servidor Flask principal.

Executar:
    python app.py

Ver README.md para instruções completas de instalação e configuração.
"""
import os
import logging

from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv

load_dotenv()  # carrega OPENAI_API_KEY, FLASK_SECRET_KEY etc. do arquivo .env

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("nash.app")


def env_int(name: str, default: int) -> int:
    """
    Lê uma variável de ambiente numérica tolerando o caso mais comum em
    painéis de hospedagem: a variável existe, mas está vazia.

    `os.environ.get(nome, padrao)` só devolve o padrão quando a chave não
    existe — com a chave presente e vazia ele devolve "", e um int("") aí
    derruba a aplicação inteira na subida. Valor inválido também não deve
    ser fatal: vira aviso no log e o padrão prevalece.
    """
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning(
            "%s tem valor inválido (%r) — usando o padrão %d.", name, raw, default
        )
        return default


def create_app(config_overrides: dict | None = None) -> Flask:
    """Factory da aplicação — permite instanciar apps isoladas (ex.: testes)."""
    app = Flask(__name__)
    app.config["JSON_AS_ASCII"] = False

    secret_key = os.environ.get("FLASK_SECRET_KEY", "").strip()
    if not secret_key:
        secret_key = os.urandom(32).hex()
        logger.warning(
            "FLASK_SECRET_KEY não definida no .env — usando uma chave temporária "
            "gerada nesta execução (ok para uso local; defina uma fixa antes de expor o servidor)."
        )
    app.config["SECRET_KEY"] = secret_key

    app.config["MAX_HISTORY_MESSAGES"] = env_int("MAX_HISTORY_MESSAGES", 30)

    if config_overrides:
        app.config.update(config_overrides)

    from backend.db import init_db
    init_db(app)

    _register_routes(app)
    return app


def _register_routes(app: Flask):
    from backend.models import db, Message, PendingAction, Log
    from backend.ai.factory import build_provider, get_provider_name
    from backend.ai import agent
    from backend.tools import tasks as tasks_mod
    from backend.tools import projects as projects_mod
    from backend.tools import connections as connections_mod
    from backend.tools import calendar as calendar_mod
    from backend.memory import memory as memory_mod
    from backend.security.audit import log_action
    from backend.security.validation import ValidationError

    ai_provider = build_provider()

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------

    def _history_limit() -> int:
        return app.config.get("MAX_HISTORY_MESSAGES", 30)

    def _recent_history() -> list[dict]:
        msgs = (
            Message.query.filter(Message.role.in_(["user", "assistant"]))
            .order_by(Message.created_at.desc())
            .limit(_history_limit())
            .all()
        )
        msgs.reverse()
        return [{"role": m.role, "content": m.content} for m in msgs]

    def _save_message(role: str, content: str):
        db.session.add(Message(role=role, content=content))
        db.session.commit()

    def _json_error(message: str, status: int = 400):
        return jsonify({"ok": False, "error": message}), status

    def _handle_mutation(fn, *args, action: str, permission: str = "WRITE", **kwargs):
        """Executa uma função de mutação direta da API (fora do fluxo de chat),
        capturando erros de validação/existência de forma consistente e
        registrando log de auditoria."""
        try:
            result = fn(*args, **kwargs)
            log_action(action, detail="via API direta", permission=permission, success=True)
            return result, None
        except ValidationError as exc:
            log_action(action, detail=str(exc), permission=permission, success=False)
            return None, (str(exc), 400)
        except LookupError as exc:
            log_action(action, detail=str(exc), permission=permission, success=False)
            return None, (str(exc), 404)

    # -----------------------------------------------------------------
    # Página principal
    # -----------------------------------------------------------------

    @app.route("/")
    def index():
        return render_template("index.html")

    # -----------------------------------------------------------------
    # Saúde do sistema
    # -----------------------------------------------------------------

    @app.route("/api/health")
    def api_health():
        return jsonify({
            "ok": True,
            "status": "healthy",
            "ai_provider": get_provider_name(),
            "ai_configured": ai_provider.is_configured(),
            "ai_model": ai_provider.model if ai_provider.is_configured() else None,
            # Preenchido só quando o provedor não pôde ser carregado — é o que
            # permite diagnosticar o servidor sem precisar do log da plataforma.
            "ai_error": getattr(ai_provider, "motivo", None),
            "max_history_messages": _history_limit(),
            "tasks_active": tasks_mod.count_active_tasks(),
            "memories_count": len(memory_mod.list_memories()),
            "projects_count": len(projects_mod.list_projects()),
            "connections": connections_mod.list_all_status(),
        })

    # -----------------------------------------------------------------
    # Chat (núcleo do N.A.S.H)
    # -----------------------------------------------------------------

    @app.route("/api/chat", methods=["POST"])
    def api_chat():
        data = request.get_json(silent=True) or {}
        user_message = (data.get("message") or "").strip()

        if not user_message:
            return _json_error("A mensagem não pode estar vazia.")
        if len(user_message) > 8000:
            return _json_error("A mensagem é muito longa (máximo 8000 caracteres).")

        if not ai_provider.is_configured():
            return jsonify({
                "ok": True,
                "type": "error",
                "text": (
                    f"O provedor de IA '{get_provider_name()}' está selecionado, mas sem credencial. "
                    "Preencha a chave correspondente no arquivo .env e reinicie o servidor "
                    "para que eu possa conversar de verdade."
                ),
            })

        _save_message("user", user_message)
        history = _recent_history()[:-1]  # exclui a mensagem recém-salva (vai como user_message)

        try:
            result = agent.run_chat_turn(ai_provider, history, user_message)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Erro inesperado no turno de chat")
            log_action("chat_turn_error", detail=str(exc), success=False)
            return jsonify({"ok": True, "type": "error", "text": f"Ocorreu um erro inesperado: {exc}"})

        if result["type"] in ("message", "confirmation_required"):
            _save_message("assistant", result["text"])

        return jsonify({"ok": True, **result})

    @app.route("/api/history")
    def api_history():
        return jsonify({"ok": True, "messages": _recent_history()})

    # -----------------------------------------------------------------
    # Ações pendentes (confirmação)
    # -----------------------------------------------------------------

    @app.route("/api/pending-actions")
    def api_list_pending_actions():
        agent.expire_old_pending_actions()
        status_filter = request.args.get("status", "pendente")
        query = PendingAction.query
        if status_filter and status_filter != "all":
            query = query.filter_by(status=status_filter)
        items = query.order_by(PendingAction.created_at.desc()).limit(50).all()
        return jsonify({"ok": True, "pending_actions": [p.to_dict() for p in items]})

    def _confirm_or_cancel(pending_id: int, confirmed: bool):
        agent.expire_old_pending_actions()
        pending = PendingAction.query.get(pending_id)
        if not pending:
            return _json_error("Ação pendente não encontrada.", 404)
        if pending.status != "pendente":
            return _json_error(f"Esta ação já foi '{pending.status}' e não pode ser executada novamente.", 409)

        result = agent.resolve_pending_action(pending, confirmed)
        _save_message("assistant", result["text"])
        return jsonify({"ok": True, **result})

    @app.route("/api/pending-actions/<int:pending_id>/confirm", methods=["POST"])
    def api_confirm_pending_action(pending_id):
        return _confirm_or_cancel(pending_id, True)

    @app.route("/api/pending-actions/<int:pending_id>/cancel", methods=["POST"])
    def api_cancel_pending_action(pending_id):
        return _confirm_or_cancel(pending_id, False)

    # -----------------------------------------------------------------
    # Tarefas
    # -----------------------------------------------------------------

    @app.route("/api/tasks", methods=["GET"])
    def api_list_tasks():
        include_deleted = request.args.get("include_deleted") == "1"
        return jsonify({"ok": True, "tasks": tasks_mod.list_tasks(include_deleted=include_deleted)})

    @app.route("/api/tasks", methods=["POST"])
    def api_create_task():
        data = request.get_json(silent=True) or {}
        result, err = _handle_mutation(
            tasks_mod.create_task, action="task_create",
            title=data.get("title", ""), description=data.get("description", ""),
            date=data.get("date"), time=data.get("time"),
            priority=data.get("priority", "normal"), project_id=data.get("project_id"),
        )
        if err:
            return _json_error(*err)
        return jsonify({"ok": True, "task": result})

    @app.route("/api/tasks/<int:task_id>", methods=["PUT"])
    def api_update_task(task_id):
        data = request.get_json(silent=True) or {}
        result, err = _handle_mutation(tasks_mod.update_task, task_id, action="task_update", **data)
        if err:
            return _json_error(*err)
        return jsonify({"ok": True, "task": result})

    @app.route("/api/tasks/<int:task_id>/complete", methods=["POST"])
    def api_complete_task(task_id):
        result, err = _handle_mutation(tasks_mod.complete_task, task_id, action="task_complete")
        if err:
            return _json_error(*err)
        return jsonify({"ok": True, "task": result})

    @app.route("/api/tasks/<int:task_id>/restore", methods=["POST"])
    def api_restore_task(task_id):
        result, err = _handle_mutation(tasks_mod.restore_task, task_id, action="task_restore")
        if err:
            return _json_error(*err)
        return jsonify({"ok": True, "task": result})

    @app.route("/api/tasks/<int:task_id>", methods=["DELETE"])
    def api_delete_task(task_id):
        permanent = request.args.get("permanent") == "1"
        result, err = _handle_mutation(
            tasks_mod.delete_task, task_id, action="task_delete", permission="DELETE", permanent=permanent
        )
        if err:
            return _json_error(*err)
        return jsonify({"ok": True, "result": result})

    # -----------------------------------------------------------------
    # Projetos
    # -----------------------------------------------------------------

    @app.route("/api/projects", methods=["GET"])
    def api_list_projects():
        return jsonify({"ok": True, "projects": projects_mod.list_projects(include_tasks=True)})

    @app.route("/api/projects", methods=["POST"])
    def api_create_project():
        data = request.get_json(silent=True) or {}
        result, err = _handle_mutation(
            projects_mod.create_project, action="project_create",
            name=data.get("name", ""), description=data.get("description", ""),
            objectives=data.get("objectives", ""),
        )
        if err:
            return _json_error(*err)
        return jsonify({"ok": True, "project": result})

    @app.route("/api/projects/<int:project_id>", methods=["PUT"])
    def api_update_project(project_id):
        data = request.get_json(silent=True) or {}
        result, err = _handle_mutation(projects_mod.update_project, project_id, action="project_update", **data)
        if err:
            return _json_error(*err)
        return jsonify({"ok": True, "project": result})

    @app.route("/api/projects/<int:project_id>", methods=["DELETE"])
    def api_delete_project(project_id):
        result, err = _handle_mutation(
            projects_mod.delete_project, project_id, action="project_delete", permission="DELETE"
        )
        if err:
            return _json_error(*err)
        return jsonify({"ok": True, "result": result})

    # -----------------------------------------------------------------
    # Memória
    # -----------------------------------------------------------------

    @app.route("/api/memories", methods=["GET"])
    def api_list_memories():
        return jsonify({"ok": True, "memories": memory_mod.list_memories()})

    @app.route("/api/memories", methods=["POST"])
    def api_save_memory():
        data = request.get_json(silent=True) or {}
        result, err = _handle_mutation(
            memory_mod.save_memory, action="memory_save",
            content=data.get("content", ""), category=data.get("category", "geral"),
        )
        if err:
            return _json_error(*err)
        return jsonify({"ok": True, "memory": result})

    @app.route("/api/memories/<int:memory_id>", methods=["PUT"])
    def api_update_memory(memory_id):
        data = request.get_json(silent=True) or {}
        result, err = _handle_mutation(
            memory_mod.update_memory, memory_id, action="memory_update",
            content=data.get("content"), category=data.get("category"),
        )
        if err:
            return _json_error(*err)
        return jsonify({"ok": True, "memory": result})

    @app.route("/api/memories/<int:memory_id>", methods=["DELETE"])
    def api_delete_memory(memory_id):
        result, err = _handle_mutation(
            memory_mod.delete_memory, memory_id, action="memory_delete", permission="DELETE"
        )
        if err:
            return _json_error(*err)
        return jsonify({"ok": True, "result": result})

    @app.route("/api/memories/clear_all", methods=["POST"])
    def api_clear_all_memories():
        result = memory_mod.delete_all_memories()
        log_action("memory_delete_all", detail=f"{result['deleted_count']} memória(s)", permission="DELETE")
        return jsonify({"ok": True, "result": result})

    # -----------------------------------------------------------------
    # Agenda / Conexões externas
    # -----------------------------------------------------------------

    @app.route("/api/calendar")
    def api_calendar():
        date = request.args.get("date")
        return jsonify({
            "ok": True,
            "local_calendar": calendar_mod.get_local_calendar(date=date),
            "google_calendar": calendar_mod.google_calendar_status(),
        })

    @app.route("/api/connections")
    def api_connections():
        return jsonify({"ok": True, "connections": connections_mod.list_all_status()})

    # -----------------------------------------------------------------
    # Tratamento de erros genéricos — nunca vaza traceback ao usuário
    # -----------------------------------------------------------------

    @app.errorhandler(404)
    def not_found(_exc):
        return jsonify({"ok": False, "error": "Rota não encontrada."}), 404

    @app.errorhandler(405)
    def method_not_allowed(_exc):
        return jsonify({"ok": False, "error": "Método não permitido para esta rota."}), 405

    @app.errorhandler(500)
    def server_error(exc):
        logger.exception("Erro interno do servidor")
        return jsonify({"ok": False, "error": "Erro interno do servidor."}), 500


app = create_app()

if __name__ == "__main__":
    port = env_int("PORT", 5000)
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    print(f"\n N.A.S.H rodando em http://127.0.0.1:{port}\n")
    app.run(host="127.0.0.1", port=port, debug=debug)
