# Nice Bench

This Python script benchmarks how different nice levels affect CPU-bound tasks, measuring throughput and latency. It runs processes with varying nice levels to observe their impact on execution time.

## Requirements

- Python 3.x
- A Unix-like OS with nice support (e.g., Linux, macOS)

## Usage

Command-line arguments:

1. **`-t, --task-size`**: CPU work per task, in calibrated seconds of single-core work (default: 9).
2. **`-n, --nice-duplicates`**: Number of processes per nice level (default: 2).
3. **`-o, --output`**: Telemetry JSON path (default: `nice-bench-<timestamp>.json`).
4. **`--default-timer-slack`**: Keep the kernel's default timer slack (usually 50us). By default tasks set it to 1ns so wake-up latency reflects scheduling rather than slack.

### Output

All tasks wait at a barrier, then wake from a timed sleep at one common start time, so the scheduler alone decides who runs first. Each task sleeps 1ms per ~10ms of CPU work to sample wake-up latency. At the end a table shows, per task: finish time and rank, CPU time and runqueue wait (from `/proc/self/schedstat`), involuntary context switches, latency p50/p90/p99/max, and a finish-time timeline. `!!` marks latency outliers (more than 5 median absolute deviations above the median).

The summary reports how well finish order follows nice order (Kendall tau, 1.0 = perfect), the number of inversions and the worst one, inversions broken down by nice distance (to tell equal-priority coin flips from real misordering), and the latency extremes across all samples.

The JSON file holds run metadata and every task's telemetry, including each wake-up sample's timestamp, latency and CPU, for offline analysis.

### Example Usage

Default run:

```bash
sudo python3 nice_bench.py
```

Custom run without duplicate processes and reduced task size:

```bash
sudo python3 nice_bench.py -t 7 -n 1
```

Note: Invocation with `sudo` is required to set nice level for restricted nice levels.
