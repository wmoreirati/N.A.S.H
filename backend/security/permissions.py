"""
N.A.S.H - Sistema de permissões.

Toda ferramenta (tool) que a IA pode chamar está associada a uma categoria
de permissão. Ações destrutivas ou que alteram estado do usuário SEMPRE
exigem confirmação explícita antes de serem executadas.

Categorias:
    READ              -> leitura, não precisa de confirmação
    WRITE             -> cria/edita dados do usuário, precisa de confirmação
    DELETE            -> remove dados do usuário, precisa de confirmação
    CALENDAR          -> altera agenda, precisa de confirmação
    EXTERNAL_SERVICE  -> chama serviço externo (Spotify, Google...), precisa
                         de confirmação E de uma conexão real estabelecida
    EMAIL, MESSAGES, SPOTIFY, FILES, SYSTEM -> reservadas para uso futuro,
                         seguem a mesma regra de EXTERNAL_SERVICE
"""

READ = "READ"
WRITE = "WRITE"
DELETE = "DELETE"
EXTERNAL_SERVICE = "EXTERNAL_SERVICE"
CALENDAR = "CALENDAR"
EMAIL = "EMAIL"
MESSAGES = "MESSAGES"
SPOTIFY = "SPOTIFY"
FILES = "FILES"
SYSTEM = "SYSTEM"

# Categorias que NUNCA exigem confirmação (apenas leitura, sem efeitos colaterais)
NO_CONFIRMATION_REQUIRED = {READ}

# Mapa: nome da ferramenta -> categoria de permissão
TOOL_PERMISSIONS = {
    # Tarefas
    "tool_create_task": WRITE,
    "tool_update_task": WRITE,
    "tool_complete_task": WRITE,
    "tool_delete_task": DELETE,
    "tool_restore_task": WRITE,
    "tool_delete_all_tasks": DELETE,
    "tool_list_tasks": READ,

    # Projetos
    "tool_create_project": WRITE,
    "tool_update_project": WRITE,
    "tool_delete_project": DELETE,
    "tool_list_projects": READ,

    # Memória
    "tool_save_memory": WRITE,
    "tool_update_memory": WRITE,
    "tool_delete_memory": DELETE,
    "tool_delete_all_memories": DELETE,
    "tool_list_memories": READ,
    
    # Data e hora
    "tool_get_datetime": READ,

    # Agenda / calendário (local, ainda não é Google Calendar real)
    "tool_get_calendar": READ,
    # Agenda / calendário (local, ainda não é Google Calendar real)
    "tool_get_calendar": READ,

    # Web
    "tool_search_papers": READ,  # não altera estado, mas depende de serviço externo real

    # Spotify (arquitetura preparada, sem execução real sem conexão)
    "tool_spotify_control": SPOTIFY,
    "tool_spotify_search": READ,
}


def get_permission(tool_name: str) -> str:
    """Retorna a categoria de permissão de uma ferramenta. Padrão: WRITE (mais restritivo)."""
    return TOOL_PERMISSIONS.get(tool_name, WRITE)


def requires_confirmation(tool_name: str) -> bool:
    """Toda ferramenta exige confirmação, exceto as puramente de leitura (READ)."""
    permission = get_permission(tool_name)
    return permission not in NO_CONFIRMATION_REQUIRED


def is_external_service(tool_name: str) -> bool:
    permission = get_permission(tool_name)
    return permission in {EXTERNAL_SERVICE, EMAIL, MESSAGES, SPOTIFY, FILES, SYSTEM}
