-- ===========================================================================
-- N.A.S.H - Tabela do Laboratorio (registros de experimento e analise).
--
-- Alternativa ao `python scripts/init_db.py`, para rodar no SQL Editor do
-- Supabase. Use um OU outro, nao os dois -- os dois sao idempotentes, mas nao
-- ha motivo para rodar duas vezes.
--
-- O DDL foi GERADO a partir do modelo (SQLAlchemy, dialeto Postgres), nao
-- escrito a mao: tipos, NOT NULL e nome de indice batem com o que o create_all
-- produziria, entao o banco nao diverge do que o codigo espera.
--
-- ORDEM: rode ANTES de publicar o codigo novo. A tela Laboratorio consulta
-- esta tabela; sem ela, a aba responde erro.
--
-- Depende de `users` ja existir (a chave estrangeira aponta para la). Se este
-- for um banco novo, rode migrate_login.sql primeiro.
-- ===========================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS lab_entries (
    id            SERIAL       NOT NULL,
    user_id       INTEGER,
    title         VARCHAR(255) NOT NULL,
    area          VARCHAR(40),
    hypothesis    TEXT,
    procedure     TEXT,
    results       TEXT,
    observations  TEXT,
    status        VARCHAR(20),
    created_at    TIMESTAMP WITHOUT TIME ZONE,
    updated_at    TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id),
    FOREIGN KEY (user_id) REFERENCES users (id)
);

CREATE INDEX IF NOT EXISTS ix_lab_entries_user_id ON lab_entries (user_id);

COMMIT;

-- ---------------------------------------------------------------------------
-- Conferencia (nao altera nada)
-- ---------------------------------------------------------------------------

SELECT EXISTS (
    SELECT 1 FROM information_schema.tables WHERE table_name = 'lab_entries'
) AS tabela_criada;
