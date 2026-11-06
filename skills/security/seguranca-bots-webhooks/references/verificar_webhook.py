import hashlib
import hmac
import time

def assinatura_ok(segredo: bytes, corpo_bruto: bytes, header: str, prefixo: str = "sha256=") -> bool:
    """GitHub (X-Hub-Signature-256, prefixo 'sha256=') e ClickUp (X-Signature, prefixo '')."""
    esperado = prefixo + hmac.new(segredo, corpo_bruto, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, header or "")

def janela_ok(ts: int, agora: float | None = None, tolerancia_s: int = 300) -> bool:
    agora = time.time() if agora is None else agora
    return abs(agora - ts) <= tolerancia_s
