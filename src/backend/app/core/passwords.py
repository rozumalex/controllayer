"""Password hashes with scrypt from the standard library. Hashing takes about
50 ms of CPU on purpose, so it runs in a thread, off the event loop."""

import asyncio
import hashlib
import hmac
import secrets

# OWASP suggests N=2^17, which takes 128 MiB a hash. 2^14 takes 16 MiB, so a
# burst of sign-ins doesn't run a small server out of memory.
N, R, P = 2**14, 8, 1


def _hash(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=32)


async def hash_password(password: str) -> str:
    """The hash to store, with its salt and parameters."""
    salt = secrets.token_bytes(16)
    digest = await asyncio.to_thread(_hash, password, salt, N, R, P)
    return f"scrypt${N}${R}${P}${salt.hex()}${digest.hex()}"


async def verify_password(password: str, stored: str | None) -> bool:
    """Whether the password matches the stored hash. With no hash, it still
    hashes once, so a missing user takes as long as a wrong password."""
    try:
        _, n, r, p, salt, digest = (stored or "").split("$")
        params = int(n), int(r), int(p)
        expected = bytes.fromhex(digest)
        salt_bytes = bytes.fromhex(salt)
    except ValueError:
        await asyncio.to_thread(_hash, password, b"\0" * 16, N, R, P)
        return False
    actual = await asyncio.to_thread(_hash, password, salt_bytes, *params)
    return hmac.compare_digest(actual, expected)
