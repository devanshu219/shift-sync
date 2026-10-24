#!/usr/bin/env bash
# Installs the browser and runs the sync. This lives in the shared code (not in
# the workflow file), so fixes here reach every copy automatically.
set -u

# Browser: normally a ~6-second download, because the runner already has the
# system libraries. Only if it won't start are Ubuntu packages installed,
# capped at 3 minutes (Ubuntu's download servers sometimes hang).
if ! timeout 120 python -m playwright install --only-shell chromium; then
  echo "::warning::Couldn't download the browser; shift times will still sync."
fi
if ! python -c "from playwright.sync_api import sync_playwright as s; p = s().start(); p.chromium.launch().close(); p.stop()" 2>/dev/null; then
  echo "The browser needs extra system packages; installing them (3 minutes max) ..."
  timeout 180 python -m playwright install-deps chromium \
    || echo "::warning::Couldn't install the browser's system packages."
fi

# Retries once on a temporary failure (exit 1). Setup problems (exit 2), a
# rejected MLSE or ESS login (exit 3, so a wrong password can't lock an
# account faster) and unreadable event details (exit 4) are NOT retried.
python sync.py && exit 0
code=$?
if [ "$code" -ne 1 ]; then exit "$code"; fi
echo "Run failed (exit $code); retrying once in 60 seconds ..."
sleep 60
python sync.py
