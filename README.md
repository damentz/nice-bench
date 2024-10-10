# Nice Bench

This Python script simulates a CPU-intensive task and runs multiple processes with varying `nice` levels to measure throughput and latency. The goal is to observe how different `nice` levels (which influence the priority of CPU scheduling in Unix-like systems) affect the execution time of CPU-bound tasks.

## Requirements

- Python 3.x
- Unix-like operating system (Linux, macOS, etc.) that supports `nice` levels.

## Usage

The script accepts two command-line arguments:

1. **`-t, --task-size`**: Defines the size of the CPU task (as a power of 10). Adjust this to simulate varying workloads. Default is 9.
2. **`-n, --nice-duplicates`**: Specifies how many processes to run for each `nice` level. Default is 2.

### Example Usage

To run the script with default parameters:

```bash
sudo python3 nice-bench.py
```

To run the script with custom parameters:

```bash
sudo python3 nice-bench.py -t 10 -n 3
```

Note: Invocation with `sudo` is required to set the `nice` level for the current process.
