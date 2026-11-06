"""Rode: python3 -m pytest -q references/  (ou: python3 references/teste_verificar_webhook.py)"""
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))
from verificar_webhook import assinatura_ok, janela_ok

SEG = b"It's a Secret to Everybody"          # vetor de teste publicado na doc do GitHub
CORPO = b"Hello, World!"
OFICIAL = "sha256=757107ea0eb2509fc211221cce984b8a37570b6d7586c22c46f4379c8b043e17"

def test_vetor_oficial_github():
    assert assinatura_ok(SEG, CORPO, OFICIAL)

def test_corpo_alterado_reprova():
    assert not assinatura_ok(SEG, b"Hello, World?", OFICIAL)

def test_header_ausente_reprova():
    assert not assinatura_ok(SEG, CORPO, None)

def test_segredo_errado_reprova():
    assert not assinatura_ok(b"outro", CORPO, OFICIAL)

def test_clickup_sem_prefixo():
    assert assinatura_ok(SEG, CORPO, OFICIAL.removeprefix("sha256="), prefixo="")

def test_janela_de_5_min():
    assert janela_ok(1000, agora=1240)
    assert not janela_ok(1000, agora=1360)

if __name__ == "__main__":
    for nome, f in list(globals().items()):
        if nome.startswith("test_"):
            f()
            print("ok", nome)
