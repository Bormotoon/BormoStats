CREATE DATABASE IF NOT EXISTS mp_analytics;

-- Keep initdb minimal; application users are provisioned explicitly during bootstrap.
SET allow_experimental_object_type = 1;
