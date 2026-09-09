# Migração da hospedagem para a conta da Piethro

Hoje o N.A.S.H roda na conta Vercel do Willians. Este documento é o roteiro
para passar a hospedagem para a conta da **Piethro**, que é a dona do projeto.

O código já é dela desde o primeiro commit (`piethropereira/N.A.S.H`), e o
banco também: o projeto Supabase `quzzrgpywawrttohvpsl` está sob a conta dela.
**O que muda aqui é só onde o site roda.**

---

## Antes de começar: entenda a limitação que causou tudo isso

O plano **Vercel Hobby não permite colaboração**. Um deploy disparado por um
commit cujo autor não é o dono da conta é recusado. Como os commits são do
Willians, o projeto na conta da Piethro publicou uma vez (o import, feito por
ela) e recusou todos os envios seguintes — foi por isso que a hospedagem
acabou morando na conta de quem constrói.

Depois da migração, isso continua valendo, e é **a decisão mais importante
deste documento**:

| Caminho | O que significa no dia a dia |
|---|---|
| **Piethro clica em Redeploy** | Toda correção do Willians exige que ela entre na Vercel e clique. Sem custo, mas ela vira o gargalo de qualquer conserto. |
| **Piethro assina o Pro** (~US$ 20/mês) | O Willians volta a publicar direto. Custa dinheiro. |
| **A Piethro passa a commitar** | Sem custo e sem gargalo, mas exige que ela mexa no código. |

Decida isto **antes** de apagar o projeto da conta do Willians. Sem definir,
a manutenção trava — foi exatamente o que travou antes.

---

## O que NÃO precisa migrar

- **O banco.** O Supabase já está na conta dela. Não toque nele.
- **As conexões do Composio.** Continuam valendo; são da conta Composio, não
  da Vercel.
- **O domínio.** `n-a-s-h-three.vercel.app` pertence ao projeto atual e será
  perdido ao apagá-lo. O projeto novo ganha outro endereço. Nada no código
  depende do endereço — os links de e-mail usam o domínio de quem acessa.

---

## Roteiro

### 1. Confirmar que o código está no repositório dela

O repositório oficial é `piethropereira/N.A.S.H`, branch `main`. Confira que o
último commit é o mesmo que está no ar hoje:

```bash
curl -s https://n-a-s-h-three.vercel.app/api/version
```

O campo `commit` tem de bater com o topo do `main` dela.

### 2. Ela importa o projeto na Vercel

Na Vercel **da Piethro**: *Add New → Project → Import Git Repository →
`piethropereira/N.A.S.H`*.

**Não mexa no preset.** A Vercel detecta Flask sozinha. Escolher "Other" faz
ela servir só arquivos estáticos e ignorar o Python — o sintoma é
`/static/style.css` responder 200 enquanto `/` e `/api/*` dão 404.

### 3. Cadastrar as variáveis de ambiente

Copie do projeto atual (Settings → Environment Variables) ou do `.env` local.
**Estas são as que importam:**

| Variável | Obrigatória | O que acontece sem ela |
|---|---|---|
| `DATABASE_URL` | sim | O app não sobe. Use a string do **Transaction pooler** (porta 6543). |
| `FLASK_SECRET_KEY` | sim | A sessão é assinada com chave nova a cada partida: todo mundo é deslogado o tempo todo. |
| `ADMIN_EMAIL` | sim | Ninguém vira administrador e ninguém aprova ninguém. Porta trancada com todos do lado de fora. |
| `AI_PROVIDER` | sim | Vale `groq` (o que está em uso). |
| `GROQ_API_KEY` | sim | O chat responde "sem credencial". |
| `GROQ_MODEL` | não | Padrão: `openai/gpt-oss-120b`. |
| `COMPOSIO_API_KEY` | não | Sem Gmail/Agenda/Drive, sem e-mail de recuperação, sem pesquisa em artigos. |
| `COMPOSIO_USER_ID` | não | Idem. |
| `MAX_HISTORY_MESSAGES` | não | Padrão: 30. |

Não cadastre `FLASK_DEBUG` (ou deixe `0`), nem `DB_AUTO_CREATE`, nem as
variáveis dos provedores que não estão em uso (`OPENAI_*`, `OPENROUTER_*`,
`GEMINI_*`, `OLLAMA_*`).

**Cuidado com variável cadastrada em branco:** vazia não é o mesmo que
ausente. `MAX_HISTORY_MESSAGES=` (vazia) já derrubou o app inteiro na subida
antes de existir tratamento. Ou preencha, ou não cadastre.

### 4. Região

O banco fica em `us-west-2`. O `vercel.json` já fixa a função em `pdx1`
(Oregon), que é colado nele. Não precisa fazer nada — só não remova esse
arquivo.

### 5. Deploy e conferência

Ela dispara o deploy. Depois, confira **de fora**, sem precisar entrar:

```bash
curl -s https://<novo-endereco>.vercel.app/api/version
```

Tem de responder o commit certo e `"ambiente":"production"`. Se responder um
commit antigo, a Vercel reconstruiu o que já tinha — o código novo não chegou
ao repositório. *"Deploy concluído" no painel não significa código novo.*

Confira também que a porta está fechada:

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://<novo-endereco>.vercel.app/
```

Esperado: **302** (redireciona para `/login`).

### 6. Só então apagar o projeto antigo

Na conta do Willians: Settings → Delete Project. Isso libera o endereço
`n-a-s-h-three.vercel.app` e evita duas instalações escrevendo no mesmo banco.

---

## Armadilhas que já custaram tempo neste projeto

- **`vercel.json` só pode ter `regions`.** Um bloco `functions` faz a Vercel
  procurar funções dentro de `api/`, que este projeto não tem, e o build morre
  em 1 segundo.
- **`DEPLOYMENT_NOT_FOUND` não quer dizer "não fez deploy"** — quer dizer
  "fez e morreu no build". Olhe a aba Deployments antes de suspeitar do envio.
- **Migração de banco vem ANTES do deploy.** O código consulta colunas que o
  banco precisa já ter. Publicar primeiro derruba o app inteiro — inclusive o
  login, porque toda consulta a `users` inclui todas as colunas do modelo.
  Aqui o banco já está migrado; isto vale para as próximas mudanças.
- **Confira em qual projeto Supabase você está** antes de rodar qualquer SQL.
  Rodar no banco errado é fácil e silencioso. Um `SELECT count(*) FROM users;`
  responde na hora se é o banco certo.

---

## Depois da migração

O `.env` local do Willians continua apontando para o mesmo banco de produção.
Isso é útil para manutenção e é uma faca de dois gumes: script rodado sem
atenção escreve em produção. Vale trocar para um banco de desenvolvimento
próprio quando a manutenção diminuir.
