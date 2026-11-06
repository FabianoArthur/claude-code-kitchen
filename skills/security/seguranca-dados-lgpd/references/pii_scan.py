#!/usr/bin/env python3
"""DLP básico: acha CPF (com dígito verificador), e-mail e telefone BR em arquivos de texto/log.
Imprime só tipo, arquivo, linha e valor MASCARADO. Exit 0 = nada achado; 1 = achou; 2 = erro de uso.
Uso: python3 pii_scan.py <arquivo ou diretório> [...]
Heurística, não prova de ausência: nomes próprios, endereços e coordenadas não são detectados."""
import os
import re
import sys

CPF = re.compile(r"(?<![\d.])(\d{3}\.?\d{3}\.?\d{3}-?\d{2})(?![\d.])")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
TEL = re.compile(r"(?<!\d)(?:\+?55[\s-]?)?\(?\d{2}\)?[\s-]?9\d{4}[\s-]?\d{4}(?!\d)")

def cpf_valido(txt: str) -> bool:
    d = [int(c) for c in re.sub(r"\D", "", txt)]
    if len(d) != 11 or len(set(d)) == 1:
        return False
    for n in (9, 10):
        soma = sum(d[i] * (n + 1 - i) for i in range(n))
        if (soma * 10 % 11) % 10 != d[n]:
            return False
    return True

def _mascara(v: str) -> str:
    return v[:2] + "*" * max(len(v) - 4, 1) + v[-2:] if len(v) > 6 else "***"

def achar(linha: str):
    out = []
    for m in CPF.finditer(linha):
        if cpf_valido(m.group(1)):
            out.append(("cpf", _mascara(m.group(1))))
    for m in EMAIL.finditer(linha):
        u, _, dom = m.group(0).partition("@")
        out.append(("email", u[:1] + "***@" + dom))
    for m in TEL.finditer(linha):
        out.append(("telefone", _mascara(re.sub(r"\D", "", m.group(0)))))
    return out

def _arquivos(alvos):
    for a in alvos:
        if os.path.isdir(a):
            for raiz, dirs, nomes in os.walk(a):
                dirs[:] = [d for d in dirs if d not in {".git", "node_modules", ".venv", "venv", "__pycache__"}]
                for n in nomes:
                    yield os.path.join(raiz, n)
        else:
            yield a

def main(argv) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    total = 0
    for caminho in _arquivos(argv):
        try:
            with open(caminho, encoding="utf-8", errors="ignore") as f:
                for i, linha in enumerate(f, 1):
                    for tipo, masc in achar(linha):
                        total += 1
                        print(f"{tipo}\t{caminho}:{i}\t{masc}")
        except (OSError, UnicodeError):
            continue
    print(f"achados: {total}", file=sys.stderr)
    return 1 if total else 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
