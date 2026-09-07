"""
N.A.S.H - Validação de entrada.

Regra central de segurança (seção 6/21 do briefing): o backend NUNCA confia
apenas no modelo de IA. Toda função que persiste dados — seja chamada pelo
agente de IA (após confirmação) ou diretamente pela API REST — passa por
estas validações antes de tocar o banco.
"""
import re

PRIORITIES = {"baixa", "normal", "alta"}
TASK_STATUSES = {"pendente", "concluida", "excluida"}
PROJECT_STATUSES = {"ativo", "concluido", "arquivado"}
MEMORY_CATEGORIES = {"preferencia", "projeto", "estudo", "tarefa", "contexto", "geral"}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class ValidationError(ValueError):
    """Erro de validação de entrada, sempre com mensagem amigável ao usuário."""
    pass


def require_text(value, field_name: str, max_length: int = 4000) -> str:
    if value is None or not str(value).strip():
        raise ValidationError(f"O campo '{field_name}' é obrigatório.")
    text = str(value).strip()
    if len(text) > max_length:
        raise ValidationError(f"O campo '{field_name}' excede o tamanho máximo de {max_length} caracteres.")
    return text


def validate_priority(value) -> str:
    if value is None:
        return "normal"
    value = str(value).strip().lower()
    if value not in PRIORITIES:
        raise ValidationError(f"Prioridade inválida: '{value}'. Use: {', '.join(sorted(PRIORITIES))}.")
    return value


def validate_task_status(value) -> str:
    value = str(value).strip().lower()
    if value not in TASK_STATUSES:
        raise ValidationError(f"Status de tarefa inválido: '{value}'. Use: {', '.join(sorted(TASK_STATUSES))}.")
    return value


def validate_project_status(value) -> str:
    value = str(value).strip().lower()
    if value not in PROJECT_STATUSES:
        raise ValidationError(f"Status de projeto inválido: '{value}'. Use: {', '.join(sorted(PROJECT_STATUSES))}.")
    return value


def validate_progress(value) -> int:
    try:
        progress = int(value)
    except (TypeError, ValueError):
        raise ValidationError("O progresso deve ser um número inteiro entre 0 e 100.")
    if progress < 0 or progress > 100:
        raise ValidationError("O progresso deve estar entre 0 e 100.")
    return progress


def validate_date(value) -> str | None:
    if value in (None, ""):
        return None
    value = str(value).strip()
    if not _DATE_RE.match(value):
        raise ValidationError(f"Data inválida: '{value}'. Use o formato YYYY-MM-DD.")
    return value


def validate_time(value) -> str | None:
    if value in (None, ""):
        return None
    value = str(value).strip()
    if not _TIME_RE.match(value):
        raise ValidationError(f"Horário inválido: '{value}'. Use o formato HH:MM (24h).")
    return value


def validate_id(value, field_name: str = "id") -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"'{field_name}' deve ser um número inteiro válido.")


def validate_memory_category(value) -> str:
    if value is None or not str(value).strip():
        return "geral"
    value = str(value).strip().lower()
    if value not in MEMORY_CATEGORIES:
        # Categoria fora da lista sugerida não é um erro fatal — apenas normaliza para 'geral'.
        return "geral"
    return value
