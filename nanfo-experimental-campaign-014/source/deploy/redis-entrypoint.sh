#!/bin/sh
set -eu
umask 077
password=$(cat /run/secrets/redis_password)
# Generated URL-safe secrets cannot inject Redis configuration or shell syntax.
case "$password" in *[!a-zA-Z0-9_-]*|'') exit 1 ;; esac
test "${#password}" -ge 32
test "${#password}" -le 128
printf 'bind 0.0.0.0\nprotected-mode yes\nport 6379\ndir /data\nappendonly yes\nappendfsync always\nsave ""\nmaxmemory 192mb\nmaxmemory-policy noeviction\nrequirepass %s\n' "$password" > /run/redis/redis.conf
chown redis:redis /run/redis/redis.conf /data
unset password
exec gosu redis redis-server /run/redis/redis.conf
