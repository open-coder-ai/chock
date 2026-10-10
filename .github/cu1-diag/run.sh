#!/bin/sh
# CU-1 temporary: rebuild the witness plugin as the kit does and trace the owner's payload from home and from the repo.
set -u
here=$(cd "$(dirname "$0")" && pwd)
home=$(cygpath -m "$USERPROFILE")
plugin="$home/.cursor/plugins/local/chock-witness"
repo="$home/witness-repo-cursor"

chock install --selection "$here/selection.yaml" --client cursor --dest "$home/.cursor/plugins/local" 2>&1 | tail -5
mkdir -p "$repo" && git -C "$repo" init -q
python -c '
import json, sys
src, home, out = sys.argv[1:4]
text = open(src, encoding="utf-8").read()
win = home.replace("/", "\\")
text = text.replace("C:\\\\Users\\\\jothi", win.replace("\\", "\\\\")).replace("/C:/Users/jothi", "/" + home)
json.loads(text)
open(out, "w", encoding="utf-8").write(text)
' "$here/payload.json" "$home" "$here/payload.local.json"
cat "$here/payload.local.json"; echo

for where in "$home" "$repo"; do
    echo; echo "######## diag, cwd = $where"
    (cd "$where" && python "$here/chock_diag.py" "$plugin" < "$here/payload.local.json") 2>&1
    echo "######## pin hook as Cursor runs it, cwd = $where"
    command=$(python -c 'import json,sys; print(json.load(open(sys.argv[1]))["hooks"]["preToolUse"][0]["command"])' "$plugin/hooks/hooks.json")
    (cd "$where" && CURSOR_PLUGIN_ROOT="$plugin" bash -c "$command" < "$here/payload.local.json") 2>&1
    echo
done
