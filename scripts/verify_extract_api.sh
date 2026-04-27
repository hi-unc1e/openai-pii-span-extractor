#!/usr/bin/env sh
set -eu

BASE_URL="${OPF_BASE_URL:-http://localhost:8000}"
SAMPLE_TEXT="My name is Alice Smith and my email is alice@example.com. Call me at 555-123-4567."

pretty_json() {
  if command -v python3 >/dev/null 2>&1; then
    python3 -m json.tool
  else
    cat
  fi
}

post_json() {
  path="$1"
  payload="$2"
  curl -fsS \
    -H "Content-Type: application/json" \
    -X POST \
    "$BASE_URL$path" \
    -d "$payload"
}

echo "== Health check: $BASE_URL/health =="
curl -fsS "$BASE_URL/health" | pretty_json
echo

echo "== Extract all labels =="
post_json "/extract" "{
  \"text\": \"$SAMPLE_TEXT\"
}" | pretty_json
echo

echo "== Extract private_email only =="
post_json "/extract" "{
  \"text\": \"$SAMPLE_TEXT\",
  \"labels\": [\"private_email\"]
}" | pretty_json
echo

echo "== Extract batch =="
post_json "/extract/batch" "{
  \"texts\": [
    \"$SAMPLE_TEXT\",
    \"The backup token is sk-test-1234567890 and the site is https://example.com/private.\"
  ]
}" | pretty_json
