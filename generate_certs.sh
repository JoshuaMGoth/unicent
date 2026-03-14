#!/bin/bash
# Generate TLS certificates for UniCent encrypted communication.
#
# Creates:
#   certs/ca.crt, certs/ca.key         - Certificate Authority
#   certs/server.crt, certs/server.key  - Host server certificate
#   certs/client.crt, certs/client.key  - Client certificate
#
# Usage: ./generate_certs.sh [output_dir]

set -e

CERT_DIR="${1:-certs}"
DAYS=3650  # 10 years
KEY_SIZE=2048

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║     UniCent TLS Certificate Gen      ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

mkdir -p "$CERT_DIR"

# --- Certificate Authority ---
echo "  [1/3] Generating CA certificate..."
openssl req -x509 -newkey "rsa:$KEY_SIZE" -nodes \
    -keyout "$CERT_DIR/ca.key" \
    -out "$CERT_DIR/ca.crt" \
    -days "$DAYS" \
    -subj "/CN=unicent-ca/O=UniCent/OU=CA" \
    2>/dev/null

echo "        CA cert: $CERT_DIR/ca.crt"

# --- Server Certificate ---
echo "  [2/3] Generating server certificate..."

# Create server CSR config
cat > "$CERT_DIR/server.cnf" <<EOF
[req]
default_bits = $KEY_SIZE
prompt = no
distinguished_name = dn
req_extensions = v3_req

[dn]
CN = unicent-host
O = UniCent
OU = Host

[v3_req]
subjectAltName = @alt_names

[alt_names]
DNS.1 = localhost
DNS.2 = *.local
IP.1 = 127.0.0.1
IP.2 = 0.0.0.0
EOF

# Add all local IPs as SANs
IP_COUNT=3
for ip in $(hostname -I 2>/dev/null || ifconfig 2>/dev/null | grep 'inet ' | awk '{print $2}' | sed 's/addr://'); do
    echo "IP.$IP_COUNT = $ip" >> "$CERT_DIR/server.cnf"
    IP_COUNT=$((IP_COUNT + 1))
done

openssl req -newkey "rsa:$KEY_SIZE" -nodes \
    -keyout "$CERT_DIR/server.key" \
    -out "$CERT_DIR/server.csr" \
    -config "$CERT_DIR/server.cnf" \
    2>/dev/null

openssl x509 -req \
    -in "$CERT_DIR/server.csr" \
    -CA "$CERT_DIR/ca.crt" \
    -CAkey "$CERT_DIR/ca.key" \
    -CAcreateserial \
    -out "$CERT_DIR/server.crt" \
    -days "$DAYS" \
    -extensions v3_req \
    -extfile "$CERT_DIR/server.cnf" \
    2>/dev/null

echo "        Server cert: $CERT_DIR/server.crt"

# --- Client Certificate ---
echo "  [3/3] Generating client certificate..."

cat > "$CERT_DIR/client.cnf" <<EOF
[req]
default_bits = $KEY_SIZE
prompt = no
distinguished_name = dn

[dn]
CN = unicent-client
O = UniCent
OU = Client
EOF

openssl req -newkey "rsa:$KEY_SIZE" -nodes \
    -keyout "$CERT_DIR/client.key" \
    -out "$CERT_DIR/client.csr" \
    -config "$CERT_DIR/client.cnf" \
    2>/dev/null

openssl x509 -req \
    -in "$CERT_DIR/client.csr" \
    -CA "$CERT_DIR/ca.crt" \
    -CAkey "$CERT_DIR/ca.key" \
    -CAcreateserial \
    -out "$CERT_DIR/client.crt" \
    -days "$DAYS" \
    2>/dev/null

echo "        Client cert: $CERT_DIR/client.crt"

# Cleanup temp files
rm -f "$CERT_DIR"/*.csr "$CERT_DIR"/*.cnf "$CERT_DIR"/*.srl

# Set permissions
chmod 600 "$CERT_DIR"/*.key
chmod 644 "$CERT_DIR"/*.crt

echo ""
echo "  Certificates generated in: $CERT_DIR/"
echo ""
echo "  Files to copy to the macOS client:"
echo "    - $CERT_DIR/ca.crt"
echo "    - $CERT_DIR/client.crt"
echo "    - $CERT_DIR/client.key"
echo ""
echo "  You can transfer these files via USB, scp, or other means."
echo "  Example:"
echo "    scp $CERT_DIR/ca.crt $CERT_DIR/client.* user@mac-hostname:~/mouse-share/certs/"
echo ""
