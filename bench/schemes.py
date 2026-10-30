"""Key-establishment schemes under test.

Three families are implemented:
  * ECDH        - ephemeral X25519 (pyca/cryptography, OpenSSL backend)
  * ML-KEM-L    - FIPS 203 ML-KEM at L in {512, 768, 1024} (liboqs via liboqs-python)
  * Hybrid-L    - X25519 + ML-KEM-L, both shared secrets concatenated and
                  passed through HKDF-SHA256

Every scheme derives its final 32-byte session key with HKDF-SHA256 so that the
key-derivation step is identical across schemes and the hybrid-minus-PQC delta
isolates the cost of the classical component.

Phases (one-round-trip handshake, initiator A and responder B):
  keygen : A generates its ephemeral key pair(s) and serialises the public key(s)
  encap  : B processes A's public key(s): X25519 ephemeral keygen + DH, and/or
           ML-KEM encapsulation, then derives the session key
  decap  : A processes B's reply: X25519 DH and/or ML-KEM decapsulation, then
           derives the session key
  total  : keygen + encap + decap (pure computation, no network)
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import oqs
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_now = time.perf_counter_ns
SESSION_KEY_LEN = 32
X25519_LEN = 32


def derive_session_key(secret: bytes, label: bytes) -> bytes:
    """HKDF-SHA256 (RFC 5869), zero salt, label-bound info, 32-byte output."""
    return HKDF(
        algorithm=hashes.SHA256(),
        length=SESSION_KEY_LEN,
        salt=None,
        info=b"CCA2026-kex-v1|" + label,
    ).derive(secret)


@dataclass
class TrialResult:
    scheme: str
    keygen_ns: int
    encap_ns: int
    decap_ns: int
    pk_bytes: int   # initiator -> responder
    ct_bytes: int   # responder -> initiator

    @property
    def total_ns(self) -> int:
        return self.keygen_ns + self.encap_ns + self.decap_ns


class Scheme:
    name: str
    family: str
    level: int | None  # ML-KEM parameter set (None for ECDH)
    nist_category: int | None

    def run_trial(self) -> TrialResult:  # pragma: no cover - interface
        raise NotImplementedError


class ECDHScheme(Scheme):
    name, family, level, nist_category = "ECDH-X25519", "classical", None, None

    def run_trial(self) -> TrialResult:
        label = self.name.encode()
        # --- keygen (A) ---
        t0 = _now()
        a_priv = X25519PrivateKey.generate()
        a_pub = a_priv.public_key().public_bytes_raw()
        t1 = _now()
        # --- encap (B) ---
        b_priv = X25519PrivateKey.generate()
        b_pub = b_priv.public_key().public_bytes_raw()
        k_b = derive_session_key(
            b_priv.exchange(X25519PublicKey.from_public_bytes(a_pub)), label)
        t2 = _now()
        # --- decap (A) ---
        k_a = derive_session_key(
            a_priv.exchange(X25519PublicKey.from_public_bytes(b_pub)), label)
        t3 = _now()
        if k_a != k_b:
            raise AssertionError(f"{self.name}: session keys differ")
        return TrialResult(self.name, t1 - t0, t2 - t1, t3 - t2,
                           len(a_pub), len(b_pub))


class MLKEMScheme(Scheme):
    family = "pqc"

    def __init__(self, level: int):
        self.level = level
        self.alg = f"ML-KEM-{level}"
        self.name = self.alg
        self.nist_category = {512: 1, 768: 3, 1024: 5}[level]
        # Stateless encapsulator reused across trials (no secret key held).
        self._encapsulator = oqs.KeyEncapsulation(self.alg)

    def run_trial(self) -> TrialResult:
        label = self.name.encode()
        decapsulator = oqs.KeyEncapsulation(self.alg)  # wrapper alloc, untimed
        try:
            t0 = _now()
            pk = decapsulator.generate_keypair()
            t1 = _now()
            ct, ss_b = self._encapsulator.encap_secret(pk)
            k_b = derive_session_key(ss_b, label)
            t2 = _now()
            k_a = derive_session_key(decapsulator.decap_secret(ct), label)
            t3 = _now()
        finally:
            decapsulator.free()
        if k_a != k_b:
            raise AssertionError(f"{self.name}: session keys differ")
        return TrialResult(self.name, t1 - t0, t2 - t1, t3 - t2, len(pk), len(ct))


class HybridScheme(Scheme):
    family = "hybrid"

    def __init__(self, level: int):
        self.level = level
        self.alg = f"ML-KEM-{level}"
        self.name = f"Hybrid-X25519+ML-KEM-{level}"
        self.nist_category = {512: 1, 768: 3, 1024: 5}[level]
        self._encapsulator = oqs.KeyEncapsulation(self.alg)

    def run_trial(self) -> TrialResult:
        label = self.name.encode()
        decapsulator = oqs.KeyEncapsulation(self.alg)
        try:
            # --- keygen (A): X25519 + ML-KEM key pairs ---
            t0 = _now()
            a_priv = X25519PrivateKey.generate()
            a_pub = a_priv.public_key().public_bytes_raw()
            kem_pk = decapsulator.generate_keypair()
            msg_a = a_pub + kem_pk
            t1 = _now()
            # --- encap (B) ---
            r_a_pub, r_kem_pk = msg_a[:X25519_LEN], msg_a[X25519_LEN:]
            b_priv = X25519PrivateKey.generate()
            b_pub = b_priv.public_key().public_bytes_raw()
            ss_ec_b = b_priv.exchange(X25519PublicKey.from_public_bytes(r_a_pub))
            ct, ss_kem_b = self._encapsulator.encap_secret(r_kem_pk)
            k_b = derive_session_key(ss_ec_b + ss_kem_b, label)
            msg_b = b_pub + ct
            t2 = _now()
            # --- decap (A) ---
            r_b_pub, r_ct = msg_b[:X25519_LEN], msg_b[X25519_LEN:]
            ss_ec_a = a_priv.exchange(X25519PublicKey.from_public_bytes(r_b_pub))
            ss_kem_a = decapsulator.decap_secret(r_ct)
            k_a = derive_session_key(ss_ec_a + ss_kem_a, label)
            t3 = _now()
        finally:
            decapsulator.free()
        if k_a != k_b:
            raise AssertionError(f"{self.name}: session keys differ")
        return TrialResult(self.name, t1 - t0, t2 - t1, t3 - t2, len(msg_a), len(msg_b))


def all_schemes() -> list[Scheme]:
    out: list[Scheme] = [ECDHScheme()]
    for lvl in (512, 768, 1024):
        out += [MLKEMScheme(lvl), HybridScheme(lvl)]
    return out
