#!/bin/sh
set -eu
password=$(cat /run/secrets/neo4j_password)
case "$password" in *[!a-zA-Z0-9_-]*|'') exit 1 ;; esac
test "${#password}" -ge 32
test "${#password}" -le 128
export NEO4J_AUTH="neo4j/$password"
unset password
cp /opt/neo4j-conf/* /var/lib/neo4j/conf/
chown -R neo4j:neo4j /var/lib/neo4j/conf
chown neo4j:neo4j /data
# Use the shipped entrypoint; never set NEO4J_PLUGINS / download APOC.
# Run the signal forwarder under the same UID as Java. A root tini with KILL
# dropped cannot signal the child after su-exec changes UID (unclean shutdown).
exec su-exec neo4j:neo4j tini -g -- /startup/docker-entrypoint.sh neo4j
