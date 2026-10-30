# Hybrid Classical–Post-Quantum Key Establishment Benchmark

The benchmark compares seven key-establishment configurations in isolation
(no TLS stack, no network):

| Family | Configurations | Implementation |
|---|---|---|
| Classical | X25519 ECDH | pyca/cryptography 50.0.2 (bundled OpenSSL 4.0.3) |
| Post-quantum | ML-KEM-512, ML-KEM-768, ML-KEM-1024 (FIPS 203) | liboqs 0.16.0 via liboqs-python 0.16.0.1 |
| Hybrid | X25519 + ML-KEM-{512, 768, 1024} | both of the above, secrets combined by HKDF-SHA256 |

Each configuration was measured for **1,000 trials (5 independent runs × 200 trials)**
after 50 discarded warm-up iterations per run. Every trial checks that both parties
derive the same 32-byte session key.

## Repository layout

```
bench/
  schemes.py         the three scheme families and the timed handshake phases
  run_benchmark.py   one independent run -> results/raw/run_XX_trials.csv
  analyze.py         statistics
  env_info.py        records hardware/software configuration
tests/
  test_correctness.py  key agreement, FIPS 203 sizes, implicit rejection,
                       liboqs <-> OpenSSL cross-implementation check
scripts/
  install_liboqs.sh  builds the exact liboqs version/commit used
  run_all.sh         tests -> 5 runs -> analysis -> figures
results/
  raw/               per-trial data (7,000 rows) + per-run environment JSON
  summary/           timing_summary.csv, run_stability.csv, hybrid_overhead.csv,
                     communication.csv, summary.json
  tables/            LaTeX tabular environments.
  figures/           handshake_time, communication_overhead
  environment.json   platform record; pip_freeze.txt   full package list
```

## Experimental platform

| Item | Value |
|---|---|
| CPU | Intel Xeon @ 2.90 GHz, family 6 model 106 (Ice Lake-SP), AVX2/AVX-512, SHA-NI |
| vCPUs / pinning | 2 vCPUs, benchmark pinned to one core (`taskset -c 1`), 1 thread per core |
| Caches | L1d 48 KiB/core, L2 1.25 MiB/core, L3 54 MiB shared |
| Memory | 7.8 GiB |
| Virtualisation | KVM guest; frequency scaling governor not exposed to the guest |
| OS / kernel | Ubuntu 26.04.1 LTS, Linux 6.1.155 (x86_64) |
| Python | CPython 3.14.8 (Clang 23.1.3 build) |
| ML-KEM | liboqs 0.16.0 (commit `5a1a854b`), `OQS_DIST_BUILD=ON` (runtime dispatch to the x86_64 AVX2 ML-KEM code), `OQS_USE_OPENSSL=OFF`, Release build, GCC 15.2.0 |
| ML-KEM binding | liboqs-python 0.16.0.1 |
| X25519, HKDF-SHA256 | cryptography 50.0.2, linked against its bundled OpenSSL 4.0.3 |
| Analysis | numpy 2.5.4, pandas 3.1.0, matplotlib 3.11.2 |

The full machine-readable record is in `results/environment.json`; each run also
stores its own copy in `results/raw/run_XX_environment.json`.

## Measurement protocol

A handshake has one round trip between initiator A and responder B. Wire formats
are the raw encodings (32-byte X25519 keys, FIPS 203 byte strings); hybrid messages
are simple concatenations (X25519 part first).

| Phase | X25519 | ML-KEM-L | Hybrid-L |
|---|---|---|---|
| **KeyGen** (A) | key pair + encode public key | `KeyGen` | both |
| **Encap** (B) | ephemeral key pair + DH + HKDF | `Encaps` + HKDF | X25519 key pair + DH + `Encaps` + HKDF(ss_ec ‖ ss_kem) |
| **Decap** (A) | DH + HKDF | `Decaps` + HKDF | DH + `Decaps` + HKDF(ss_ec ‖ ss_kem) |
| **Total** | sum of the three phases | | |

- **Clock:** `time.perf_counter_ns()` (monotonic, ns resolution). Times are wall-clock
  CPU time of the Python calls, so they include binding overhead (a few µs per call);
  they are not cycle counts of the C code.
- **Same KDF everywhere:** all seven schemes derive the session key with HKDF-SHA256
  (zero salt, scheme-specific `info`), so the hybrid-minus-ML-KEM difference isolates
  the classical component.
- **Warm-up:** 50 iterations of every scheme per run, discarded.
- **Interleaving:** within each trial the seven schemes run once each in a seeded random
  order (seed = 2026 + run id), so slow drifts affect all schemes equally.
- **Garbage collector:** Python's cyclic GC is disabled for the whole measured phase.
- **Independence:** five separate processes (runs), each with its own warm-up.
- **Wrapper allocation:** creation of the liboqs-python `KeyEncapsulation` object is
  outside the timed region; the cryptographic calls themselves are inside.

### Statistics

The timing distributions are right-skewed with occasional preemption outliers, so the
**median** and **interquartile range (IQR)** are the primary statistics. The analysis
also reports mean, standard deviation, 5 % trimmed mean, 5th/95th percentiles and
95 % percentile-bootstrap confidence intervals (10,000 resamples) for the mean, the
median, and the hybrid-minus-ML-KEM median difference. No observations were removed.

## Results (1,000 trials per configuration)

Median (IQR) in microseconds:

| Scheme | KeyGen | Encap | Decap | **Total** | Bytes on wire |
|---|---|---|---|---|---|
| X25519 | 37.8 (1.5) | 78.6 (2.7) | 41.4 (1.4) | **157.9 (6.8)** | 64 |
| ML-KEM-512 | 8.3 (0.6) | 14.2 (0.8) | 14.3 (0.5) | **36.9 (1.9)** | 1,568 |
| X25519+ML-KEM-512 | 46.7 (1.9) | 90.4 (3.5) | 53.2 (1.8) | **190.9 (11.5)** | 1,632 |
| ML-KEM-768 | 11.7 (0.7) | 17.4 (0.8) | 18.4 (0.7) | **47.6 (2.3)** | 2,272 |
| X25519+ML-KEM-768 | 50.2 (1.8) | 94.0 (3.2) | 57.5 (1.9) | **202.1 (10.4)** | 2,336 |
| ML-KEM-1024 | 14.5 (0.8) | 20.7 (0.9) | 22.5 (0.8) | **57.7 (2.8)** | 3,136 |
| X25519+ML-KEM-1024 | 53.0 (2.0) | 97.0 (3.3) | 61.6 (2.1) | **212.4 (9.7)** | 3,200 |

Cost of adding X25519 to ML-KEM (difference of medians, 95 % bootstrap CI):

| Level | Δ total (µs) | Relative to ML-KEM alone |
|---|---|---|
| 512 | 154.0 [153.7, 154.3] | +418 % |
| 768 | 154.5 [154.2, 154.8] | +324 % |
| 1024 | 154.6 [154.1, 155.0] | +268 % |

Key observations:

1. **ML-KEM is faster than X25519** in this stack at every level (37–58 µs vs 158 µs).
2. **The hybrid penalty is constant** (~154 µs ≈ one full X25519 exchange) and does not
   depend on the ML-KEM level. It is large in relative terms but sub-millisecond in
   absolute terms.
3. **Raising the ML-KEM level costs ~10 µs per step** in computation (37 → 48 → 58 µs),
   but **~700–860 bytes per step** on the wire.
4. **Communication is dominated by ML-KEM**: X25519 contributes a fixed 64 bytes,
   i.e. 3.9 %, 2.7 % and 2.0 % of the hybrid payload at levels 512/768/1024.
5. **Stability:** between-run coefficient of variation of the median is ≤ 1.0 % for every
   configuration (`results/summary/run_stability.csv`).

## Validation

`python -m pytest -q tests` runs 16 checks:

- both parties derive identical session keys (all seven schemes);
- public-key and ciphertext lengths equal FIPS 203 Table 3 (800/768, 1184/1088, 1568/1568 B);
- tampered ciphertexts trigger FIPS 203 implicit rejection (a different pseudorandom key, no error);
- **cross-implementation conformance:** for ML-KEM-768 and ML-KEM-1024, the same 64-byte seed
  yields byte-identical encapsulation keys in liboqs and in OpenSSL (via pyca/cryptography),
  and ciphertexts decapsulate correctly in both directions.

**Harness artifact found and removed.** An earlier version of the harness forced a garbage
collection between trials. This made the first operations after each collection slower
(ML-KEM-768 KeyGen median 56 µs in the first position of a trial vs 12 µs in the last),
because freed memory had to be faulted back in. Only the phases that allocate output
buffers (KeyGen, Encap) were affected; Decap was not. The final harness keeps the collector
disabled throughout, and `summary.json` reports the median total time by position within a
trial (157–160 µs, flat) as a regression check.

## Reproducing the results

```bash
python3 -m venv venv && . venv/bin/activate
pip install cmake ninja
pip install -r requirements.txt
scripts/install_liboqs.sh
export OQS_INSTALL_PATH=$HOME/_oqs LD_LIBRARY_PATH=$HOME/_oqs/lib
scripts/run_all.sh    # 5 runs x 200 trials
```

`run_all.sh [RUNS] [TRIALS] [WARMUP] [CPU]` changes the defaults. On a different machine
absolute timings will differ; the relative findings above are what the paper relies on.

## Limitations

- Single platform (one virtualised x86-64 Ice Lake host); no ARM or embedded targets.
- Python-level timing includes binding overhead; X25519 and ML-KEM come from different
  libraries (OpenSSL vs liboqs), so the X25519/ML-KEM speed ratio reflects these
  particular implementations.
- Computation only: no network latency, packet fragmentation, TLS framing,
  authentication (signatures/certificates) or energy measurements.
- The hybrid combiner is plain concatenation + HKDF; transcript binding as in TLS 1.3
  is not modelled (it does not change the measured cost materially).

## Citation
Citation details will be added when available.


## License

MIT, see `LICENSE`.
