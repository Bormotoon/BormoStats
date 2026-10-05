-- Sign-in with e-mail and password. Credentials live apart from dim_user so that the
-- user service, which rewrites whole dim_user rows, can never drop a password hash.
CREATE TABLE IF NOT EXISTS dim_user_credential
(
  user_id String,
  password_hash String,
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY user_id;

-- Browser sessions: the token is bss_<session_id>_<secret>; only a scrypt hash of the
-- secret is stored, as for API keys.
CREATE TABLE IF NOT EXISTS sys_user_session
(
  session_id String,
  user_id String,
  token_hash String,
  created_at DateTime DEFAULT now(),
  expires_at DateTime,
  revoked_at Nullable(DateTime),
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY session_id;
