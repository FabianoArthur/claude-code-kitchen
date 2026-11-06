"""Rode: python3 skills/security/seguranca-dados-lgpd/references/teste_pii_scan.py"""
import os
import sys
import subprocess
import tempfile
sys.path.insert(0, os.path.dirname(__file__))
from pii_scan import cpf_valido, achar

def test_cpf_valido_de_teste():
    assert cpf_valido("111.444.777-35")          # CPF sintético clássico de exemplo
    assert cpf_valido("111444777" + "35")

def test_cpf_digito_errado():
    assert not cpf_valido("111.444.777-36")

def test_cpf_repetido_nao_conta():
    assert not cpf_valido("111.111.111-11")

def test_acha_cpf_email_telefone_e_mascara():
    linha = "user=joao@example.com cpf=111.444.777-35 tel=(11) 91234-5678"
    tipos = {t for t, _ in achar(linha)}
    assert tipos == {"cpf", "email", "telefone"}
    for _, mascarado in achar(linha):
        assert "joao@" not in mascarado and "777" not in mascarado and "91234" not in mascarado

def test_numero_de_11_digitos_invalido_nao_e_cpf():
    assert [t for t, _ in achar("pedido " + "1234567" + "8901 ok")] == []

def test_cli_exit_code():
    with tempfile.TemporaryDirectory() as d:
        limpo, sujo = os.path.join(d, "limpo.log"), os.path.join(d, "sujo.log")
        open(limpo, "w").write("GET /health 200\n")
        open(sujo, "w").write("login ok email=ana@example.org\n")
        s = os.path.join(os.path.dirname(__file__), "pii_scan.py")
        assert subprocess.run([sys.executable, s, limpo]).returncode == 0
        r = subprocess.run([sys.executable, s, sujo], capture_output=True, text=True)
        assert r.returncode == 1 and "email" in r.stdout and "ana@" not in r.stdout

if __name__ == "__main__":
    falhas = 0
    for nome, f in list(globals().items()):
        if nome.startswith("test_"):
            try:
                f()
                print("ok    ", nome)
            except Exception as e:
                falhas += 1
                print("FALHOU", nome, repr(e))
    print("falhas:", falhas)
    sys.exit(1 if falhas else 0)
