#!/bin/sh
# Render the Redis ACL from the environment so the password never appears in the
# process arguments (visible via `ps`/`docker inspect`). The default user is
# disabled; the application user may not run administrative commands.
set -eu
: "${REDIS_PASSWORD:?REDIS_PASSWORD must be set}"
REDIS_USERNAME="${REDIS_USERNAME:-bormostats}"
# The ACL stores only the SHA-256 of the password ("#<hex>"), which also keeps
# passwords with spaces or special characters from breaking the ACL syntax.
PASSWORD_SHA256="$(printf '%s' "$REDIS_PASSWORD" | sha256sum | cut -d' ' -f1)"
umask 077
cat > /tmp/users.acl <<ACL
user default off
user ${REDIS_USERNAME} on #${PASSWORD_SHA256} ~* &* +@all -flushall -flushdb -config -debug -shutdown -module -acl -replicaof -slaveof -failover
ACL
exec redis-server --appendonly yes --aclfile /tmp/users.acl "$@"
