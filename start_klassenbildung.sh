#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PORT=6767

# macOS ships with Python 3.9, which is too old for streamlit/ortools.
# Pick the first interpreter that is at least 3.11.
find_python() {
  for candidate in python3.13 python3.12 python3.11 python3 "$HOME/.local/bin/python3.13" \
                   /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    if command -v "$candidate" >/dev/null 2>&1 || [ -x "$candidate" ]; then
      if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
        echo "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

if [ ! -d ".venv" ]; then
  if ! PYTHON="$(find_python)"; then
    echo "Kein Python 3.11+ gefunden." >&2
    echo "Bitte installieren, z. B. mit:  brew install python@3.13" >&2
    echo "(Homebrew: https://brew.sh)" >&2
    exit 1
  fi
  echo "Erstelle virtuelle Umgebung mit $PYTHON ..."
  "$PYTHON" -m venv .venv
fi

source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# Browser oeffnen, sobald der Server antwortet (macOS: open, Linux: xdg-open).
(
  for _ in $(seq 1 60); do
    if curl -s -o /dev/null "http://localhost:$PORT"; then
      if command -v open >/dev/null 2>&1; then
        open "http://localhost:$PORT"
      elif command -v xdg-open >/dev/null 2>&1; then
        xdg-open "http://localhost:$PORT"
      fi
      break
    fi
    sleep 1
  done
) &

python -m streamlit run app.py --server.address localhost --server.port "$PORT"
