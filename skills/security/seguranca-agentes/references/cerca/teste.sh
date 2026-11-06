#!/usr/bin/env bash
# bateria: cada linha "esperado<TAB>comando". esperado = bloqueia|passa
h="${1:?caminho do hook}"; falhas=0
while IFS=$'\t' read -r esperado cmd; do
  [ -z "$esperado" ] && continue
  jq -nc --arg c "$cmd" '{hook_event_name:"PreToolUse",tool_name:"Bash",tool_input:{command:$c}}' | "$h" >/dev/null 2>&1; rc=$?
  if [ "$esperado" = bloqueia ] && [ $rc -eq 2 ]; then r=ok; elif [ "$esperado" = passa ] && [ $rc -eq 0 ]; then r=ok; else r=FALHOU; falhas=$((falhas+1)); fi
  printf '%-6s %-8s rc=%s  %s\n' "$r" "$esperado" "$rc" "$cmd"
done < "$(dirname "$0")/casos.tsv"
echo "falhas: $falhas"; [ $falhas -eq 0 ]
