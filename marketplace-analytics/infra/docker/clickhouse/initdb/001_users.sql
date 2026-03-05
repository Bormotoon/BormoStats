CREATE DATABASE IF NOT EXISTS mp_analytics;

-- Note: users usually provisioned through users.xml; keep initdb minimal.
SET allow_experimental_object_type = 1;

-- Default admin user for local bootstrap / Metabase setup using .env.example.
CREATE USER IF NOT EXISTS admin IDENTIFIED WITH plaintext_password BY 'admin_password';
GRANT ALL ON mp_analytics.* TO admin;
