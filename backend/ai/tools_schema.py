"""
N.A.S.H - Esquema de ferramentas (tools) expostas ao modelo de IA.

Formato compatível com "function calling" da API da OpenAI.
O modelo decide sozinho quando (e se) chamar uma ferramenta.
"""

TOOLS = [
    # ---------- TAREFAS ----------
    {
        "type": "function",
        "function": {
            "name": "tool_list_tasks",
            "description": "Lista as tarefas do usuário. Use para responder perguntas como 'quais tarefas tenho hoje'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["pendente", "concluida", "excluida"], "description": "Filtrar por status (opcional)."}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tool_create_task",
            "description": "Propõe a criação de uma nova tarefa/lembrete. Requer confirmação do usuário antes de ser efetivada.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Título curto da tarefa."},
                    "description": {"type": "string", "description": "Detalhes adicionais (opcional)."},
                    "date": {"type": "string", "description": "Data no formato YYYY-MM-DD (opcional)."},
                    "time": {"type": "string", "description": "Horário no formato HH:MM (opcional)."},
                    "priority": {"type": "string", "enum": ["baixa", "normal", "alta"]},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tool_update_task",
            "description": "Propõe editar campos de uma tarefa existente (título, descrição, data, horário ou prioridade). Requer confirmação.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "date": {"type": "string", "description": "YYYY-MM-DD"},
                    "time": {"type": "string", "description": "HH:MM"},
                    "priority": {"type": "string", "enum": ["baixa", "normal", "alta"]},
                },
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tool_complete_task",
            "description": "Propõe marcar uma tarefa existente como concluída. Requer confirmação.",
            "parameters": {
                "type": "object",
                "properties": {"task_id": {"type": "integer"}},
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tool_delete_task",
            "description": "Propõe excluir uma tarefa (exclusão lógica, pode ser restaurada). Requer confirmação.",
            "parameters": {
                "type": "object",
                "properties": {"task_id": {"type": "integer"}},
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tool_restore_task",
            "description": "Propõe restaurar uma tarefa excluída. Requer confirmação.",
            "parameters": {
                "type": "object",
                "properties": {"task_id": {"type": "integer"}},
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tool_delete_all_tasks",
            "description": "Propõe excluir TODAS as tarefas ativas do usuário. Ação destrutiva em massa. Requer confirmação explícita.",
            "parameters": {"type": "object", "properties": {}},
        },
    },

    # ---------- PROJETOS ----------
    {
        "type": "function",
        "function": {
            "name": "tool_list_projects",
            "description": "Lista os projetos do usuário.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tool_create_project",
            "description": "Propõe a criação de um novo projeto. Requer confirmação.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "objectives": {"type": "string"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tool_update_project",
            "description": "Propõe editar campos de um projeto existente (nome, descrição, objetivos, notas, progresso ou status). Requer confirmação.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "objectives": {"type": "string"},
                    "notes": {"type": "string"},
                    "progress": {"type": "integer", "description": "0 a 100"},
                    "status": {"type": "string", "enum": ["ativo", "concluido", "arquivado"]},
                },
                "required": ["project_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tool_delete_project",
            "description": "Propõe excluir um projeto permanentemente (as tarefas ligadas a ele ficam sem projeto). Requer confirmação.",
            "parameters": {
                "type": "object",
                "properties": {"project_id": {"type": "integer"}},
                "required": ["project_id"],
            },
        },
    },

    # ---------- MEMÓRIA ----------
    {
        "type": "function",
        "function": {
            "name": "tool_list_memories",
            "description": "Lista as memórias salvas sobre o usuário.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tool_save_memory",
            "description": "Propõe salvar uma nova informação permanente sobre o usuário (preferência, contexto, dado pessoal relevante). Requer confirmação explícita ANTES de salvar — nunca salve memórias silenciosamente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "O que deve ser lembrado, de forma clara e objetiva."},
                    "category": {"type": "string", "enum": ["preferencia", "projeto", "estudo", "tarefa", "contexto", "geral"]},
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tool_update_memory",
            "description": "Propõe editar o conteúdo ou a categoria de uma memória existente. Requer confirmação.",
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_id": {"type": "integer"},
                    "content": {"type": "string"},
                    "category": {"type": "string", "enum": ["preferencia", "projeto", "estudo", "tarefa", "contexto", "geral"]},
                },
                "required": ["memory_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tool_delete_memory",
            "description": "Propõe excluir uma memória específica. Requer confirmação.",
            "parameters": {
                "type": "object",
                "properties": {"memory_id": {"type": "integer"}},
                "required": ["memory_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tool_delete_all_memories",
            "description": "Propõe apagar TODAS as memórias salvas. Ação destrutiva e irreversível. Requer confirmação explícita.",
            "parameters": {"type": "object", "properties": {}},
        },
    },

    # ---------- DATA E HORA ----------
    {
        "type": "function",
        "function": {
            "name": "tool_get_datetime",
            "description": "Obtém a data e hora local atual do computador. Use para perguntas como 'que horas são', 'qual a data de hoje', 'que dia é hoje' ou 'qual o horário atual'.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },

    # ---------- CALENDÁRIO ----------
    {
        "type": "function",
        "function": {
            "name": "tool_get_calendar",
            "description": "Consulta a agenda local (tarefas com data/hora), opcionalmente de um dia específico.",
            "parameters": {
                "type": "object",
                "properties": {"date": {"type": "string", "description": "YYYY-MM-DD (opcional)."}},
            },
        },
    },

    # ---------- WEB ----------
    {
        "type": "function",
        "function": {
            "name": "tool_search_papers",
            "description": "Pesquisa em ARTIGOS CIENTÍFICOS revisados por pares (não é busca na internet aberta). Use para embasar explicações de química, física, biologia e afins com fonte citável. Não serve para notícia, preço, horário ou qualquer informação do dia a dia.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "O tema a pesquisar, de preferência em inglês (a base é majoritariamente em inglês)."},
                    "ano_minimo": {"type": "integer", "description": "Opcional: só artigos deste ano em diante."},
                },
                "required": ["query"],
            },
        },
    },

    # ---------- SPOTIFY ----------
    {
        "type": "function",
        "function": {
            "name": "tool_spotify_search",
            "description": "Busca músicas, artistas ou playlists no Spotify. Só retorna resultados reais se o Spotify estiver conectado.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tool_spotify_control",
            "description": "Controla a reprodução no Spotify (tocar, pausar, avançar). Só funciona se o Spotify estiver realmente conectado.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["play", "pause", "next", "previous"]},
                },
                "required": ["action"],
            },
        },
    },
]


def get_tools_schema() -> list[dict]:
    return TOOLS
