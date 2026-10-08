CREATE TABLE IF NOT EXISTS games (
    game_id TEXT PRIMARY KEY,
    group_id BIGINT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    version INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    state JSONB NOT NULL,
    rng JSONB NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_game_per_group ON games(group_id) WHERE active;
CREATE TABLE IF NOT EXISTS private_chats (
    user_id BIGINT PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    available BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS update_receipts (
    update_id TEXT PRIMARY KEY,
    game_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS callback_intentions (
    token TEXT PRIMARY KEY,
    game_id TEXT NOT NULL REFERENCES games(game_id),
    expected_version INTEGER NOT NULL,
    actor_id BIGINT,
    chat_id BIGINT NOT NULL,
    action TEXT NOT NULL,
    args JSONB NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS game_events (
    id BIGSERIAL PRIMARY KEY,
    game_id TEXT NOT NULL REFERENCES games(game_id),
    update_id TEXT NOT NULL,
    audience TEXT NOT NULL,
    name TEXT NOT NULL,
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS outbox (
    id BIGSERIAL PRIMARY KEY,
    game_id TEXT REFERENCES games(game_id),
    update_id TEXT,
    ordinal INTEGER,
    method TEXT NOT NULL,
    payload JSONB NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMPTZ,
    result JSONB,
    error_code TEXT,
    UNIQUE(update_id, ordinal)
);
CREATE TABLE IF NOT EXISTS game_timers (
    timer_id TEXT PRIMARY KEY,
    game_id TEXT NOT NULL REFERENCES games(game_id),
    expected_version INTEGER NOT NULL,
    kind TEXT NOT NULL,
    args JSONB NOT NULL,
    due_at TIMESTAMPTZ,
    remaining_seconds DOUBLE PRECISION,
    status TEXT NOT NULL DEFAULT 'pending'
);
CREATE TABLE IF NOT EXISTS service_state (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL
);
