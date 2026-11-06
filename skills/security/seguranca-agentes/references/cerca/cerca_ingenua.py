#!/usr/bin/env python3
"""CONTRAPROVA, não use: a regra por prefixo que parece suficiente.
Rode ./teste.sh ./cerca_ingenua.py para ver quantos casos de bloqueio ela deixa passar."""
import json
import sys
cmd = json.load(sys.stdin)["tool_input"]["command"]
if cmd.startswith("git push origin main"):
    print("push na base", file=sys.stderr)
    sys.exit(2)
