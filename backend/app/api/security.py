"""Autenticação: senha com scrypt (stdlib) e token JWT HS256 com expiração."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time

import jwt

N, R, P = 2 ** 14, 8, 1


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(pw.encode(), salt=salt, n=N, r=R, p=P, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, s, h = stored.split("$")
        dk = hashlib.scrypt(pw.encode(), salt=base64.b64decode(s), n=N, r=R, p=P, dklen=32)
        return hmac.compare_digest(dk, base64.b64decode(h))
    except Exception:
        return False


def make_token(user: str, secret: str, minutes: int) -> str:
    now = int(time.time())
    return jwt.encode({"sub": user, "iat": now, "exp": now + minutes * 60}, secret, algorithm="HS256")


def read_token(token: str, secret: str) -> str:
    return jwt.decode(token, secret, algorithms=["HS256"])["sub"]


class LoginLimiter:
    """Bloqueia força bruta: 5 falhas em 10 min por usuário/IP."""

    def __init__(self, max_fail=5, window=600):
        self.max, self.window, self.fails = max_fail, window, {}

    def allowed(self, key: str) -> bool:
        now = time.time()
        self.fails[key] = [t for t in self.fails.get(key, []) if now - t < self.window]
        return len(self.fails[key]) < self.max

    def fail(self, key: str):
        self.fails.setdefault(key, []).append(time.time())
