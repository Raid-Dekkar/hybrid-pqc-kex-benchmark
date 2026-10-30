"""Correctness and conformance checks for the benchmarked schemes.

Run with:  python -m pytest -q tests/
"""
import os
import sys
from pathlib import Path

import oqs
import pytest
from cryptography.hazmat.primitives.asymmetric import mlkem as ossl_mlkem

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bench.schemes import ECDHScheme, HybridScheme, MLKEMScheme, all_schemes  # noqa: E402

# FIPS 203, Table 3 (sizes in bytes): (encapsulation key, ciphertext)
FIPS203_SIZES = {512: (800, 768), 768: (1184, 1088), 1024: (1568, 1568)}


@pytest.mark.parametrize("scheme", all_schemes(), ids=lambda s: s.name)
def test_both_parties_derive_same_key(scheme):
    for _ in range(25):
        scheme.run_trial()  # raises AssertionError on mismatch


@pytest.mark.parametrize("level", [512, 768, 1024])
def test_wire_sizes_match_fips203(level):
    pk, ct = FIPS203_SIZES[level]
    r = MLKEMScheme(level).run_trial()
    assert (r.pk_bytes, r.ct_bytes) == (pk, ct)
    h = HybridScheme(level).run_trial()
    assert (h.pk_bytes, h.ct_bytes) == (pk + 32, ct + 32)


def test_ecdh_sizes():
    r = ECDHScheme().run_trial()
    assert (r.pk_bytes, r.ct_bytes) == (32, 32)


@pytest.mark.parametrize("level", [512, 768, 1024])
def test_implicit_rejection_on_tampered_ciphertext(level):
    """FIPS 203 decapsulation must not fail loudly; it returns a pseudorandom key."""
    alg = f"ML-KEM-{level}"
    with oqs.KeyEncapsulation(alg) as rx, oqs.KeyEncapsulation(alg) as tx:
        pk = rx.generate_keypair()
        ct, ss = tx.encap_secret(pk)
        bad = bytearray(ct); bad[0] ^= 0x01
        ss_bad = rx.decap_secret(bytes(bad))
        assert len(ss_bad) == 32 and ss_bad != ss


@pytest.mark.parametrize("level,cls", [
    (768, (ossl_mlkem.MLKEM768PrivateKey, ossl_mlkem.MLKEM768PublicKey)),
    (1024, (ossl_mlkem.MLKEM1024PrivateKey, ossl_mlkem.MLKEM1024PublicKey)),
])
def test_cross_implementation_liboqs_vs_openssl(level, cls):
    """Same 64-byte seed (d||z) must give byte-identical encapsulation keys in
    liboqs and OpenSSL, and ciphertexts must interoperate in both directions."""
    priv_cls, pub_cls = cls
    seed = os.urandom(64)
    with oqs.KeyEncapsulation(f"ML-KEM-{level}") as q:
        pk_oqs = q.generate_keypair_seed(seed)
        sk_ossl = priv_cls.from_seed_bytes(seed)
        assert sk_ossl.public_key().public_bytes_raw() == pk_oqs
        # OpenSSL encapsulates -> liboqs decapsulates
        ss1, ct1 = pub_cls.from_public_bytes(pk_oqs).encapsulate()
        assert q.decap_secret(ct1) == ss1
    # liboqs encapsulates -> OpenSSL decapsulates
    with oqs.KeyEncapsulation(f"ML-KEM-{level}") as tx:
        ct2, ss2 = tx.encap_secret(pk_oqs)
        assert sk_ossl.decapsulate(ct2) == ss2
