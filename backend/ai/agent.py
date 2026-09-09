"""
N.A.S.H / N.A.S.H - Orquestrador do agente de IA.

Monta:
SYSTEM PROMPT + MEMORIA + HISTORICO + FERRAMENTAS + MENSAGEM DO USUARIO

Executa ferramentas de leitura imediatamente.

Ferramentas de escrita/exclusao/servicos externos exigem
confirmacao explicita do usuario.

Tambem possui um FAST ROUTER local para comandos simples:
- calculadora
- porcentagem
- data
- hora
- dia da semana
- status do sistema

Isso evita chamar o Ollama para comandos determinísticos.
"""

import json
import logging
import ast
import operator
import math
import re

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from backend.ai.provider import AIProviderError, ModelWantedToolError
from backend.ai.tools_schema import get_tools_schema
from backend.security import permissions
from backend.security.audit import log_action
from backend.security.validation import ValidationError
from backend.memory import memory as memory_mod
from backend.tools import tasks, projects, calendar as calendar_mod, connections
from backend.security.auth import e_admin, escopar, marcar_dono
from backend.tools import composio_tools
from backend.models import db, PendingAction, Task, Project, Memory


logger = logging.getLogger("nash.agent")


MAX_TOOL_ITERATIONS = 6
PENDING_ACTION_EXPIRATION_MINUTES = 30


# ===========================================================================
# FERRAMENTAS
# ===========================================================================

READ_TOOL_NAMES = {
    "tool_list_tasks",
    "tool_list_projects",
    "tool_list_memories",
    "tool_get_calendar",
    "tool_get_datetime",
    "tool_search_web",
    "tool_spotify_search",
}


WRITE_TOOL_NAMES = {
    "tool_create_task",
    "tool_update_task",
    "tool_complete_task",
    "tool_delete_task",
    "tool_restore_task",
    "tool_delete_all_tasks",

    "tool_create_project",
    "tool_update_project",
    "tool_delete_project",

    "tool_save_memory",
    "tool_update_memory",
    "tool_delete_memory",
    "tool_delete_all_memories",

    "tool_spotify_control",
}


# ===========================================================================
# VERIFICACAO DE CONSISTENCIA DAS FERRAMENTAS
# ===========================================================================

def _check_tool_consistency():
    """
    Garante que:

    tools_schema.py
        ->
    permissions.py
        ->
    agent.py

    estejam sincronizados.
    """

    schema_names = {
        tool["function"]["name"]
        for tool in get_tools_schema()
    }

    dispatched_names = READ_TOOL_NAMES | WRITE_TOOL_NAMES

    permission_names = set(
        permissions.TOOL_PERMISSIONS.keys()
    )

    missing_dispatcher = schema_names - dispatched_names
    missing_schema = dispatched_names - schema_names
    missing_permission = schema_names - permission_names

    problems = []

    if missing_dispatcher:
        problems.append(
            "ferramentas no schema sem dispatcher: "
            f"{sorted(missing_dispatcher)}"
        )

    if missing_schema:
        problems.append(
            "ferramentas com dispatcher mas fora do schema: "
            f"{sorted(missing_schema)}"
        )

    if missing_permission:
        problems.append(
            "ferramentas no schema sem permissão declarada: "
            f"{sorted(missing_permission)}"
        )

    if problems:
        raise RuntimeError(
            "Inconsistencia entre tools_schema.py, permissions.py "
            "e agent.py — corrija antes de subir o servidor: "
            + " | ".join(problems)
        )


_check_tool_consistency()


# ===========================================================================
# INTEGRACOES EXTERNAS (Composio)
# ===========================================================================
#
# Registradas DEPOIS da checagem acima, de proposito: aquela verificacao cuida
# das ferramentas NATIVAS, cujo schema, permissao e dispatcher moram neste
# repositorio. As acoes do Composio vem de catalogo externo e somem se a
# conexao for revogada -- exigir que estejam sempre presentes faria o servidor
# recusar iniciar por causa de um servico de terceiro fora do ar.

COMPOSIO_READ_NAMES = {
    slug for slug, perm in composio_tools.ACOES.items() if perm == permissions.READ
}
COMPOSIO_WRITE_NAMES = set(composio_tools.ACOES) - COMPOSIO_READ_NAMES

# O sistema de permissao precisa conhecer as acoes externas para aplicar o
# cartao de confirmacao a todas que escrevem.
permissions.TOOL_PERMISSIONS.update(composio_tools.ACOES)

# Palavra na mensagem -> servico externo oferecido naquele turno. Sem este
# filtro, os ~5.800 tokens do catalogo inteiro viajariam em toda pergunta e
# estourariam sozinhos o teto de 6.000 tokens/minuto da camada gratuita.
GATILHOS_COMPOSIO = {
    "gmail":          ("email", "e-mail", "mail", "caixa de entrada", "inbox", "remetente"),
    "googlecalendar": ("agenda", "calendario", "calendário", "compromisso", "evento",
                       "reuniao", "reunião", "marcar", "agendar", "horário livre"),
    "googledrive":    ("drive", "arquivo", "pasta"),
    "googledocs":     ("docs", "documento", "redigir"),
    "googlesheets":   ("planilha", "sheets", "tabela"),
    "notion":         ("notion",),
    "youtube":        ("youtube", "video", "vídeo"),
}


def servicos_externos_relevantes(mensagem: str) -> set[str]:
    baixa = (mensagem or "").lower()
    return {
        servico
        for servico, gatilhos in GATILHOS_COMPOSIO.items()
        if any(g in baixa for g in gatilhos)
    }


def schemas_externos_para(mensagem: str) -> list[dict]:
    """Esquemas das acoes externas dos servicos citados na mensagem."""
    # As contas conectadas (Gmail, Agenda, Drive) sao de uma pessoa so: a dona
    # do projeto. Usuario comum aprovado NAO recebe estas ferramentas -- sem
    # isto, qualquer acesso liberado leria o e-mail dela pelo chat.
    if not e_admin():
        return []
    servicos = servicos_externos_relevantes(mensagem)
    if not servicos:
        return []
    return [
        s for s in composio_tools.get_schemas()
        if s["function"]["name"].split("_", 1)[0].lower() in servicos
    ]


# ===========================================================================
# SYSTEM PROMPT
# ===========================================================================

SYSTEM_PROMPT_TEMPLATE = """Você é N.A.S.H, um assistente pessoal de IA, parceiro de estudos e centro de comando \
do usuário. Sua identidade é própria e independente.

PERSONALIDADE:
Inteligente, educado, objetivo, natural, levemente sofisticado, proativo e técnico quando necessário, \
mas também capaz de conversar casualmente.

Nunca soe como um chatbot robótico.

Adapte a linguagem ao usuário:
- Se pedirem para explicar como iniciante, simplifique.
- Se pedirem nível universitário, aprofunde.
- Se pedirem "só a resposta", seja conciso.
- Se pedirem "passo a passo", detalhe tudo.

MODO ESPECIALISTA:

Para perguntas de matemática, física, química, biologia, tecnologia, programação, engenharia, astronomia \
ou eletrônica, ao resolver um problema estruture assim quando fizer sentido:

1. O que o problema pede.
2. Dados fornecidos.
3. Conceitos e fórmulas necessários.
4. Explicação das variáveis.
5. Substituição dos valores.
6. Cálculo.
7. Verificação de unidades e resultado.
8. Resposta final.

Use LaTeX/Markdown quando ajudar.

Exemplo:

$$F = ma$$

Use tabelas, listas e blocos de código quando apropriado.

FERRAMENTAS E CONFIRMAÇÃO:

Você possui ferramentas para gerenciar tarefas, projetos e memória.

SEMPRE chame a ferramenta apropriada quando o pedido exigir — inclusive para
criar, alterar ou excluir.

Entenda como a confirmação funciona aqui: chamar a ferramenta NÃO executa a
ação. O sistema intercepta a chamada e mostra ao usuário um cartão de
Confirmar/Cancelar. Nada é gravado enquanto ele não confirmar.

Portanto, NUNCA peça permissão por escrito antes de chamar a ferramenta.
Perguntar "deseja que eu crie?" não gera a confirmação — apenas trava o
pedido, e a ação nunca chega a ser proposta. Quem pergunta é o sistema, não
você. Se faltar um dado obrigatório, use um valor razoável ou pergunte
apenas o que for realmente indispensável.

O que você nunca deve fazer é afirmar que algo já aconteceu. Só diga
"salvei", "criei", "atualizei" ou "excluí" depois que o sistema informar que
a ação foi confirmada e executada.

INTEGRAÇÕES EXTERNAS:

Nunca finja que Spotify, Google Calendar, Gmail, Outlook ou mensagens estão conectados.

O status real das conexões está listado abaixo.

Confie apenas nesse status.

BUSCA WEB:

Você só possui acesso à web quando a ferramenta tool_search_web retornar um resultado real.

Se a ferramenta informar que não existe acesso, informe isso claramente ao usuário.

Nunca invente resultados de pesquisa.

MEMÓRIA ATUAL DO USUÁRIO:

{memory_snapshot}

STATUS DAS CONEXÕES EXTERNAS:

{connections_status}
"""


def _connections_status_text() -> str:
    statuses = connections.list_all_status()

    lines = []

    for status in statuses:
        estado = (
            "conectado"
            if status["connected"]
            else "NÃO conectado"
        )

        lines.append(
            f"- {status['service']}: {estado}"
        )

    return "\n".join(lines)


# Regra de estilo acrescentada SO quando a resposta vai ser falada. O modo
# especialista, com seus 8 passos, e otimo lido na tela e insuportavel ouvido:
# "10 x 10" virava uma aula. Isto muda a FORMA, nunca o conteudo nem as
# permissoes.
INSTRUCAO_VOZ = """

MODO VOZ (esta resposta vai ser OUVIDA, não lida):

Fale como alguém falaria em voz alta, não como um documento.

- Responda direto. Pergunta simples ("quanto é 10 vezes 10") merece a resposta e mais nada: "Cem." Nunca aplique a estrutura numerada do modo especialista aqui.
- No máximo 2 ou 3 frases, a menos que peçam explicação passo a passo.
- Nada de listas, títulos, tabelas, marcação, emoji, aspas decorativas ou fórmulas escritas. Diga "dez ao quadrado", não "10^2".
- Nada de repetir a pergunta antes de responder.
- Se a resposta for naturalmente longa, dê o essencial em voz e ofereça o detalhe: "Quer que eu detalhe?"
"""


def build_system_prompt(modo_voz: bool = False) -> str:

    prompt = SYSTEM_PROMPT_TEMPLATE.format(
        memory_snapshot=memory_mod.memory_context_snapshot(),
        connections_status=_connections_status_text(),
    )

    if modo_voz:
        prompt += INSTRUCAO_VOZ

    print(
        "[N.A.S.H PROMPT]",
        len(prompt),
        "caracteres"
    )

    return prompt


# ===========================================================================
# DISPATCH DE LEITURA
# ===========================================================================

def _dispatch_read(tool_name: str, args: dict) -> dict:

    # Acao externa (Composio) de leitura: Gmail, Agenda, Drive, Docs, Sheets,
    # Notion, YouTube. Executa direto, como qualquer leitura.
    if tool_name in COMPOSIO_READ_NAMES:
        if not e_admin():
            return {"ok": False, "message":
                    "Ações em serviços externos são restritas ao administrador."}
        return composio_tools.executar(tool_name, args)

    try:

        if tool_name == "tool_list_tasks":

            return {
                "tasks": tasks.list_tasks(
                    status=args.get("status")
                )
            }

        if tool_name == "tool_list_projects":

            return {
                "projects": projects.list_projects()
            }

        if tool_name == "tool_list_memories":

            return {
                "memories": memory_mod.list_memories()
            }

        if tool_name == "tool_get_calendar":

            return {
                "local_calendar": calendar_mod.get_local_calendar(
                    date=args.get("date")
                ),
                "google_calendar": calendar_mod.google_calendar_status(),
            }

        if tool_name == "tool_get_datetime":

            now = datetime.now(
                ZoneInfo("America/Sao_Paulo")
            )

            return {
                "date": now.strftime("%Y-%m-%d"),
                "time": now.strftime("%H:%M:%S"),
                "day_of_week": now.strftime("%A"),
            }

        if tool_name == "tool_search_web":

            return {
                "ok": False,
                "message": "Busca web não configurada nesta instalação.",
            }

        if tool_name == "tool_spotify_search":

            return connections.spotify_search(
                query=args.get("query", "")
            )

    except ValidationError as exc:

        return {
            "ok": False,
            "message": str(exc),
        }

    except Exception as exc:

        logger.exception(
            "Erro ao executar ferramenta de leitura %s",
            tool_name
        )

        return {
            "ok": False,
            "message": f"Erro ao executar {tool_name}: {exc}",
        }

    return {
        "ok": False,
        "message": f"Ferramenta de leitura desconhecida: {tool_name}",
    }


# ===========================================================================
# EXECUCAO DE FERRAMENTAS DE ESCRITA
# ===========================================================================

def execute_write_tool(tool_name: str, args: dict) -> dict:

    # Acao externa confirmada pelo usuario. So chega aqui depois do cartao.
    if tool_name in COMPOSIO_WRITE_NAMES:
        if not e_admin():
            return {"ok": False, "message":
                    "Ações em serviços externos são restritas ao administrador."}
        return composio_tools.executar(tool_name, args)

    if tool_name == "tool_create_task":
        return tasks.create_task(**args)

    if tool_name == "tool_update_task":

        args = dict(args)

        task_id = args.pop("task_id")

        return tasks.update_task(
            task_id,
            **args
        )

    if tool_name == "tool_complete_task":

        return tasks.complete_task(
            args["task_id"]
        )

    if tool_name == "tool_delete_task":

        return tasks.delete_task(
            args["task_id"]
        )

    if tool_name == "tool_restore_task":

        return tasks.restore_task(
            args["task_id"]
        )

    if tool_name == "tool_delete_all_tasks":

        return tasks.delete_all_tasks()

    if tool_name == "tool_create_project":

        return projects.create_project(**args)

    if tool_name == "tool_update_project":

        args = dict(args)

        project_id = args.pop("project_id")

        return projects.update_project(
            project_id,
            **args
        )

    if tool_name == "tool_delete_project":

        return projects.delete_project(
            args["project_id"]
        )

    if tool_name == "tool_save_memory":

        return memory_mod.save_memory(**args)

    if tool_name == "tool_update_memory":

        args = dict(args)

        memory_id = args.pop("memory_id")

        return memory_mod.update_memory(
            memory_id,
            **args
        )

    if tool_name == "tool_delete_memory":

        return memory_mod.delete_memory(
            args["memory_id"]
        )

    if tool_name == "tool_delete_all_memories":

        return memory_mod.delete_all_memories()

    if tool_name == "tool_spotify_control":

        return connections.spotify_control(
            **args
        )

    raise ValueError(
        f"Ferramenta de escrita desconhecida: {tool_name}"
    )


# ===========================================================================
# DESCRICAO DAS ACOES
# ===========================================================================

def _describe_action(tool_name: str, args: dict) -> str:

    # Sem isto, o cartao mostraria o slug cru (GMAIL_SEND_EMAIL) a quem so
    # quer saber o que vai acontecer com os dados dele.
    if tool_name in composio_tools.ACOES:
        return composio_tools.descreve(tool_name, args)

    if tool_name == "tool_create_task":

        partes = [
            f'Vou criar a tarefa: "{args.get("title", "").strip()}".'
        ]

        if args.get("date"):
            partes.append(
                f"Data: {args['date']}."
            )

        if args.get("time"):
            partes.append(
                f"Horário: {args['time']}."
            )

        if args.get("priority"):
            partes.append(
                f"Prioridade: {args['priority']}."
            )

        return (
            " ".join(partes)
            + " Confirmar?"
        )

    if tool_name == "tool_update_task":

        task = escopar(Task.query, Task).filter(
            Task.id == args.get("task_id")
        ).first()

        nome = (
            f'"{task.title}"'
            if task
            else f'#{args.get("task_id")}'
        )

        campos = [
            key
            for key in (
                "title",
                "description",
                "date",
                "time",
                "priority",
            )
            if args.get(key) is not None
        ]

        return (
            f"Vou atualizar a tarefa {nome} "
            f"({', '.join(campos) or 'sem alterações'}). "
            "Confirmar?"
        )

    if tool_name == "tool_complete_task":

        task = escopar(Task.query, Task).filter(
            Task.id == args.get("task_id")
        ).first()

        nome = (
            f'"{task.title}"'
            if task
            else f'#{args.get("task_id")}'
        )

        return (
            f"Vou marcar a tarefa {nome} "
            "como concluída. Confirmar?"
        )

    if tool_name == "tool_delete_task":

        task = escopar(Task.query, Task).filter(
            Task.id == args.get("task_id")
        ).first()

        nome = (
            f'"{task.title}"'
            if task
            else f'#{args.get("task_id")}'
        )

        return (
            f"Vou excluir a tarefa {nome}. "
            "Ela poderá ser restaurada depois. Confirmar?"
        )

    if tool_name == "tool_restore_task":

        task = escopar(Task.query, Task).filter(
            Task.id == args.get("task_id")
        ).first()

        nome = (
            f'"{task.title}"'
            if task
            else f'#{args.get("task_id")}'
        )

        return (
            f"Vou restaurar a tarefa {nome}. "
            "Confirmar?"
        )

    if tool_name == "tool_delete_all_tasks":

        total = tasks.count_active_tasks()

        return (
            f"Isso apagará {total} tarefa(s) "
            "permanentemente da lista ativa. "
            "Deseja confirmar?"
        )

    if tool_name == "tool_create_project":

        return (
            f'Vou criar o projeto '
            f'"{args.get("name", "").strip()}". '
            "Confirmar?"
        )

    if tool_name == "tool_update_project":

        project = escopar(Project.query, Project).filter(
            Project.id == args.get("project_id")
        ).first()

        nome = (
            f'"{project.name}"'
            if project
            else f'#{args.get("project_id")}'
        )

        campos = [
            key
            for key in (
                "name",
                "description",
                "objectives",
                "notes",
                "progress",
                "status",
            )
            if args.get(key) is not None
        ]

        return (
            f"Vou atualizar o projeto {nome} "
            f"({', '.join(campos) or 'sem alterações'}). "
            "Confirmar?"
        )

    if tool_name == "tool_delete_project":

        project = escopar(Project.query, Project).filter(
            Project.id == args.get("project_id")
        ).first()

        nome = (
            f'"{project.name}"'
            if project
            else f'#{args.get("project_id")}'
        )

        return (
            f"Vou excluir o projeto {nome}. "
            "As tarefas ligadas a ele NÃO serão apagadas, "
            "apenas desvinculadas. Confirmar?"
        )

    if tool_name == "tool_save_memory":

        return (
            "Posso salvar isto na sua memória: "
            f'"{args.get("content", "").strip()}". '
            "Deseja confirmar?"
        )

    if tool_name == "tool_update_memory":

        mem = escopar(Memory.query, Memory).filter(
            Memory.id == args.get("memory_id")
        ).first()

        trecho = (
            f'"{mem.content[:60]}..."'
            if mem
            else f'#{args.get("memory_id")}'
        )

        return (
            f"Vou atualizar a memória {trecho}. "
            "Confirmar?"
        )

    if tool_name == "tool_delete_memory":

        mem = escopar(Memory.query, Memory).filter(
            Memory.id == args.get("memory_id")
        ).first()

        trecho = (
            f'"{mem.content[:60]}..."'
            if mem
            else f'#{args.get("memory_id")}'
        )

        return (
            f"Vou excluir a memória {trecho}. "
            "Confirmar?"
        )

    if tool_name == "tool_delete_all_memories":

        total = len(
            memory_mod.list_memories()
        )

        return (
            f"Isso apagará TODAS as {total} "
            "memória(s) salvas, de forma irreversível. "
            "Deseja confirmar?"
        )

    if tool_name == "tool_spotify_control":

        return (
            f"Vou enviar o comando "
            f"'{args.get('action')}' para o Spotify. "
            "Confirmar?"
        )

    return (
        f"Vou executar a ação "
        f"'{tool_name}'. Confirmar?"
    )


# ===========================================================================
# PENDING ACTION
# ===========================================================================

def create_pending_action(
    tool_name: str,
    args: dict
) -> PendingAction:

    description = _describe_action(
        tool_name,
        args
    )

    pending = PendingAction(
        tool_name=tool_name,
        arguments=json.dumps(
            args,
            ensure_ascii=False
        ),
        description=description,
        permission=permissions.get_permission(
            tool_name
        ),
        status="pendente",
    )
    marcar_dono(pending)

    db.session.add(pending)

    db.session.commit()

    log_action(
        "pending_action_created",
        detail=f"{tool_name}: {description}",
        permission=pending.permission,
    )

    return pending


def expire_old_pending_actions(
    minutes: int = PENDING_ACTION_EXPIRATION_MINUTES
) -> int:

    cutoff = (
        datetime.utcnow()
        - timedelta(minutes=minutes)
    )

    stale = PendingAction.query.filter(
        PendingAction.status == "pendente",
        PendingAction.created_at < cutoff,
    ).all()

    for pending in stale:

        pending.status = "expirada"

        pending.resolved_at = datetime.utcnow()

    if stale:

        db.session.commit()

        log_action(
            "pending_actions_expired",
            detail=f"{len(stale)} ação(ões) expirada(s)"
        )

    return len(stale)


# ===========================================================================
# CALCULADORA SEGURA
# ===========================================================================

def _safe_calculate(expression: str):

    """
    Calculadora matemática local e restrita.

    Operadores:
        +
        -
        *
        /
        //
        %
        **

    Funções:
        sqrt(x)
        sin(x)
        cos(x)
        tan(x)
        log(x)
        log10(x)
        ln(x)
        abs(x)

    Constantes:
        pi
        e

    Trigonometria utiliza GRAUS:

        sin(30) = 0.5
        cos(60) = 0.5
        tan(45) = 1
    """

    operators = {

        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,

        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
    }

    functions = {

        "sqrt": math.sqrt,

        "log": math.log,

        "log10": math.log10,

        "ln": math.log,

        "abs": abs,

        "sin": lambda x:
            math.sin(math.radians(x)),

        "cos": lambda x:
            math.cos(math.radians(x)),

        "tan": lambda x:
            math.tan(math.radians(x)),
    }

    constants = {

        "pi": math.pi,

        "e": math.e,
    }

    def evaluate(node):

        # ---------------------------------------------------------------
        # NUMEROS
        # ---------------------------------------------------------------

        if isinstance(
            node,
            ast.Constant
        ):

            if (
                isinstance(
                    node.value,
                    (int, float)
                )
                and not isinstance(
                    node.value,
                    bool
                )
            ):
                return node.value

            raise ValueError(
                "Valor inválido."
            )

        # ---------------------------------------------------------------
        # CONSTANTES
        # ---------------------------------------------------------------

        if isinstance(
            node,
            ast.Name
        ):

            if node.id in constants:

                return constants[node.id]

            raise ValueError(
                f"Constante desconhecida: {node.id}"
            )

        # ---------------------------------------------------------------
        # OPERACOES
        # ---------------------------------------------------------------

        if isinstance(
            node,
            ast.BinOp
        ):

            left = evaluate(
                node.left
            )

            right = evaluate(
                node.right
            )

            operation = operators.get(
                type(node.op)
            )

            if operation is None:

                raise ValueError(
                    "Operação não permitida."
                )

            if isinstance(
                node.op,
                ast.Pow
            ):

                if abs(right) > 100:

                    raise ValueError(
                        "Expoente muito grande."
                    )

            result = operation(
                left,
                right
            )

            if (
                isinstance(
                    result,
                    (int, float)
                )
                and abs(result) > 1e100
            ):

                raise ValueError(
                    "Resultado muito grande."
                )

            return result

        # ---------------------------------------------------------------
        # +X / -X
        # ---------------------------------------------------------------

        if isinstance(
            node,
            ast.UnaryOp
        ):

            operation = operators.get(
                type(node.op)
            )

            if operation is None:

                raise ValueError(
                    "Operação não permitida."
                )

            return operation(
                evaluate(node.operand)
            )

        # ---------------------------------------------------------------
        # FUNCOES
        # ---------------------------------------------------------------

        if isinstance(
            node,
            ast.Call
        ):

            if not isinstance(
                node.func,
                ast.Name
            ):

                raise ValueError(
                    "Função não permitida."
                )

            function_name = node.func.id

            if function_name not in functions:

                raise ValueError(
                    f"Função '{function_name}' não permitida."
                )

            if len(node.args) != 1:

                raise ValueError(
                    f"A função '{function_name}' "
                    "aceita exatamente um argumento."
                )

            value = evaluate(
                node.args[0]
            )

            result = functions[
                function_name
            ](value)

            if not math.isfinite(
                result
            ):

                raise ValueError(
                    "Resultado inválido."
                )

            return result

        raise ValueError(
            "Expressão não permitida."
        )

    tree = ast.parse(
        expression,
        mode="eval"
    )

    return evaluate(
        tree.body
    )


# ===========================================================================
# FAST ROUTER
# ===========================================================================

def _fast_command(
    user_message: str
) -> dict | None:

    """
    Resolve comandos simples sem chamar o Ollama.

    Retorna:

        {"type": "message", "text": "..."}

    ou:

        None

    quando o comando deve seguir para o Ollama.
    """

    text = user_message.strip().lower()

    # ===================================================================
    # PORCENTAGEM
    # ===================================================================

    percent_match = re.match(
        r"^\s*(\d+(?:[.,]\d+)?)\s*%\s*"
        r"(?:de|da|do)\s*"
        r"(\d+(?:[.,]\d+)?)\s*$",
        text,
    )

    if percent_match:

        percentage = float(
            percent_match.group(1)
            .replace(",", ".")
        )

        value = float(
            percent_match.group(2)
            .replace(",", ".")
        )

        result = (
            percentage / 100
        ) * value

        return {
            "type": "message",
            "text": (
                f"{percentage:g}% de "
                f"{value:g} é **{result:g}**."
            ),
        }

    # ===================================================================
    # CALCULADORA
    # ===================================================================

    calculator_expression = text

    # Simbolos matematicos

    replacements = {

        "×": "*",

        "÷": "/",

        "−": "-",

        "π": "pi",
    }

    for old, new in replacements.items():

        calculator_expression = (
            calculator_expression.replace(
                old,
                new
            )
        )

    # Prefixos naturais

    calculator_prefixes = (

        "quanto é ",

        "quanto e ",

        "calcule ",

        "calcula ",

        "calcular ",
    )

    for prefix in calculator_prefixes:

        if calculator_expression.startswith(
            prefix
        ):

            calculator_expression = (
                calculator_expression[
                    len(prefix):
                ].strip()
            )

            break

    # Matematica FALADA. Por voz ninguem diz "asterisco": diz "dez vezes dez",
    # que a transcricao entrega como "10 x 10" ou "10 vezes 10". Sem isto a
    # conta mais simples escapava do roteador e ia para o modelo, que aplicava
    # a estrutura de 8 passos do modo especialista a um "10 x 10" -- era essa a
    # resposta arrastada que a pessoa ouvia.
    #
    # A troca so vale entre numeros: converter "x" solto quebraria funcoes e
    # frases comuns.
    calculator_expression = re.sub(
        r"(?<=\d)\s*[xX×]\s*(?=\d)", "*", calculator_expression
    )

    faladas = (
        (r"\bdividido\s+por\b", "/"),
        (r"\bdividido\b",      "/"),
        (r"\bvezes\b",         "*"),
        (r"\bmultiplicado\s+por\b", "*"),
        (r"\bmais\b",          "+"),
        (r"\bmenos\b",         "-"),
        (r"\bpor\s+cento\b",   "%"),
    )
    convertida = calculator_expression
    for padrao, simbolo in faladas:
        convertida = re.sub(padrao, simbolo, convertida)

    # Só aceita a versão falada se o resultado virar aritmética pura. Assim
    # "me fale mais sobre física" não vira "me fale + sobre física" e continua
    # indo para o modelo, que é onde ela deve ir.
    if re.fullmatch(r"[0-9+\-*/().%\s]+", convertida.strip() or "x"):
        calculator_expression = convertida

    # Decimal brasileiro

    calculator_expression = re.sub(
        r"(?<=\d),(?=\d)",
        ".",
        calculator_expression
    )

    # -------------------------------------------------------------------
    # Permite:
    #
    # números
    # operadores
    # parênteses
    # ponto
    # letras das funções
    # constantes pi/e
    # -------------------------------------------------------------------

    allowed_pattern = re.compile(
        r"^[0-9a-zA-Z_+\-*/().%\s]+$"
    )

    scientific_names = {
        "sqrt",
        "sin",
        "cos",
        "tan",
        "log",
        "log10",
        "ln",
        "abs",
        "pi",
        "e",
    }

    if (
        calculator_expression
        and len(calculator_expression) <= 100
        and any(
            char.isdigit()
            for char in calculator_expression
        )
        and allowed_pattern.fullmatch(
            calculator_expression
        )
    ):

        # ---------------------------------------------------------------
        # Segurança adicional:
        # somente nomes conhecidos podem aparecer.
        # ---------------------------------------------------------------

        names = re.findall(
            r"\b[a-zA-Z_][a-zA-Z0-9_]*\b",
            calculator_expression
        )

        unknown_names = [
            name
            for name in names
            if name not in scientific_names
        ]

        if not unknown_names:

            try:

                expression = (
                    calculator_expression
                    .replace("%", "/100")
                )

                result = _safe_calculate(
                    expression
                )

                if isinstance(
                    result,
                    float
                ):

                    formatted = (
                        f"{result:.10f}"
                        .rstrip("0")
                        .rstrip(".")
                    )

                else:

                    formatted = str(
                        result
                    )

                return {
                    "type": "message",
                    "text": (
                        f"O resultado é **{formatted}**."
                    ),
                }

            except (
                ValueError,
                ZeroDivisionError,
                SyntaxError,
                OverflowError,
                TypeError,
            ):

                pass

    # ===================================================================
    # DATA / HORA
    # ===================================================================

    now = datetime.now(
        ZoneInfo("America/Sao_Paulo")
    )

    # ===================================================================
    # HORA
    # ===================================================================

    if any(
        term in text
        for term in (

            "que horas são",

            "que horas sao",

            "qual a hora",

            "qual é a hora",

            "qual e a hora",

            "horário atual",

            "horario atual",

            "hora atual",
        )
    ):

        return {

            "type": "message",

            "text": (
                "Agora são "
                f"{now.strftime('%H:%M:%S')} "
                "em São Paulo."
            ),
        }

    # ===================================================================
    # DATA
    # ===================================================================

    if any(
        term in text
        for term in (

            "qual a data",

            "qual é a data",

            "qual e a data",

            "data de hoje",

            "data atual",

            "que data é hoje",

            "que data e hoje",

            "que data é hj",
        )
    ):

        return {

            "type": "message",

            "text": (
                "Hoje é "
                f"{now.strftime('%d/%m/%Y')}."
            ),
        }

    # ===================================================================
    # DIA DA SEMANA
    # ===================================================================

    if any(
        term in text
        for term in (

            "que dia é hoje",

            "que dia e hoje",

            "que dia é hj",

            "qual o dia de hoje",

            "dia da semana",
        )
    ):

        dias = {

            "Monday":
                "segunda-feira",

            "Tuesday":
                "terça-feira",

            "Wednesday":
                "quarta-feira",

            "Thursday":
                "quinta-feira",

            "Friday":
                "sexta-feira",

            "Saturday":
                "sábado",

            "Sunday":
                "domingo",
        }

        dia = dias[
            now.strftime("%A")
        ]

        return {

            "type": "message",

            "text": (
                f"Hoje é {dia}, "
                f"{now.strftime('%d/%m/%Y')}."
            ),
        }

    # ===================================================================
    # STATUS
    # ===================================================================

    if any(
        term in text
        for term in (

            "você está online",

            "voce esta online",

            "sistema está online",

            "sistema esta online",

            "status do sistema",

            "status do nash",

            "status do assistente",
        )
    ):

        return {

            "type": "message",

            "text": (
                "N.A.S.H está online "
                "e o processamento local "
                "está funcionando."
            ),
        }

    # ===================================================================
    # NENHUM COMANDO LOCAL
    # ===================================================================

    return None


# ===========================================================================
# LOOP PRINCIPAL DO AGENTE
# ===========================================================================

def run_chat_turn(
    provider,
    history: list[dict],
    user_message: str,
    modo_voz: bool = False
) -> dict:

    """
    Executa um turno completo.

    Retornos:

        {
            "type": "message",
            "text": "..."
        }

        {
            "type": "confirmation_required",
            "text": "...",
            "pending_action": {...}
        }

        {
            "type": "error",
            "text": "..."
        }
    """

    # -------------------------------------------------------------------
    # Expira ações antigas
    # -------------------------------------------------------------------

    expire_old_pending_actions()

    # -------------------------------------------------------------------
    # FAST ROUTER
    # -------------------------------------------------------------------

    fast_result = _fast_command(
        user_message
    )

    if fast_result is not None:

        print(
            "[FAST ROUTER] comando local — "
            "Ollama não utilizado"
        )

        return fast_result

    # -------------------------------------------------------------------
    # SYSTEM PROMPT
    # -------------------------------------------------------------------

    messages = [

        {
            "role": "system",
            "content": build_system_prompt(modo_voz),
        }

    ]

    print(
        "[HISTORICO]",
        len(history),
        "mensagens"
    )

    # -------------------------------------------------------------------
    # Historico limitado
    # -------------------------------------------------------------------

    messages.extend(
        history[-4:]
    )

    # -------------------------------------------------------------------
    # Mensagem atual
    # -------------------------------------------------------------------

    messages.append(
        {
            "role": "user",
            "content": user_message,
        }
    )

    # -------------------------------------------------------------------
    # Decide se precisa disponibilizar ferramentas
    # -------------------------------------------------------------------

    message_lower = (
        user_message.lower()
    )

    ACTION_PATTERNS = (

        "hora",
        "horas",
        "horário",
        "horario",

        "data",

        "dia",

        "tarefa",
        "tarefas",

        "projeto",
        "projetos",

        "memória",
        "memoria",

        "agenda",

        "calendário",
        "calendario",

        "tocar",
        "pausar",

        "música",
        "musica",

        "playlist",

        "spotify",

        "criar",
        "crie",

        "adicionar",
        "adicione",

        "salvar",

        "lembre",

        "lembrar",

        "lembra",

        "listar",

        "mostrar",

        "minhas",
    )

    needs_tools = any(
        pattern in message_lower
        for pattern in ACTION_PATTERNS
    )

    tools_schema = (
        get_tools_schema()
        if needs_tools
        else []
    )

    # Acoes externas so entram quando a mensagem cita o servico. O catalogo
    # inteiro custa ~5.800 tokens; mandado em toda pergunta, estouraria
    # sozinho o teto de 6.000 tokens/minuto da camada gratuita do provedor.
    externos = schemas_externos_para(user_message)
    if externos:
        tools_schema = list(tools_schema) + externos
        print(
            f"[EXTERNOS] {len(externos)} acao(oes) de "
            f"{sorted(servicos_externos_relevantes(user_message))}"
        )

    known_tool_names = {
        tool["function"]["name"]
        for tool in tools_schema
    }

    # -------------------------------------------------------------------
    # LOOP DE FERRAMENTAS
    # -------------------------------------------------------------------

    for _ in range(
        MAX_TOOL_ITERATIONS
    ):

        try:

            response = provider.chat(
                messages,
                tools=tools_schema
            )

        except ModelWantedToolError as exc:

            # A aposta de "esta mensagem nao pede acao" foi por palavra-chave,
            # e o modelo discordou. Sem tratamento, um simples "ola" morre com
            # 400 e o erro cru da API aparece na tela.
            #
            # Refaz UMA vez oferecendo o catalogo. Se ja havia ferramentas na
            # chamada, o problema e outro e insistir so gastaria tokens.
            if tools_schema:
                return {
                    "type": "error",
                    "text": str(exc),
                }

            tools_schema = list(get_tools_schema()) + externos
            known_tool_names = {
                tool["function"]["name"]
                for tool in tools_schema
            }
            logger.info(
                "Modelo pediu ferramenta sem que houvesse: refazendo com %d ferramenta(s).",
                len(tools_schema),
            )
            continue

        except AIProviderError as exc:

            return {
                "type": "error",
                "text": str(exc),
            }

        # ----------------------------------------------------------------
        # Resposta normal
        # ----------------------------------------------------------------

        if not response.has_tool_calls:

            return {

                "type": "message",

                "text": response.text or "",
            }

        # ----------------------------------------------------------------
        # Registra resposta do assistente
        # ----------------------------------------------------------------

        messages.append(

            {
                "role": "assistant",

                "content": (
                    response.text
                    or None
                ),

                "tool_calls": [

                    {
                        "id": tc.id,

                        "type": "function",

                        "function": {

                            "name": tc.name,

                            "arguments": json.dumps(
                                tc.arguments,
                                ensure_ascii=False
                            ),
                        },
                    }

                    for tc in response.tool_calls
                ],
            }

        )

        pending_found = None

        # ----------------------------------------------------------------
        # Processa ferramentas
        # ----------------------------------------------------------------

        for tc in response.tool_calls:

            # ------------------------------------------------------------
            # Ferramenta desconhecida
            # ------------------------------------------------------------

            if tc.name not in known_tool_names:

                logger.warning(
                    "Modelo tentou chamar ferramenta desconhecida: %s",
                    tc.name
                )

                messages.append(

                    {
                        "role": "tool",

                        "tool_call_id": tc.id,

                        "content": json.dumps(
                            {
                                "ok": False,

                                "message": (
                                    f"Ferramenta "
                                    f"'{tc.name}' "
                                    "não existe."
                                ),
                            },
                            ensure_ascii=False
                        ),
                    }

                )

                continue

            # ------------------------------------------------------------
            # Ferramenta que exige confirmação
            # ------------------------------------------------------------

            if permissions.requires_confirmation(
                tc.name
            ):

                pending_found = (
                    create_pending_action(
                        tc.name,
                        tc.arguments
                    )
                )

                messages.append(

                    {
                        "role": "tool",

                        "tool_call_id": tc.id,

                        "content": json.dumps(
                            {
                                "status":
                                    "aguardando_confirmacao"
                            },
                            ensure_ascii=False
                        ),
                    }

                )

                break

            # ------------------------------------------------------------
            # Ferramenta de leitura
            # ------------------------------------------------------------

            else:

                result = _dispatch_read(
                    tc.name,
                    tc.arguments
                )

                messages.append(

                    {
                        "role": "tool",

                        "tool_call_id": tc.id,

                        "content": json.dumps(
                            result,
                            ensure_ascii=False,
                            default=str
                        ),
                    }

                )

        # ----------------------------------------------------------------
        # Existe ação pendente?
        # ----------------------------------------------------------------

        if pending_found:

            return {

                "type":
                    "confirmation_required",

                "text":
                    pending_found.description,

                "pending_action":
                    pending_found.to_dict(),
            }

        # ----------------------------------------------------------------
        # Continua para o modelo interpretar o resultado
        # ----------------------------------------------------------------

        continue

    # -------------------------------------------------------------------
    # Loop excedido
    # -------------------------------------------------------------------

    return {

        "type": "error",

        "text": (
            "O N.A.S.H tentou usar "
            "ferramentas várias vezes sem "
            "conseguir concluir. "
            "Tente reformular o pedido."
        ),
    }


# ===========================================================================
# RESOLVER ACAO PENDENTE
# ===========================================================================

def resolve_pending_action(
    pending: PendingAction,
    confirmed: bool
) -> dict:

    # -------------------------------------------------------------------
    # Defesa contra execução duplicada
    # -------------------------------------------------------------------

    if pending.status != "pendente":

        return {

            "type": "error",

            "text": (
                f"Esta ação já foi "
                f"'{pending.status}' "
                "e não pode ser executada novamente."
            ),
        }

    # -------------------------------------------------------------------
    # Recupera argumentos
    # -------------------------------------------------------------------

    args = json.loads(
        pending.arguments
    )

    # -------------------------------------------------------------------
    # Cancelamento
    # -------------------------------------------------------------------

    if not confirmed:

        pending.status = "cancelada"

        pending.resolved_at = (
            datetime.utcnow()
        )

        db.session.commit()

        log_action(
            "pending_action_cancelled",

            detail=pending.tool_name,

            permission=pending.permission,
        )

        return {

            "type": "message",

            "text": (
                "Ação cancelada. "
                "Nada foi alterado."
            ),
        }

    # -------------------------------------------------------------------
    # Execucao confirmada
    # -------------------------------------------------------------------

    try:

        result = execute_write_tool(
            pending.tool_name,
            args
        )

    except (
        ValidationError,
        LookupError,
        ValueError
    ) as exc:

        pending.status = "cancelada"

        pending.resolved_at = (
            datetime.utcnow()
        )

        db.session.commit()

        log_action(

            "pending_action_failed",

            detail=(
                f"{pending.tool_name}: "
                f"{exc}"
            ),

            permission=pending.permission,

            success=False,
        )

        return {

            "type": "error",

            "text": str(exc),
        }

    except Exception as exc:

        logger.exception(
            "Erro ao executar ação confirmada %s",
            pending.tool_name
        )

        pending.status = "cancelada"

        pending.resolved_at = (
            datetime.utcnow()
        )

        db.session.commit()

        log_action(

            "pending_action_failed",

            detail=(
                f"{pending.tool_name}: "
                f"{exc}"
            ),

            permission=pending.permission,

            success=False,
        )

        return {

            "type": "error",

            "text": (
                "Não consegui concluir "
                f"a ação: {exc}"
            ),
        }

    # -------------------------------------------------------------------
    # Marca como confirmada
    # -------------------------------------------------------------------

    pending.status = "confirmada"

    pending.resolved_at = (
        datetime.utcnow()
    )

    db.session.commit()

    log_action(

        "pending_action_confirmed",

        detail=pending.tool_name,

        permission=pending.permission,
    )

    # -------------------------------------------------------------------
    # Mensagens finais
    # -------------------------------------------------------------------

    confirmations = {

        "tool_create_task":
            "Tarefa criada.",

        "tool_update_task":
            "Tarefa atualizada.",

        "tool_complete_task":
            "Tarefa marcada como concluída.",

        "tool_delete_task":
            "Tarefa excluída.",

        "tool_restore_task":
            "Tarefa restaurada.",

        "tool_delete_all_tasks":
            "Todas as tarefas ativas foram excluídas.",

        "tool_create_project":
            "Projeto criado.",

        "tool_update_project":
            "Projeto atualizado.",

        "tool_delete_project":
            "Projeto excluído (tarefas preservadas).",

        "tool_save_memory":
            "Memória salva.",

        "tool_update_memory":
            "Memória atualizada.",

        "tool_delete_memory":
            "Memória excluída.",

        "tool_delete_all_memories":
            "Todas as memórias foram apagadas.",
    }

    if pending.tool_name == "tool_spotify_control":

        if isinstance(
            result,
            dict
        ):

            text = result.get(
                "message",
                "Comando enviado."
            )

        else:

            text = "Comando enviado."

    else:

        text = confirmations.get(
            pending.tool_name,
            "Ação concluída."
        )

    return {

        "type": "message",

        "text": text,

        "result": result,
    }