"""
N.A.S.H - Servidor Flask principal.

Executar:
    python app.py

Ver README.md para instruções completas de instalação e configuração.
"""
import os
import logging

from flask import Flask, jsonify, redirect, render_template, request, url_for
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
    from backend.tools import lab as lab_mod
    from backend.memory import memory as memory_mod
    from backend.security import auth
    from backend.tools import email as email_mod
    from backend.security.audit import log_action
    from backend.security.validation import ValidationError

    ai_provider = build_provider()

    # Último erro real do provedor de IA, para o indicador de status não
    # afirmar "online" quando a IA não responde. Guardado em memória do
    # processo: em servidor sem estado, uma falha registrada numa instância
    # pode não ser vista por outra. É melhor-esforço de propósito — a
    # alternativa (validar a chave a cada verificação de saúde) gastaria uma
    # chamada de API a cada 20 segundos.
    _last_ai_error = [None]

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------

    def _history_limit() -> int:
        return app.config.get("MAX_HISTORY_MESSAGES", 30)

    def _recent_history() -> list[dict]:
        msgs = (
            auth.escopar(Message.query, Message)
            .filter(Message.role.in_(["user", "assistant"]))
            .order_by(Message.created_at.desc())
            .limit(_history_limit())
            .all()
        )
        msgs.reverse()
        return [{"role": m.role, "content": m.content} for m in msgs]

    def _save_message(role: str, content: str):
        db.session.add(auth.marcar_dono(Message(role=role, content=content)))
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
    # Porta de entrada
    # -----------------------------------------------------------------

    # Único conjunto de rotas alcançável sem sessão. A lista é de endpoints,
    # não de caminhos, e o guard abaixo NEGA tudo que não estiver aqui — de
    # modo que uma rota nova nasce protegida por esquecimento, não exposta.
    ROTAS_PUBLICAS = {
        "static",
        "pagina_login",
        "api_registrar",
        "api_login",
        "api_eu",
        "api_logout",
        "api_version",
        "api_esqueci_senha",
        "pagina_redefinir",
        "api_redefinir_senha",
    }

    @app.before_request
    def exigir_sessao():
        if request.endpoint in ROTAS_PUBLICAS or request.endpoint is None:
            return None
        if auth.usuario_atual():
            return None
        # Navegador pedindo página vai para a tela de login; chamada de API
        # recebe 401 para o front tratar sem redirecionar em segundo plano.
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": "Faça login para continuar."}), 401
        return redirect(url_for("pagina_login"))

    @app.route("/api/version")
    def api_version():
        """
        Qual código está realmente no ar.

        É público de propósito: serve justamente para conferir um deploy de
        fora, sem sessão. Já aconteceu de a Vercel reconstruir o commit antigo
        e o painel dizer "concluído" -- sem isto, a única forma de perceber era
        procurar um trecho de arquivo estático, que não distingue nada quando o
        arquivo não mudou.

        Expõe só o identificador do commit e a região. Nada de credencial,
        nada de configuração.
        """
        commit = (os.environ.get("VERCEL_GIT_COMMIT_SHA") or "").strip()
        return jsonify({
            "ok": True,
            "commit": commit[:7] or "desconhecido",
            "commit_completo": commit or None,
            "branch": os.environ.get("VERCEL_GIT_COMMIT_REF") or None,
            "regiao": os.environ.get("VERCEL_REGION") or None,
            "ambiente": os.environ.get("VERCEL_ENV") or "local",
        })

    @app.route("/login")
    def pagina_login():
        if auth.usuario_atual():
            return redirect(url_for("index"))
        return render_template("login.html")

    @app.route("/api/auth/registrar", methods=["POST"])
    def api_registrar():
        dados = request.get_json(silent=True) or {}
        try:
            usuario = auth.registrar(
                email=dados.get("email", ""),
                senha=dados.get("senha", ""),
                nome=dados.get("nome", ""),
            )
        except auth.AuthError as exc:
            return _json_error(exc.mensagem, exc.status)

        log_action("auth.registrar", detail=usuario.email, permission="READ", success=True)

        # Avisa quem pode liberar. Sem isto, o pedido so aparece se o adm
        # abrir o app e olhar -- e ninguem fica atualizando painel.
        if not usuario.aprovado:
            from backend.models import User
            for adm in User.query.filter_by(is_admin=True).all():
                _avisar(
                    email_mod.pedido_de_acesso_para_admin,
                    destinatario_admin=adm.email,
                    nome=usuario.name or "",
                    email=usuario.email,
                    link_painel=_endereco("/"),
                )
        if usuario.aprovado:
            auth.iniciar_sessao(usuario)
            return jsonify({"ok": True, "usuario": usuario.to_dict(), "liberado": True})
        return jsonify({
            "ok": True,
            "liberado": False,
            "mensagem": "Pedido enviado. Você poderá entrar assim que o "
                        "administrador liberar o seu acesso.",
        })

    @app.route("/api/auth/login", methods=["POST"])
    def api_login():
        dados = request.get_json(silent=True) or {}
        try:
            usuario = auth.autenticar(dados.get("email", ""), dados.get("senha", ""))
        except auth.AuthError as exc:
            log_action("auth.login", detail=exc.mensagem, permission="READ", success=False)
            return _json_error(exc.mensagem, exc.status)

        auth.iniciar_sessao(usuario)
        log_action("auth.login", detail=usuario.email, permission="READ", success=True)
        return jsonify({"ok": True, "usuario": usuario.to_dict()})

    @app.route("/api/auth/logout", methods=["POST"])
    def api_logout():
        auth.encerrar_sessao()
        return jsonify({"ok": True})

    def _avisar(funcao, *args, **kwargs) -> bool:
        """
        Dispara um aviso por e-mail sem deixar que ele derrube o fluxo.

        O módulo de e-mail já trata as próprias falhas, mas depender disso
        seria confiar que ele nunca vai mudar. Cadastro, aprovação e
        recuperação precisam funcionar com o Gmail fora do ar -- só sem aviso.
        """
        try:
            return bool(funcao(*args, **kwargs))
        except Exception:  # noqa: BLE001 — aviso nunca é motivo para falhar
            logger.exception("Falha ao enviar aviso por e-mail (fluxo segue)")
            return False

    def _endereco(caminho: str = "") -> str:
        """URL absoluta desta instalação — o link do e-mail precisa dela."""
        return request.url_root.rstrip("/") + caminho

    @app.route("/api/auth/esqueci", methods=["POST"])
    def api_esqueci_senha():
        """
        Pede um link de recuperação.

        Responde SEMPRE a mesma coisa, exista o e-mail ou não. Diferenciar
        transformaria esta rota numa forma de descobrir quem tem conta aqui --
        e ela é pública.
        """
        dados = request.get_json(silent=True) or {}
        email = (dados.get("email") or "").strip().lower()

        resposta = jsonify({
            "ok": True,
            "mensagem": "Se existir uma conta com esse e-mail, o link de "
                        "recuperação já está a caminho. Confira a caixa de entrada.",
        })

        from backend.models import User
        usuario = User.query.filter_by(email=email).first() if email else None
        if not usuario:
            return resposta

        token = auth.criar_token_de_recuperacao(usuario)
        enviado = _avisar(
            email_mod.recuperacao_de_senha,
            destinatario=usuario.email,
            nome=usuario.name or "",
            link=_endereco(f"/redefinir?token={token}"),
            validade_horas=auth.VALIDADE_TOKEN_HORAS,
        )
        log_action("auth.esqueci", detail=f"{usuario.email} enviado={enviado}",
                   permission="READ", success=enviado)
        return resposta

    @app.route("/redefinir")
    def pagina_redefinir():
        return render_template("redefinir.html", token=request.args.get("token", ""))

    @app.route("/api/auth/redefinir", methods=["POST"])
    def api_redefinir_senha():
        dados = request.get_json(silent=True) or {}
        try:
            usuario = auth.concluir_recuperacao(
                dados.get("token", ""), dados.get("nova_senha", "")
            )
        except auth.AuthError as exc:
            return _json_error(exc.mensagem, exc.status)

        log_action("auth.redefinir", detail=usuario.email, permission="WRITE", success=True)
        return jsonify({"ok": True, "mensagem": "Senha alterada. Já pode entrar."})

    @app.route("/api/auth/trocar-senha", methods=["POST"])
    @auth.login_required
    def api_trocar_senha():
        dados = request.get_json(silent=True) or {}
        try:
            auth.trocar_senha(
                auth.usuario_atual(),
                dados.get("senha_atual", ""),
                dados.get("nova_senha", ""),
            )
        except auth.AuthError as exc:
            return _json_error(exc.mensagem, exc.status)

        log_action("auth.trocar_senha", detail=auth.usuario_atual().email,
                   permission="WRITE", success=True)
        return jsonify({"ok": True, "mensagem": "Senha alterada."})

    @app.route("/api/admin/usuarios/<int:user_id>/redefinir-senha", methods=["POST"])
    @auth.admin_required
    def api_admin_redefinir_senha(user_id: int):
        try:
            usuario, temporaria = auth.redefinir_senha(user_id)
        except auth.AuthError as exc:
            return _json_error(exc.mensagem, exc.status)

        # A senha vai no log só como "quem", nunca o valor.
        log_action("auth.redefinir_senha", detail=usuario.email,
                   permission="WRITE", success=True)
        enviada = _avisar(
            email_mod.senha_redefinida_pelo_admin,
            usuario.email, usuario.name or "", temporaria, _endereco("/")
        )
        return jsonify({
            "ok": True,
            "usuario": usuario.to_dict(),
            "senha_temporaria": temporaria,
            "email_enviado": enviada,
            "mensagem": "Entregue esta senha à pessoa. Ela não será mostrada de novo.",
        })

    @app.route("/api/auth/eu")
    def api_eu():
        usuario = auth.usuario_atual()
        return jsonify({"ok": True, "usuario": usuario.to_dict() if usuario else None})

    # -----------------------------------------------------------------
    # Administração de acessos (somente adm)
    # -----------------------------------------------------------------

    @app.route("/api/admin/usuarios")
    @auth.admin_required
    def api_admin_usuarios():
        return jsonify({"ok": True, "usuarios": auth.listar_usuarios()})

    @app.route("/api/admin/usuarios/<int:user_id>/aprovar", methods=["POST"])
    @auth.admin_required
    def api_admin_aprovar(user_id: int):
        try:
            usuario = auth.aprovar(user_id)
        except auth.AuthError as exc:
            return _json_error(exc.mensagem, exc.status)
        log_action("auth.aprovar", detail=usuario.email, permission="WRITE", success=True)
        _avisar(email_mod.acesso_liberado, usuario.email, usuario.name or "", _endereco("/"))
        return jsonify({"ok": True, "usuario": usuario.to_dict()})

    @app.route("/api/admin/usuarios/<int:user_id>/recusar", methods=["POST"])
    @auth.admin_required
    def api_admin_recusar(user_id: int):
        try:
            usuario = auth.recusar(user_id)
        except auth.AuthError as exc:
            return _json_error(exc.mensagem, exc.status)
        log_action("auth.recusar", detail=usuario.email, permission="WRITE", success=True)
        return jsonify({"ok": True, "usuario": usuario.to_dict()})

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
            # Atenção ao significado: isto diz que HÁ uma credencial, não que
            # ela funciona. Uma chave inválida passa por aqui — quem sabe da
            # verdade é `ai_error`, preenchido quando uma chamada real falha.
            "ai_configured": ai_provider.is_configured(),
            "ai_model": ai_provider.model if ai_provider.is_configured() else None,
            "ai_error": getattr(ai_provider, "motivo", None) or _last_ai_error[0],
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
        # O modo voz avisa que a resposta vai ser OUVIDA, nao lida. Muda o
        # formato (sem listas, sem marcacao, curto), nunca o conteudo.
        modo_voz = bool(data.get("voz"))

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
            result = agent.run_chat_turn(
                ai_provider, history, user_message, modo_voz=modo_voz
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Erro inesperado no turno de chat")
            log_action("chat_turn_error", detail=str(exc), success=False)
            return jsonify({"ok": True, "type": "error", "text": f"Ocorreu um erro inesperado: {exc}"})

        # Uma resposta de erro significa que a IA nao respondeu de fato.
        # Registrar isso e o que permite o indicador dizer a verdade em vez
        # de mostrar "online" com a chave recusada.
        if result["type"] == "error":
            _last_ai_error[0] = result["text"]
        else:
            _last_ai_error[0] = None

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
        query = auth.escopar(PendingAction.query, PendingAction)
        if status_filter and status_filter != "all":
            query = query.filter_by(status=status_filter)
        items = query.order_by(PendingAction.created_at.desc()).limit(50).all()
        return jsonify({"ok": True, "pending_actions": [p.to_dict() for p in items]})

    def _confirm_or_cancel(pending_id: int, confirmed: bool):
        agent.expire_old_pending_actions()
        pending = auth.escopar(PendingAction.query, PendingAction).filter(
            PendingAction.id == pending_id
        ).first()
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

    # -----------------------------------------------------------------
    # Laboratório
    # -----------------------------------------------------------------

    @app.route("/api/lab", methods=["GET"])
    def api_list_lab():
        return jsonify({
            "ok": True,
            "entries": lab_mod.list_entries(
                status=request.args.get("status"),
                area=request.args.get("area"),
            ),
        })

    @app.route("/api/lab", methods=["POST"])
    def api_create_lab():
        dados = request.get_json(silent=True) or {}
        resultado, erro = _handle_mutation(
            lab_mod.create_entry,
            title=dados.get("title", ""),
            area=dados.get("area", "geral"),
            hypothesis=dados.get("hypothesis", ""),
            procedure=dados.get("procedure", ""),
            results=dados.get("results", ""),
            observations=dados.get("observations", ""),
            action="lab.criar",
        )
        if erro:
            return _json_error(*erro)
        return jsonify({"ok": True, "entry": resultado})

    @app.route("/api/lab/<int:entry_id>", methods=["PUT"])
    def api_update_lab(entry_id):
        dados = request.get_json(silent=True) or {}
        resultado, erro = _handle_mutation(
            lab_mod.update_entry, entry_id, action="lab.atualizar", **dados
        )
        if erro:
            return _json_error(*erro)
        return jsonify({"ok": True, "entry": resultado})

    @app.route("/api/lab/<int:entry_id>", methods=["DELETE"])
    def api_delete_lab(entry_id):
        resultado, erro = _handle_mutation(
            lab_mod.delete_entry, entry_id, action="lab.excluir", permission="DELETE"
        )
        if erro:
            return _json_error(*erro)
        return jsonify({"ok": True, "result": resultado})

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
