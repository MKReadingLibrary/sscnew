#!/usr/bin/env bash
set -e

# ── 1.  Provide Windscribe credentials to OpenVPN ─────────────
if [[ -z "$VPN_USER" || -z "$VPN_PASS" ]]; then
  echo "✖️  Set VPN_USER and VPN_PASS in Railway variables"; exit 1
fi

printf "%s\n%s\n" "$VPN_USER" "$VPN_PASS" > /tmp/auth.txt
chmod 600 /tmp/auth.txt

# ── 2.  Launch OpenVPN daemon ─────────────────────────────────
echo "🚀 Starting Windscribe (India) VPN …"
/usr/sbin/openvpn --config /app/windscribe-india.ovpn \
                  --auth-user-pass /tmp/auth.txt \
                  --daemon

# wait until tunnel is reachable
echo -n "⏳ Waiting for tun0 "
for i in {1..25}; do
  ip addr show tun0 &>/dev/null && { echo "✓"; break; }
  echo -n "."; sleep 1
done

# ── 3.  Run the scraper  ──────────────────────────────────────
exec python /app/main.py
