#!/usr/bin/env bash
# Full pipeline: tests -> 5 independent benchmark runs -> statistics -> figures.
# Usage: scripts/run_all.sh [RUNS] [TRIALS] [WARMUP] [CPU]
set -euo pipefail
cd "$(dirname "$0")/.."
RUNS="${1:-5}"; TRIALS="${2:-200}"; WARMUP="${3:-50}"; CPU="${4:-1}"
export OQS_INSTALL_PATH="${OQS_INSTALL_PATH:-$HOME/_oqs}"
export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}"
PIN=""; command -v taskset >/dev/null && PIN="taskset -c $CPU"

python -m pytest -q tests
rm -f results/raw/run_*_trials.csv results/raw/run_*_environment.json
for i in $(seq 1 "$RUNS"); do
  $PIN python bench/run_benchmark.py --run-id "$i" --trials "$TRIALS" --warmup "$WARMUP"
done
python bench/analyze.py
python bench/plot.py
python bench/env_info.py --out results/environment.json
pip freeze > results/pip_freeze.txt
