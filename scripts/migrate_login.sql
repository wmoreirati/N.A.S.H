-- ===========================================================================
-- N.A.S.H - Migracao do banco para o login com aprovacao pelo administrador.
--
-- Alternativa ao scripts/migrate_login.py, para rodar direto no SQL Editor do
-- Supabase. Faz exatamente a mesma coisa; use um OU outro, nao os dois.
--
-- O DDL abaixo foi GERADO a partir dos modelos (SQLAlchemy, dialeto Postgres),
-- nao escrito a mao: os tipos, o NOT NULL e os nomes de indice sao os mesmos
-- que o create_all produziria. Assim o banco nao diverge do que o codigo espera.
--
-- E idempotente do inicio ao fim (IF NOT EXISTS em tudo). Rodar duas vezes nao
-- quebra nada e nao duplica coluna.
--
-- ORDEM IMPORTA: rode isto ANTES de publicar o codigo novo. O codigo novo
-- consulta a tabela `users`; sem ela, a aplicacao responde 500 na primeira
-- requisicao.
--
-- A coluna user_id nasce NULA de proposito. As linhas que ja existem em
-- producao nao tem dono ainda; quem as adota e o primeiro cadastro feito com o
-- e-mail definido em ADMIN_EMAIL (ver adotar_orfaos em backend/security/auth.py).
-- Ate la elas ficam invisiveis para todos, que e o lado seguro do erro.
-- ===========================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Tabela de pessoas com acesso
-- ---------------------------------------------------------------------------
-- Sem DEFAULT em status/is_admin de proposito: o padrao vive no modelo Python,
-- e a aplicacao sempre preenche os dois. Assim um INSERT manual incompleto
-- falha alto, em vez de criar silenciosamente um usuario em estado indefinido.

CREATE TABLE IF NOT EXISTS users (
    id              SERIAL       NOT NULL,
    email           VARCHAR(255) NOT NULL,
    name            VARCHAR(120),
    password_hash   TEXT         NOT NULL,
    status          VARCHAR(20)  NOT NULL,
    is_admin        BOOLEAN      NOT NULL,
    created_at      TIMESTAMP WITHOUT TIME ZONE,
    approved_at     TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email);

-- ---------------------------------------------------------------------------
-- 2. Coluna de dono nas tabelas de dado pessoal
-- ---------------------------------------------------------------------------

ALTER TABLE tasks           ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id);
ALTER TABLE projects        ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id);
ALTER TABLE memories        ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id);
ALTER TABLE messages        ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id);
ALTER TABLE pending_actions ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id);

CREATE INDEX IF NOT EXISTS ix_tasks_user_id           ON tasks (user_id);
CREATE INDEX IF NOT EXISTS ix_projects_user_id        ON projects (user_id);
CREATE INDEX IF NOT EXISTS ix_memories_user_id        ON memories (user_id);
CREATE INDEX IF NOT EXISTS ix_messages_user_id        ON messages (user_id);
CREATE INDEX IF NOT EXISTS ix_pending_actions_user_id ON pending_actions (user_id);

-- ---------------------------------------------------------------------------
-- 3. Recuperacao de senha
-- ---------------------------------------------------------------------------
-- Guardam o HASH do token de recuperacao e a validade, nunca o token em si:
-- quem ler o banco nao consegue redefinir a senha de ninguem.

ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_token_hash TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_expira_em  TIMESTAMP WITHOUT TIME ZONE;

COMMIT;

-- ===========================================================================
-- 4. Conferencia (nao altera nada)
-- ===========================================================================
-- Esperado: as 5 linhas com tem_user_id = true, e orfaos > 0 nas tabelas que
-- ja tinham dados. Orfao aqui nao e erro: e registro esperando adocao pelo adm.

SELECT
    t.tabela,
    EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_name = t.tabela AND c.column_name = 'user_id'
    ) AS tem_user_id
FROM (VALUES ('tasks'), ('projects'), ('memories'), ('messages'), ('pending_actions'))
     AS t(tabela);

SELECT 'tasks'           AS tabela, count(*) AS orfaos FROM tasks           WHERE user_id IS NULL
UNION ALL SELECT 'projects',        count(*) FROM projects        WHERE user_id IS NULL
UNION ALL SELECT 'memories',        count(*) FROM memories        WHERE user_id IS NULL
UNION ALL SELECT 'messages',        count(*) FROM messages        WHERE user_id IS NULL
UNION ALL SELECT 'pending_actions', count(*) FROM pending_actions WHERE user_id IS NULL;
