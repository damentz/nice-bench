# Nice Bench

This Python script benchmarks how different nice levels affect CPU-bound tasks, measuring throughput and latency. It runs processes with varying nice levels to observe their impact on execution time.

## Requirements

- Python 3.x
- A Unix-like OS with nice support (e.g., Linux, macOS)

## Usage

Command-line arguments:

1. **`-t, --task-size`**: Sets the task size as a power of 10 (default: 9).
2. **`-n, --nice-duplicates`**: Number of processes per nice level (default: 2).

### Example Usage

Default run:

```bash
sudo python3 nice-bench.py
```

Custom run without duplicate processes and reduced task size:

```bash
sudo python3 nice-bench.py -t 7 -n 1
```

Note: Invocation with `sudo` is required to set nice level for restricted nice levels.
