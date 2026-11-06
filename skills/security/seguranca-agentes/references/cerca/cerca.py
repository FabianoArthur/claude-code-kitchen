#!/usr/bin/env python3
"""PreToolUse (matcher Bash): barra ações irreversíveis ou de credencial.
Fail-closed: qualquer erro de leitura/parse também bloqueia (exit 2)."""
import json
import os
import re
import sys

BASES = os.environ.get("CERCA_BASES", "main master release staging dev production").split()
SEP = r"[;&|\n]"  # fronteira de subcomando

REGRAS = [
    (r"\bgh\s+pr\s+merge\b", "merge é do humano"),
    (r"(^|" + SEP + r"|\s|\()sudo\s", "sudo não é permitido ao agente"),
    (r"\b(curl|wget)\b[^;&\n]*\|\s*(sudo\s+)?(ba|z|da)?sh\b", "baixar e executar script"),
    (r"(~|\$HOME|/Users/[^/\s]+)/(\.ssh|\.aws|\.config/gh)\b|\.claude\.json\b|clickup_token\b|\.config/discord",
     "arquivo de credencial"),
]

def motivo_push(cmd: str):
    for m in re.finditer(r"\bgit\b[^;&|\n]*?\bpush\b([^;&|\n]*)", cmd):
        args = m.group(1).replace('"', " ").replace("'", " ").split()
        for a in args:
            if a in ("--mirror", "--delete") or a.startswith("--force"):
                return "push forçado/destrutivo"
            if re.fullmatch(r"-[A-Za-z]*[fd][A-Za-z]*", a):  # -f, -d e combinadas (-uf)
                return "push forçado/destrutivo"
            if a.startswith("+"):  # refspec +origem:destino força o push
                return "push forçado (refspec com +)"
            if a.startswith(":"):
                return "remoção de branch remota"
            alvo = a.split(":")[-1].removeprefix("refs/heads/")
            if alvo in BASES:
                return f"push direto na base '{alvo}'"
    return None

def main() -> int:
    try:
        evento = json.load(sys.stdin)
        cmd = evento["tool_input"]["command"]
        if not isinstance(cmd, str):
            raise ValueError("command não é string")
    except Exception as e:  # fail-closed
        print(f"cerca: entrada ilegível ({e}); bloqueado por segurança", file=sys.stderr)
        return 2
    for padrao, motivo in REGRAS:
        if re.search(padrao, cmd):
            print(f"cerca: {motivo}. Peça ao humano.", file=sys.stderr)
            return 2
    m = motivo_push(cmd)
    if m:
        print(f"cerca: {m}. Abra PR a partir da sua branch.", file=sys.stderr)
        return 2
    return 0

if __name__ == "__main__":
    sys.exit(main())
