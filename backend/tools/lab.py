"""
N.A.S.H - Laboratório: registros de experimento e análise.

Estrutura de relatório: hipótese, procedimento, resultados e observações.
Tudo escopado pelo dono, como o resto -- registro de laboratório é trabalho
de escola de alguém, não conteúdo compartilhado.
"""
from backend.models import LabEntry, db
from backend.security.auth import escopar, marcar_dono
from backend.security.validation import require_text, validate_id

AREAS = ("geral", "quimica", "fisica", "biologia", "matematica", "tecnologia")
STATUS = ("aberto", "concluido")

# Campos de texto livre. Ficam juntos porque criação e edição tratam os
# quatro exatamente igual -- e esquecer um deles numa das duas seria o tipo
# de erro que passa despercebido por semanas.
CAMPOS_TEXTO = ("hypothesis", "procedure", "results", "observations")


def _validar_area(area: str | None) -> str:
    area = (area or "geral").strip().lower()
    return area if area in AREAS else "geral"


def _validar_status(status: str | None) -> str:
    status = (status or "aberto").strip().lower()
    return status if status in STATUS else "aberto"


def list_entries(status: str | None = None, area: str | None = None):
    query = escopar(LabEntry.query, LabEntry)
    if status:
        query = query.filter_by(status=_validar_status(status))
    if area:
        query = query.filter_by(area=_validar_area(area))
    entradas = query.order_by(LabEntry.updated_at.desc()).all()
    return [e.to_dict() for e in entradas]


def get_entry_or_raise(entry_id: int) -> LabEntry:
    # Mesmo escopo do resto: registro de outra pessoa responde "não
    # encontrado", nunca "acesso negado" -- a segunda resposta confirmaria
    # que ele existe.
    entrada = escopar(LabEntry.query, LabEntry).filter(
        LabEntry.id == validate_id(entry_id, "entry_id")
    ).first()
    if not entrada:
        raise LookupError(f"Registro de laboratório {entry_id} não encontrado.")
    return entrada


def get_entry(entry_id: int):
    return get_entry_or_raise(entry_id).to_dict()


def create_entry(title: str, area: str = "geral", **campos):
    entrada = LabEntry(
        title=require_text(title, "title", max_length=255),
        area=_validar_area(area),
        status="aberto",
        **{c: (campos.get(c) or "").strip() for c in CAMPOS_TEXTO},
    )
    marcar_dono(entrada)
    db.session.add(entrada)
    db.session.commit()
    return entrada.to_dict()


def update_entry(entry_id: int, **campos):
    entrada = get_entry_or_raise(entry_id)

    if campos.get("title") is not None:
        entrada.title = require_text(campos["title"], "title", max_length=255)
    if campos.get("area") is not None:
        entrada.area = _validar_area(campos["area"])
    if campos.get("status") is not None:
        entrada.status = _validar_status(campos["status"])
    for campo in CAMPOS_TEXTO:
        if campos.get(campo) is not None:
            setattr(entrada, campo, str(campos[campo]).strip())

    db.session.commit()
    return entrada.to_dict()


def delete_entry(entry_id: int):
    entrada = get_entry_or_raise(entry_id)
    db.session.delete(entrada)
    db.session.commit()
    return {"deleted_id": entry_id}


def count_open_entries() -> int:
    return escopar(LabEntry.query, LabEntry).filter_by(status="aberto").count()
