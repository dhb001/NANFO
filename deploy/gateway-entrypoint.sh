#!/bin/sh
# NANFO gateway start-up, baked into the frontend image (nothing is bind-mounted).
# Renders /tmp/nginx/{upstream.conf,realip.conf,trusted-hop.map} from two validated
# values, then runs nginx in the foreground:
#   NANFO_GATEWAY_UPSTREAM      single | distributed  (baked upstream definitions)
#   NANFO_GATEWAY_TRUSTED_HOP   IPv4 address allowed to supply X-Forwarded-For/-Proto:
#                               the published port's Docker bridge gateway, where the
#                               host TLS proxy connects (R06). Empty: nobody trusted.
# --render DIR renders only (tests/CI) and never starts nginx.
set -eu
umask 077
out=/tmp/nginx
render_only=
if [ "$#" -gt 0 ]; then
  if [ "$#" -ne 2 ] || [ "$1" != "--render" ]; then
    echo "usage: nanfo-gateway-entrypoint.sh [--render DIR]" >&2
    exit 64
  fi
  out=$2
  render_only=1
fi
case "${NANFO_GATEWAY_UPSTREAM:-single}" in
  single) upstream=/etc/nginx/nanfo/upstream-single.conf ;;
  distributed) upstream=/etc/nginx/nanfo/upstream-distributed.conf ;;
  *) echo "NANFO_GATEWAY_UPSTREAM must be single or distributed" >&2; exit 64 ;;
esac
hop=${NANFO_GATEWAY_TRUSTED_HOP:-}
valid_ipv4() {
  case "$1" in ''|*[!0-9.]*|.*|*.|*..*) return 1 ;; esac
  old_ifs=$IFS
  IFS=.
  # shellcheck disable=SC2086 # deliberate field splitting of a digits-and-dots value
  set -- $1
  IFS=$old_ifs
  [ "$#" -eq 4 ] || return 1
  for octet do
    case "$octet" in 0?*) return 1 ;; esac
    [ "${#octet}" -le 3 ] || return 1
    [ "$octet" -le 255 ] || return 1
  done
}
if [ -n "$hop" ] && ! valid_ipv4 "$hop"; then
  echo "NANFO_GATEWAY_TRUSTED_HOP must be a single IPv4 address" >&2
  exit 64
fi
mkdir -p "$out"
printf 'include %s;\n' "$upstream" > "$out/upstream.conf"
if [ -n "$hop" ]; then
  printf 'set_real_ip_from %s/32;\n' "$hop" > "$out/realip.conf"
  printf '%s 1;\n' "$hop" > "$out/trusted-hop.map"
else
  rm -f "$out/realip.conf" "$out/trusted-hop.map"
fi
if [ -n "$render_only" ]; then
  exit 0
fi
exec nginx -g 'daemon off;'
