"""Capture the hardware/software environment of a benchmark run."""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from importlib import metadata


def _read(path: str) -> str | None:
    try:
        with open(path) as fh:
            return fh.read().strip()
    except OSError:
        return None


def _cpu() -> dict:
    info: dict = {}
    txt = _read("/proc/cpuinfo") or ""
    for line in txt.splitlines():
        if ":" not in line:
            continue
        k, v = (s.strip() for s in line.split(":", 1))
        if k == "model name":
            info.setdefault("model_name", v)
        elif k in ("cpu family", "model", "stepping", "microcode"):
            info.setdefault(k.replace(" ", "_"), v)
        elif k == "flags":
            flags = set(v.split())
            info.setdefault("simd_flags", sorted(
                f for f in ("sse4_2", "avx", "avx2", "bmi2", "adx", "aes",
                            "avx512f", "avx512vl", "sha_ni") if f in flags))
            info.setdefault("hypervisor", "hypervisor" in flags)
    info["logical_cpus"] = os.cpu_count()
    try:
        out = subprocess.run(["lscpu"], capture_output=True, text=True).stdout
        for line in out.splitlines():
            k, _, v = line.partition(":")
            k, v = k.strip(), v.strip()
            if k in ("Hypervisor vendor", "L1d cache", "L2 cache", "L3 cache",
                     "Core(s) per socket", "Thread(s) per core", "Socket(s)",
                     "CPU max MHz", "BogoMIPS"):
                info[k.lower().replace(" ", "_").replace("(s)", "s")] = v
    except FileNotFoundError:
        pass
    gov = _read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
    info["scaling_governor"] = gov or "not exposed (virtualised)"
    return info


def _mem_total_gib() -> float | None:
    for line in (_read("/proc/meminfo") or "").splitlines():
        if line.startswith("MemTotal"):
            return round(int(line.split()[1]) / 1024 / 1024, 2)
    return None


def _pkg(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def _os_release() -> str | None:
    for line in (_read("/etc/os-release") or "").splitlines():
        if line.startswith("PRETTY_NAME="):
            return line.split("=", 1)[1].strip('"')
    return None


def _liboqs_config() -> dict:
    import oqs  # noqa: WPS433
    cfg = {"liboqs_version": oqs.oqs_version(),
           "liboqs_python_version": oqs.oqs_python_version()}
    root = os.environ.get("OQS_INSTALL_PATH", os.path.expanduser("~/_oqs"))
    hdr = _read(os.path.join(root, "include", "oqs", "oqsconfig.h")) or ""
    defined = [ln.split()[1] for ln in hdr.splitlines() if ln.startswith("#define")]
    cfg["mlkem_x86_64_optimised"] = all(
        f"OQS_ENABLE_KEM_ml_kem_{l}_x86_64" in defined for l in (512, 768, 1024))
    cfg["dist_build_runtime_cpu_dispatch"] = "OQS_DIST_BUILD" in defined
    cfg["uses_openssl_for_symmetric"] = "OQS_USE_OPENSSL" in defined
    commit = _read(os.path.join(root, "LIBOQS_COMMIT"))
    if commit:
        cfg["liboqs_git_commit"] = commit
    return cfg


def collect() -> dict:
    from cryptography.hazmat.backends.openssl.backend import backend
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "platform": {
            "system": platform.system(),
            "kernel": platform.release(),
            "os": _os_release(),
            "machine": platform.machine(),
        },
        "cpu": _cpu(),
        "memory_total_gib": _mem_total_gib(),
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "compiler": platform.python_compiler(),
            "executable": sys.executable,
        },
        "libraries": {
            "cryptography": _pkg("cryptography"),
            "cryptography_openssl": backend.openssl_version_text(),
            "liboqs-python": _pkg("liboqs-python"),
            "numpy": _pkg("numpy"),
            "pandas": _pkg("pandas"),
            "scipy": _pkg("scipy"),
            "matplotlib": _pkg("matplotlib"),
        },
        "liboqs": _liboqs_config(),
        "cpu_microarchitecture_note": (
            "Intel family 6 model 106 = Ice Lake-SP (3rd Gen Xeon Scalable)"
            if _cpu().get("cpu_family") == "6" and _cpu().get("model") == "106" else None),
        "cpu_affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
    }


if __name__ == "__main__":
    # liboqs-python prints a notice on import, so a file, not stdout.
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/environment.json")
    out = ap.parse_args().out
    with open(out, "w") as fh:
        json.dump(collect(), fh, indent=2)
    print(f"environment -> {out}")
