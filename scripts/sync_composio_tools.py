"""
N.A.S.H - Baixa os esquemas das ações do Composio para um arquivo local.

Uso:
    python scripts/sync_composio_tools.py

Por que existe: consultar a API do Composio na subida do servidor custaria
uma ida à rede a cada partida a frio de função serverless. O catálogo é
baixado aqui, uma vez, e versionado — assim a lista de ações fica revisável
no git, e o servidor só lê arquivo.

Rode de novo quando quiser acrescentar ações em `composio_tools.ACOES`.
"""
import json
import os
import sys
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from backend.tools.composio_tools import ACOES, BASE_URL, CATALOGO_PATH  # noqa: E402


# Máquinas atrás de proxy que intercepta TLS (o caso desta) não conseguem
# validar a cadeia de certificados e o download falha. A flag é opt-in e vale
# só para esta ferramenta local — o código que roda em produção
# (`composio_tools.executar`) sempre valida o certificado.
VERIFICAR_TLS = "--sem-verificar-tls" not in sys.argv


def toolkit_de(slug: str) -> str:
    return slug.split("_", 1)[0].lower()


def enxuga(schema: dict, limite_desc: int = 90) -> dict:
    """
    Reduz o esquema de parâmetros ao essencial.

    Medido: os 18 esquemas crus do Composio somam ~11 mil tokens, contra 1.789
    das 21 ferramentas nativas. O peso está nas descrições longas de cada
    propriedade e em campos que o modelo não usa para decidir (examples,
    title, default aninhado). Cortar isso preserva a informação que importa —
    nome, tipo e obrigatoriedade — e devolve o custo para a ordem de grandeza
    do resto do sistema.
    """
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}

    props = {}
    for nome, campo in (schema.get("properties") or {}).items():
        if not isinstance(campo, dict):
            continue
        limpo = {"type": campo.get("type", "string")}
        desc = (campo.get("description") or "").strip()
        if desc:
            limpo["description"] = desc[:limite_desc]
        if campo.get("enum"):
            limpo["enum"] = campo["enum"][:12]
        props[nome] = limpo

    saida = {"type": "object", "properties": props}
    if schema.get("required"):
        saida["required"] = schema["required"]
    return saida


def main() -> int:
    chave = (os.environ.get("COMPOSIO_API_KEY") or "").strip()
    if not chave:
        print("COMPOSIO_API_KEY não definida no .env.")
        return 1

    if not VERIFICAR_TLS:
        import urllib3
        urllib3.disable_warnings()
        print("  AVISO: verificação de TLS desligada (proxy local). Use só nesta máquina.")

    toolkits = sorted({toolkit_de(s) for s in ACOES})
    print(f"\n  Ações no catálogo: {len(ACOES)}  |  toolkits: {', '.join(toolkits)}\n")

    encontrados, faltando = {}, []
    for tk in toolkits:
        r = requests.get(
            f"{BASE_URL}/tools",
            headers={"x-api-key": chave},
            params={"toolkit_slug": tk, "limit": 200},
            timeout=60,
            verify=VERIFICAR_TLS,
        )
        if r.status_code != 200:
            print(f"    {tk}: HTTP {r.status_code} — pulado")
            continue
        for t in r.json().get("items", []):
            if t.get("slug") in ACOES:
                encontrados[t["slug"]] = t

    ferramentas = []
    for slug in ACOES:
        t = encontrados.get(slug)
        if not t:
            faltando.append(slug)
            continue
        ferramentas.append({
            "type": "function",
            "function": {
                "name": slug,
                # A descrição do Composio às vezes é longa; cortar mantém o
                # esquema barato, e ele viaja em toda mensagem.
                "description": (t.get("description") or t.get("name") or slug)[:140],
                "parameters": enxuga(t.get("input_parameters") or {}),
            },
        })

    CATALOGO_PATH.parent.mkdir(parents=True, exist_ok=True)
    CATALOGO_PATH.write_text(
        json.dumps({"tools": ferramentas}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    por_toolkit = {}
    for f in ferramentas:
        tk = toolkit_de(f["function"]["name"])
        por_toolkit.setdefault(tk, 0)
        por_toolkit[tk] += len(json.dumps(f, ensure_ascii=False)) // 4
    print()
    print("  Custo por servico (tokens, so quando a mensagem pedir aquele servico):")
    for tk, custo in sorted(por_toolkit.items(), key=lambda x: -x[1]):
        print(f"    {tk:<16} ~{custo}")

    tamanho = len(json.dumps(ferramentas, ensure_ascii=False))
    print(f"  Gravadas {len(ferramentas)} ações em {CATALOGO_PATH.name}")
    print(f"  Custo do esquema: ~{tamanho // 4} tokens por mensagem que ofereça estas ações")
    if faltando:
        print(f"\n  NÃO ENCONTRADAS ({len(faltando)}) — confira o nome em https://app.composio.dev:")
        for s in faltando:
            print(f"    {s}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
