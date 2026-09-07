# N.A.S.H

Assistente pessoal de IA local — parceiro de estudos e **centro de comando pessoal**.

N.A.S.H conversa naturalmente sobre qualquer assunto, com modo especialista em
exatas (matemática, física, química, biologia, tecnologia), gerencia tarefas,
projetos, calendário local e memória de longo prazo, e só executa ações que
alteram seus dados depois que você confirmar.

---

## 1. O que é o N.A.S.H

Um assistente pessoal que roda na sua máquina (Flask + SQLite), conversa com um
modelo de IA real — local via Ollama, ou pela API da OpenAI ou do Google Gemini,
à sua escolha — e nunca finge ter feito algo que não fez: nem salvar uma memória,
nem conectar um serviço externo.

## 2. Recursos

- Chat com IA real, com histórico persistente e limite de contexto configurável
- Modo especialista em exatas, com LaTeX renderizado (MathJax)
- Tarefas (criar, editar, concluir, excluir, restaurar)
- Projetos (com tarefas vinculadas — excluir um projeto nunca apaga as tarefas)
- Calendário local (tarefas com data/hora)
- Memória persistente, só salva com confirmação explícita
- Sistema de permissões: READ nunca precisa de confirmação; WRITE, DELETE e
  serviços externos sempre precisam
- `PendingAction` com expiração automática — nada fica pendente para sempre,
  e nada é executado duas vezes
- Log de auditoria de toda ação importante (sem nunca gravar segredos)
- Reconhecimento e síntese de voz (Web Speech API do navegador)
- Interface HUD própria, responsiva, dark mode

## 3. Estrutura

```
nash/
├── app.py                      # Fábrica da aplicação Flask + todas as rotas
├── requirements.txt
├── .env.example
├── README.md
├── tests/
│   └── test_backend.py          # Testes automatizados (pytest/unittest)
│
├── backend/
│   ├── models.py                 # Tabelas SQLAlchemy (SQLite)
│   ├── db.py                     # Inicialização do banco (instance/nash.db)
│   │
│   ├── ai/
│   │   ├── provider.py           # Interface abstrata AIProvider
│   │   ├── factory.py            # Escolhe o provedor conforme AI_PROVIDER
│   │   ├── ollama_provider.py    # Modelo local (padrão)
│   │   ├── openai_provider.py    # API da OpenAI
│   │   ├── gemini_provider.py    # API do Google Gemini
│   │   ├── tools_schema.py       # Definição das ferramentas (function calling)
│   │   └── agent.py              # Orquestrador: prompt + memória + histórico + tools
│   │
│   ├── memory/
│   │   └── memory.py             # CRUD de memória (com limite de contexto)
│   │
│   ├── tools/
│   │   ├── tasks.py              # CRUD de tarefas
│   │   ├── projects.py           # CRUD de projetos (preserva tarefas ao excluir)
│   │   ├── calendar.py           # Agenda local + status Google Calendar
│   │   └── connections.py        # Status real de integrações externas
│   │
│   └── security/
│       ├── permissions.py        # Categorias de permissão + regra de confirmação
│       ├── validation.py         # Validação de entrada compartilhada
│       └── audit.py              # Log de auditoria (nunca grava segredos)
│
├── templates/
│   └── index.html                # Interface (HUD/centro de comando)
│
└── static/
    ├── style.css                  # Identidade visual (dark mode, ciano/azul)
    └── app.js                      # Chat, tarefas, projetos, memória, calendário, voz
```

## 4. Requisitos

- **Python 3.10 ou superior** (o código usa a sintaxe `str | None`).
- Um provedor de IA, à escolha (ver `AI_PROVIDER` na seção 7):
  - **Ollama** rodando na máquina — gratuito, sem chave, mas o modelo padrão é
    pequeno e não serve para ensinar exatas; ou
  - uma **chave de API** da OpenAI ou do Google Gemini — paga por uso, e é o que
    faz o modo professor funcionar de verdade.

O app sobe sem nenhum deles: o chat avisa que a IA está offline em vez de quebrar.

## 5. Instalação

**Windows:**
```
python -m venv .venv
.venv\Scripts\activate
```

**macOS/Linux:**
```
python3 -m venv .venv
source .venv/bin/activate
```

## 6. requirements.txt

```
pip install -r requirements.txt
```

Inclui apenas o necessário: `Flask`, `Flask-SQLAlchemy`, `python-dotenv`,
`requests`, e as bibliotecas dos provedores opcionais `openai` e `google-genai`
(mais `pytest`, opcional, só para rodar os testes).

## 7. Configuração do `.env`

**Windows:** `copy .env.example .env`
**macOS/Linux:** `cp .env.example .env`

```
AI_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3:1.7b
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.6-flash
PORT=5000
FLASK_DEBUG=1
FLASK_SECRET_KEY=
MAX_HISTORY_MESSAGES=30
```

- `AI_PROVIDER`: qual modelo responde no chat — `ollama` (local, gratuito),
  `openai` ou `gemini`. Um valor desconhecido faz o servidor recusar iniciar,
  em vez de cair silenciosamente em outro provedor.
  ⚠️ O modelo local padrão é pequeno e **erra contas**. Para uso como professor
  de exatas, use `openai` ou `gemini`.
- Chave do provedor escolhido: sem ela, o chat funciona mas avisa que a IA
  está offline (`ollama` não precisa de chave).
- `FLASK_SECRET_KEY`: recomendado gerar uma fixa com
  `python -c "import secrets; print(secrets.token_hex(32))"`. Se deixar vazio,
  o servidor gera uma chave temporária a cada reinício (ok para uso local).
- `MAX_HISTORY_MESSAGES`: quantas mensagens recentes são enviadas ao modelo
  como contexto a cada turno (evita prompts gigantes).

⚠️ O `.env` nunca é lido pelo navegador — apenas pelo processo Python do servidor.

## 8. Execução

```
python app.py
```

Abra: **http://127.0.0.1:5000**

## 9. Banco de dados

SQLite local em `instance/nash.db`, criado automaticamente na primeira
execução (a pasta `instance/` também é criada sozinha, se não existir).
Para resetar tudo, feche o servidor e apague a pasta `instance/`.

## 10. API

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/health` | Status do sistema (IA, contadores, conexões) |
| POST | `/api/chat` | Envia mensagem ao N.A.S.H |
| GET | `/api/history` | Histórico recente de mensagens |
| GET | `/api/pending-actions` | Lista ações aguardando confirmação |
| POST | `/api/pending-actions/<id>/confirm` | Confirma e executa uma ação pendente |
| POST | `/api/pending-actions/<id>/cancel` | Cancela uma ação pendente |
| GET/POST | `/api/tasks` | Lista / cria tarefas |
| PUT/DELETE | `/api/tasks/<id>` | Edita / exclui (lógico) uma tarefa |
| POST | `/api/tasks/<id>/complete` | Marca tarefa como concluída |
| POST | `/api/tasks/<id>/restore` | Restaura tarefa excluída |
| GET/POST | `/api/projects` | Lista / cria projetos |
| PUT/DELETE | `/api/projects/<id>` | Edita / exclui um projeto (tarefas preservadas) |
| GET/POST | `/api/memories` | Lista / salva memórias |
| PUT/DELETE | `/api/memories/<id>` | Edita / exclui uma memória |
| POST | `/api/memories/clear_all` | Apaga todas as memórias |
| GET | `/api/calendar` | Agenda local + status do Google Calendar |
| GET | `/api/connections` | Status real de todas as integrações externas |

Toda resposta de erro segue o formato `{"ok": false, "error": "mensagem amigável"}`
— nenhuma rota vaza traceback para o cliente (fica só no log do servidor).

## 11. Ferramentas (function calling)

21 ferramentas, todas com esquema, permissão e implementação sincronizados:

**Tarefas:** `tool_list_tasks` (READ), `tool_create_task`, `tool_update_task`,
`tool_complete_task`, `tool_restore_task` (WRITE), `tool_delete_task`,
`tool_delete_all_tasks` (DELETE)

**Projetos:** `tool_list_projects` (READ), `tool_create_project`,
`tool_update_project` (WRITE), `tool_delete_project` (DELETE)

**Memória:** `tool_list_memories` (READ), `tool_save_memory`,
`tool_update_memory` (WRITE), `tool_delete_memory`, `tool_delete_all_memories` (DELETE)

**Calendário e data/hora:** `tool_get_calendar`, `tool_get_datetime` (READ)

**Web:** `tool_search_web` (READ — responde "busca web não configurada" sem integração real)

**Spotify:** `tool_spotify_search` (READ), `tool_spotify_control` (SPOTIFY —
exige confirmação E conexão real válida)

Ao subir o servidor, `backend/ai/agent.py` roda uma **auto-verificação**: se
alguma ferramenta existir no schema sem permissão ou dispatcher (ou
vice-versa), o servidor recusa iniciar com um erro claro em vez de deixar uma
"ferramenta fantasma" passar despercebida.

## 12. Sistema de confirmação

1. Você pede algo em linguagem natural.
2. O modelo decide chamar uma ferramenta.
3. `backend/security/permissions.py` classifica a ferramenta: `READ` executa
   direto; `WRITE`/`DELETE`/`SPOTIFY` exigem confirmação.
4. O backend cria um `PendingAction` e devolve uma descrição amigável
   ("Vou criar a tarefa... Confirmar?").
5. A interface mostra um cartão **Confirmar / Cancelar**.
6. Só ao clicar em **Confirmar** a ferramenta é executada de verdade.

Proteções extras:
- Uma `PendingAction` pendente há mais de 30 minutos expira sozinha (status
  `expirada`) e não pode mais ser confirmada.
- A mesma ação nunca é executada duas vezes — confirmar uma ação já resolvida
  retorna erro `409`.
- O backend nunca confia apenas no nome da ferramenta que o modelo tenta
  chamar: se não existir no schema conhecido, é rejeitada antes de qualquer
  execução.

## 13. Integrações externas

**Status atual: nenhuma integração externa está realmente conectada.** A
arquitetura está pronta (tabela `connections`, `backend/tools/connections.py`,
ferramentas `tool_spotify_*`), mas o fluxo OAuth completo depende de
credenciais de aplicativo (client ID / client secret) que só você pode gerar
nos painéis de desenvolvedor de cada serviço. A aba **Conexões** sempre mostra
o estado real — nunca finge que algo está ativo.

## 14. Troubleshooting

| Sintoma | Causa provável | Solução |
|---|---|---|
| `ModuleNotFoundError` ao rodar `python app.py` | venv não ativado / dependências não instaladas | Ative o `.venv` e rode `pip install -r requirements.txt` |
| Chat diz que o provedor está sem credencial | Chave do `AI_PROVIDER` escolhido está vazia | Preencha o `.env` e reinicie o servidor |
| Chat diz "chave rejeitada pela OpenAI" | Chave inválida/expirada/sem créditos | Gere uma nova chave e verifique o saldo |
| Página em branco / erro 500 | Banco corrompido | Apague `instance/` e reinicie (o banco é recriado do zero) |
| Ação de confirmação retorna 409 | A ação já foi confirmada/cancelada/expirou | Peça a ação de novo pelo chat |
| Microfone não funciona | Navegador sem suporte / permissão negada | Use Chrome/Edge e permita o microfone |
| Porta 5000 em uso | Outro processo na porta | Mude `PORT` no `.env` |

---

## 15. Testes

```
pip install pytest   # se ainda não instalado
pytest tests/ -v
```

Ou sem pytest:

```
python -m unittest discover -s tests -v
```

Os testes usam um banco SQLite temporário (nunca o banco real) e não fazem
nenhuma chamada de rede. Cobrem: ciclo de vida de tarefas, exclusão de
projeto preservando tarefas, memória, confirmação/cancelamento/expiração de
`PendingAction`, impossibilidade de executar a mesma ação duas vezes,
permissões READ vs WRITE, consistência schema/permissão/dispatcher, e
respostas de erro sem vazamento de traceback.

## 16. Testes manuais recomendados

1. Envie uma mensagem simples ("N.A.S.H, o que é a segunda lei de Newton?").
2. Peça para criar uma tarefa por texto e confirme no cartão do chat.
3. Na aba **Tarefas**, edite, conclua e exclua a tarefa criada.
4. Crie um projeto, vincule uma tarefa a ele, exclua o projeto e confirme que
   a tarefa continua existindo (só perde o vínculo).
5. Peça para o N.A.S.H salvar uma preferência e confirme; veja em **Memória**.
6. Veja a aba **Calendário** com uma tarefa que tenha data.
7. Zere a chave do provedor escolhido e reinicie: o chat deve avisar que a IA está offline
   sem quebrar a interface.
