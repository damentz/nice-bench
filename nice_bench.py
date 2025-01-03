#!/usr/bin/env python3

from __future__ import annotations
import os
import time
import multiprocessing
import argparse
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

# Constants
SLEEP_INTERVAL = 1000
SLEEP_DURATION = 0.001


def calibrate_task_size() -> int:
    """Calibrate task size over one second."""
    task_size = 0
    total = 0
    start_time = time.time()

    while time.time() - start_time < 1:
        task_size += 1
        total += task_size**2

    return task_size


def cpu_intensive_task(task_size: int) -> float:
    """Simulate a CPU-intensive task with periodic sleeps to measure wake-up latency."""

    total = 0
    wakeup_total = 0
    sleep_count = 0

    try:
        time.sleep(0.1)  # Allow time for other processes to start
        for i in range(task_size):
            total += i**2

            if sleep_count % SLEEP_INTERVAL == 0:
                sleep_start = time.monotonic_ns()
                time.sleep(SLEEP_DURATION)
                sleep_end = time.monotonic_ns()
                wakeup_total += (
                    sleep_end - sleep_start - (SLEEP_DURATION * 1_000_000_000)
                )
                sleep_count += 1
    except KeyboardInterrupt:
        pass

    return wakeup_total / sleep_count if sleep_count > 0 else float(0)


def measure_task(nice_level: int, task_size: int) -> float:
    """Measure throughput and duration of a task with a specific nice level."""
    start_time = time.time()
    pid = os.getpid()

    try:
        os.nice(nice_level)  # Apply nice level to current process
    except PermissionError:
        logging.warning(
            f"Permission denied for process {pid} with nice level {nice_level}, skipping"
        )
        return 0

    wakeup_latency_us = cpu_intensive_task(task_size) / 1000

    duration = time.time() - start_time
    logging.info(
        f"Task completed with nice level {nice_level} in {duration:.2f} "
        f"seconds, with wakeup latency of {wakeup_latency_us:.2f} microseconds"
    )

    return duration


def run_experiment(task_size: int, nice_levels: list[int]) -> None:
    """Run the experiment launching processes with given task size and nice levels."""

    task_multiplier = calibrate_task_size()
    logging.info(f"Calibrated task size: {task_multiplier}")

    processes = []

    for nice_level in nice_levels:
        p = multiprocessing.Process(
            target=measure_task, args=(nice_level, task_size * task_multiplier)
        )
        processes.append(p)

    for p in processes:
        p.start()

    start_time = time.time()

    logging.info(f"System has {os.cpu_count()} CPUs")
    logging.info(f"Launched {len(processes)} processes with nice levels: {nice_levels}")
    logging.info(
        f"Running task with size {task_size}. Press Ctrl+C to stop the experiment"
    )

    try:
        for p in processes:
            p.join()

        total_duration = time.time() - start_time
        logging.info(f"All tasks completed in {total_duration:.2f} seconds")
    except KeyboardInterrupt:
        logging.info(
            "Experiment interrupted, all tasks stopped after"
            f"{time.time() - start_time:.2f} seconds"
        )


def process_args():
    """Process command-line arguments for task size and nice level duplicates."""
    parser = argparse.ArgumentParser(
        description="Run a CPU-intensive task with varying nice levels."
    )
    parser.add_argument(
        "-t", "--task-size", type=int, default=9, help="Size of the CPU task"
    )
    parser.add_argument(
        "-n",
        "--nice-duplicates",
        type=int,
        default=2,
        help="Number of processes to run per nice level",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = process_args()
    logging.info("Starting experiment...")

    nice_levels = [i for i in range(20, -20, -1) for _ in range(args.nice_duplicates)]
    run_experiment(args.task_size, nice_levels)
