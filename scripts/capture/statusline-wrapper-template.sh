#!/bin/sh
# Compose wrapper: existing statusline output + capture badge on its final line.
# Shipped as a template; /drvr:capture-statusline substitutes the placeholder below at install.
PAYLOAD="$(cat 2>/dev/null)" || PAYLOAD=""
ORIG="$(printf '%s' "$PAYLOAD" | {{ORIGINAL_COMMAND}} 2>/dev/null)"
BADGE="$(sh "$(dirname "$0")/capture-statusline.sh" </dev/null 2>/dev/null)" || BADGE=""
if [ -z "$BADGE" ]; then
  printf '%s\n' "$ORIG"
elif [ -z "$ORIG" ]; then
  printf '%s\n' "$BADGE"
else
  printf '%s %s\n' "$ORIG" "$BADGE"
fi
exit 0
