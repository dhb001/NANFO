#!/bin/sh
# NANFO Redis (baked into deploy/Dockerfile.redis; never bind-mounted from a checkout).
# Generates a private config with ACL users (ADR-028 C24): `default` is disabled, the
# application authenticates as `nanfo` and the operator user `nanfo-admin` is used only
# by manage.py rotate/healthchecks. Only SHA-256 password hashes enter the config.
set -eu
umask 077
password_hash() {
  value=$(cat "$1")
  # Generated URL-safe secrets cannot inject Redis configuration or shell syntax.
  case "$value" in *[!a-zA-Z0-9_-]*|'') exit 1 ;; esac
  test "${#value}" -ge 32
  test "${#value}" -le 128
  printf '%s' "$value" | sha256sum | cut -d ' ' -f 1
}
app_hash=$(password_hash /run/secrets/redis_password)
admin_hash=$(password_hash /run/secrets/redis_admin_password)
test "$app_hash" != "$admin_hash"
cat > /run/redis/redis.conf <<EOF
bind 0.0.0.0
protected-mode yes
port 6379
dir /data
appendonly yes
appendfsync always
save ""
maxmemory 192mb
maxmemory-policy noeviction
user default off resetpass -@all resetkeys resetchannels
user nanfo on #$app_hash ~* &* +@all -@dangerous +info +client|setname +client|id
user nanfo-admin on #$admin_hash ~* &* +@all
EOF
chown redis:redis /run/redis/redis.conf /data
unset app_hash admin_hash
exec gosu redis redis-server /run/redis/redis.conf
