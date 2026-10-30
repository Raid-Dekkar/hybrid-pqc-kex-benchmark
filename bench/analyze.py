"""Aggregate raw per-trial CSVs into summary statistics.

Outputs (results/summary, results/tables):
  timing_summary.csv        per scheme x phase: n, mean, sd, median, IQR, p5, p95,
                            95% bootstrap CI of mean and of median (microseconds)
  run_stability.csv         per-run medians of total time and between-run CV
  hybrid_overhead.csv       Hybrid-L minus ML-KEM-L (median total), bootstrap CI
  communication.csv         wire sizes per scheme
  summary.json              everything above in one file
  tables/*.tex              IEEE-ready tabular environments
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW, SUM, TAB = ROOT / "results/raw", ROOT / "results/summary", ROOT / "results/tables"
PHASES = ["keygen", "encap", "decap", "total"]
ORDER = ["ECDH-X25519", "ML-KEM-512", "Hybrid-X25519+ML-KEM-512", "ML-KEM-768",
         "Hybrid-X25519+ML-KEM-768", "ML-KEM-1024", "Hybrid-X25519+ML-KEM-1024"]
SHORT = {"ECDH-X25519": "X25519 (classical)", "ML-KEM-512": "ML-KEM-512",
         "Hybrid-X25519+ML-KEM-512": "X25519+ML-KEM-512", "ML-KEM-768": "ML-KEM-768",
         "Hybrid-X25519+ML-KEM-768": "X25519+ML-KEM-768", "ML-KEM-1024": "ML-KEM-1024",
         "Hybrid-X25519+ML-KEM-1024": "X25519+ML-KEM-1024"}
B = 10_000
RNG = np.random.default_rng(20261030)


def boot_ci(x: np.ndarray, stat, b: int = B) -> tuple[float, float]:
    idx = RNG.integers(0, len(x), size=(b, len(x)))
    vals = stat(x[idx], axis=1)
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def _trimmed_mean(x: np.ndarray, frac: float) -> float:
    """Mean after discarding the lowest and highest `frac` of observations."""
    xs = np.sort(x)
    k = int(len(xs) * frac)
    return float(xs[k:len(xs) - k].mean())


def load() -> pd.DataFrame:
    files = sorted(RAW.glob("run_*_trials.csv"))
    if not files:
        raise SystemExit("no raw data found; run bench/run_benchmark.py first")
    df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    for p in PHASES:
        df[f"{p}_us"] = df[f"{p}_ns"] / 1000.0
    return df


def timing_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for s in ORDER:
        d = df[df.scheme == s]
        for p in PHASES:
            x = d[f"{p}_us"].to_numpy()
            q1, q3 = np.percentile(x, [25, 75])
            mlo, mhi = boot_ci(x, np.mean)
            dlo, dhi = boot_ci(x, np.median)
            rows.append(dict(scheme=s, phase=p, n=len(x), mean_us=x.mean(),
                             sd_us=x.std(ddof=1), median_us=np.median(x),
                             q1_us=q1, q3_us=q3, iqr_us=q3 - q1,
                             p5_us=np.percentile(x, 5), p95_us=np.percentile(x, 95),
                             min_us=x.min(), max_us=x.max(),
                             mean_ci95_lo=mlo, mean_ci95_hi=mhi,
                             median_ci95_lo=dlo, median_ci95_hi=dhi,
                             cv_pct=100 * x.std(ddof=1) / x.mean(),
                             trimmed_mean_5pct_us=_trimmed_mean(x, 0.05),
                             n_gt_10x_median=int((x > 10 * np.median(x)).sum())))
    return pd.DataFrame(rows)


def run_stability(df: pd.DataFrame) -> pd.DataFrame:
    med = df.groupby(["scheme", "run_id"]).total_us.median().unstack()
    med = med.loc[ORDER]
    out = med.copy()
    out.columns = [f"run_{c:02d}_median_us" for c in out.columns]
    out["mean_of_run_medians_us"] = med.mean(axis=1)
    out["between_run_cv_pct"] = 100 * med.std(axis=1, ddof=1) / med.mean(axis=1)
    return out.reset_index()


def hybrid_overhead(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    ecdh = df[df.scheme == "ECDH-X25519"].total_us.to_numpy()
    for lvl in (512, 768, 1024):
        pq = df[df.scheme == f"ML-KEM-{lvl}"]
        hy = df[df.scheme == f"Hybrid-X25519+ML-KEM-{lvl}"]
        row = dict(level=lvl)
        for p in PHASES:
            a, b = pq[f"{p}_us"].to_numpy(), hy[f"{p}_us"].to_numpy()
            delta = np.median(b) - np.median(a)
            ia = RNG.integers(0, len(a), (B, len(a)))
            ib = RNG.integers(0, len(b), (B, len(b)))
            dist = np.median(b[ib], axis=1) - np.median(a[ia], axis=1)
            row[f"{p}_delta_median_us"] = delta
            row[f"{p}_delta_ci95_lo"] = float(np.percentile(dist, 2.5))
            row[f"{p}_delta_ci95_hi"] = float(np.percentile(dist, 97.5))
        row["total_delta_pct_of_mlkem"] = 100 * row["total_delta_median_us"] / np.median(pq.total_us)
        row["total_delta_vs_ecdh_median_ratio"] = row["total_delta_median_us"] / np.median(ecdh)
        rows.append(row)
    return pd.DataFrame(rows)


def communication(df: pd.DataFrame) -> pd.DataFrame:
    c = df.groupby("scheme")[["pk_bytes", "ct_bytes", "total_bytes"]].agg(["min", "max"])
    assert (c.xs("min", axis=1, level=1) == c.xs("max", axis=1, level=1)).all().all(), \
        "wire sizes must be constant"
    c = c.xs("min", axis=1, level=1).loc[ORDER].reset_index()
    base = int(c.loc[c.scheme == "ECDH-X25519", "total_bytes"].iloc[0])
    c["ratio_vs_ecdh"] = c.total_bytes / base
    c["classical_share_pct"] = np.where(c.scheme.str.startswith("Hybrid"),
                                        100 * 64 / c.total_bytes, np.nan)
    return c


def latex_tables(ts: pd.DataFrame, comm: pd.DataFrame, ho: pd.DataFrame, n: int) -> None:
    TAB.mkdir(parents=True, exist_ok=True)
    piv = ts.pivot(index="scheme", columns="phase", values=["median_us", "iqr_us"]).loc[ORDER]
    lines = [r"\begin{tabular}{|l|c|c|c|c|}", r"\hline",
             r"\textbf{Scheme} & \textbf{KeyGen} & \textbf{Encap} & \textbf{Decap} & \textbf{Total} \\",
             r"\hline"]
    for s in ORDER:
        cells = [f"{piv.loc[s, ('median_us', p)]:.1f} ({piv.loc[s, ('iqr_us', p)]:.1f})" for p in PHASES]
        lines.append(f"{SHORT[s]} & " + " & ".join(cells) + r" \\ \hline")
    lines.append(r"\end{tabular}")
    (TAB / "timing_median_iqr.tex").write_text(
        f"% median (IQR) in microseconds, n={n} measured trials per scheme\n" + "\n".join(lines) + "\n")

    mean = ts[ts.phase == "total"].set_index("scheme").loc[ORDER]
    lines = [r"\begin{tabular}{|l|c|c|c|}", r"\hline",
             r"\textbf{Scheme} & \textbf{Mean [95\% CI]} & \textbf{5\%-trim. mean} & \textbf{P95} \\",
             r"\hline"]
    for s in ORDER:
        r = mean.loc[s]
        lines.append(f"{SHORT[s]} & {r.mean_us:.1f} [{r.mean_ci95_lo:.1f}, {r.mean_ci95_hi:.1f}] & "
                     f"{r.trimmed_mean_5pct_us:.1f} & {r.p95_us:.1f}" + r" \\ \hline")
    lines.append(r"\end{tabular}")
    (TAB / "total_mean_ci.tex").write_text(
        "% total handshake time, microseconds\n" + "\n".join(lines) + "\n")

    lines = [r"\begin{tabular}{|l|c|c|c|c|}", r"\hline",
             r"\textbf{Scheme} & \textbf{Initiator$\rightarrow$} & \textbf{Responder$\rightarrow$} & \textbf{Total} & \textbf{$\times$X25519} \\",
             r" & \textbf{(B)} & \textbf{(B)} & \textbf{(B)} & \\", r"\hline"]
    for _, r in comm.iterrows():
        lines.append(f"{SHORT[r.scheme]} & {r.pk_bytes} & {r.ct_bytes} & {r.total_bytes} & {r.ratio_vs_ecdh:.1f}" + r" \\ \hline")
    lines.append(r"\end{tabular}")
    (TAB / "communication.tex").write_text("\n".join(lines) + "\n")

    lines = [r"\begin{tabular}{|l|c|c|}", r"\hline",
             r"\textbf{Level} & \textbf{$\Delta$ total ($\mu$s) [95\% CI]} & \textbf{$\Delta$ (\%)} \\", r"\hline"]
    for _, r in ho.iterrows():
        lines.append(f"ML-KEM-{int(r.level)} & {r.total_delta_median_us:.1f} "
                     f"[{r.total_delta_ci95_lo:.1f}, {r.total_delta_ci95_hi:.1f}] & "
                     f"{r.total_delta_pct_of_mlkem:.0f}" + r" \\ \hline")
    lines.append(r"\end{tabular}")
    (TAB / "hybrid_overhead.tex").write_text(
        "% hybrid minus ML-KEM-only, difference of medians, bootstrap CI\n" + "\n".join(lines) + "\n")


def main() -> None:
    SUM.mkdir(parents=True, exist_ok=True)
    df = load()
    n = int(df.groupby("scheme").size().min())
    ts, rs, ho, cm = timing_summary(df), run_stability(df), hybrid_overhead(df), communication(df)
    ts.round(3).to_csv(SUM / "timing_summary.csv", index=False)
    rs.round(3).to_csv(SUM / "run_stability.csv", index=False)
    ho.round(3).to_csv(SUM / "hybrid_overhead.csv", index=False)
    cm.round(3).to_csv(SUM / "communication.csv", index=False)
    # order-position effect check (does position within a shuffled trial matter?)
    pos = df.groupby("order_in_trial").total_us.median().round(2).to_dict()
    json.dump({"n_runs": int(df.run_id.nunique()), "trials_per_run": int(df.trial.nunique()),
               "n_per_scheme": n, "bootstrap_resamples": B,
               "timing": ts.round(3).to_dict("records"),
               "run_stability": rs.round(3).to_dict("records"),
               "hybrid_overhead": ho.round(3).to_dict("records"),
               "communication": cm.round(3).to_dict("records"),
               "median_total_us_by_order_position": pos},
              open(SUM / "summary.json", "w"), indent=2)
    latex_tables(ts, cm, ho, n)
    pd.set_option("display.width", 200)
    print(ts[ts.phase == "total"][["scheme", "n", "median_us", "iqr_us", "mean_us",
                                    "trimmed_mean_5pct_us", "p95_us", "n_gt_10x_median"]].round(2).to_string(index=False))
    print(rs.round(2).to_string(index=False))
    print(ho.round(2).to_string(index=False))


if __name__ == "__main__":
    main()
