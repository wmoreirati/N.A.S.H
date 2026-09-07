"""
N.A.S.H - Memória persistente.

Regras (seção 9 do briefing):
- NADA é salvo automaticamente na conversa; salvar sempre passa pelo
  fluxo de confirmação (PendingAction), tratado em backend/ai/agent.py.
- Este módulo apenas executa as operações de CRUD já autorizadas.
- O contexto enviado ao modelo é limitado (quantidade de memórias E
  tamanho total em caracteres) — nunca envia memória ilimitada.
"""
from backend.models import db, Memory
from backend.security.validation import require_text, validate_memory_category

DEFAULT_CONTEXT_LIMIT = 30
DEFAULT_CONTEXT_MAX_CHARS = 3000


def list_memories(category: str | None = None):
    query = Memory.query
    if category:
        query = query.filter_by(category=category)
    memories = query.order_by(Memory.updated_at.desc()).all()
    return [m.to_dict() for m in memories]


def save_memory(content: str, category: str = "geral"):
    content = require_text(content, "content")
    category = validate_memory_category(category)
    memory = Memory(content=content, category=category)
    db.session.add(memory)
    db.session.commit()
    return memory.to_dict()


def update_memory(memory_id: int, content: str | None = None, category: str | None = None):
    memory = Memory.query.get(memory_id)
    if not memory:
        raise LookupError(f"Memória {memory_id} não encontrada.")
    if content is not None:
        memory.content = require_text(content, "content")
    if category is not None:
        memory.category = validate_memory_category(category)
    db.session.commit()
    return memory.to_dict()


def delete_memory(memory_id: int):
    memory = Memory.query.get(memory_id)
    if not memory:
        raise LookupError(f"Memória {memory_id} não encontrada.")
    db.session.delete(memory)
    db.session.commit()
    return {"deleted_id": memory_id}


def delete_all_memories():
    count = Memory.query.delete()
    db.session.commit()
    return {"deleted_count": count}


def memory_context_snapshot(limit: int = DEFAULT_CONTEXT_LIMIT, max_chars: int = DEFAULT_CONTEXT_MAX_CHARS) -> str:
    """
    Gera um resumo textual das memórias mais recentes, para ser injetado
    no system prompt do modelo de IA. Limitado por quantidade E por
    tamanho total em caracteres, para nunca inflar o prompt indefinidamente.
    """
    memories = Memory.query.order_by(Memory.updated_at.desc()).limit(limit).all()
    if not memories:
        return "Nenhuma memória salva ainda."

    lines = []
    total = 0
    for m in memories:
        line = f"- [{m.category}] {m.content}"
        if total + len(line) > max_chars:
            lines.append(f"(+{len(memories) - len(lines)} memória(s) omitida(s) por limite de contexto)")
            break
        lines.append(line)
        total += len(line)
    return "\n".join(lines)
