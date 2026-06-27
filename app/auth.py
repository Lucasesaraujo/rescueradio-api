import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Literal

import jwt


ROLE_OPERADOR = "operador"
ROLE_COMANDANTE = "comandante"
ROLE_ADMIN = "admin"
ALLOWED_ROLES = {ROLE_OPERADOR, ROLE_COMANDANTE, ROLE_ADMIN}

PasswordVerifyResult = Literal["valid", "invalid", "needs_rehash"]


def get_jwt_secret() -> str:
    return os.getenv("JWT_SECRET", "rescueradio-dev-secret")


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    iterations = 260_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_raw, salt_raw, digest_raw = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False

        iterations = int(iterations_raw)
        salt = base64.b64decode(salt_raw.encode("ascii"))
        expected_digest = base64.b64decode(digest_raw.encode("ascii"))
    except (ValueError, TypeError):
        return False

    candidate = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(candidate, expected_digest)


def create_access_token(user: dict) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=int(os.getenv("JWT_EXPIRE_MINUTES", "480"))
    )
    payload = {
        "sub": user["username"],
        "display_name": user["display_name"],
        "role": user["role"],
        "base_id": user.get("base_id"),
        "exp": expires_at,
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm="HS256")


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, get_jwt_secret(), algorithms=["HS256"])


def public_user(user: dict) -> dict:
    return {
        "username": user["username"],
        "display_name": user["display_name"],
        "role": user["role"],
        "base_id": user.get("base_id"),
    }
