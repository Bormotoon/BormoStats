-- Destructive: drops the whole history. Only for dev/stage or emergencies; take a backup first.
DROP TABLE IF EXISTS hist_changes;
DROP TABLE IF EXISTS hist_refs;
DROP TABLE IF EXISTS hist_commits;
DROP TABLE IF EXISTS hist_objects;
