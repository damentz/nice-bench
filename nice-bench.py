#!/usr/bin/env python3

import os
import time
import multiprocessing
import argparse

# Function to simulate CPU-intensive task
def cpu_intensive_task(n):
    total = 0
    wakeup_total = 0
    sleep_duration = 0.001
    sleep_count = 0
    for i in range(n):
        total += i ** 2

        if sleep_count % 1000 == 0:
            sleep_start = time.time()
            time.sleep(sleep_duration)
            sleep_end = time.time()
            wakeup_total += sleep_end - sleep_start - sleep_duration
            sleep_count += 1

    return wakeup_total / sleep_count

# Function to measure throughput and latency
def measure_task(nice_level, task_size):
    start_time = time.time()

    # Set the nice level for the current process
    pid = os.getpid()
    os.nice(nice_level)  # Apply nice level to current process

    print(f"Process {pid} running with nice level: {nice_level}")

    # Run the task
    wakeup_latency_us = cpu_intensive_task(task_size) * 1000000

    end_time = time.time()

    latency = end_time - start_time
    print(f"Task completed with nice level {nice_level} in {latency:.2f} seconds, with wakeup latency of {wakeup_latency_us:.2f} microseconds")

    return latency

# Main function to run the experiment
def run_experiment(task_size, nice_levels):
    processes = []

    for i in range(len(nice_levels)):
        nice_level = nice_levels[i % len(nice_levels)]  # Cycle through the nice levels
        p = multiprocessing.Process(target=measure_task, args=(nice_level, task_size))
        processes.append(p)

    # Start all processes
    for p in processes:
        p.start()

    time.sleep(1)  # Wait for all processes to start

    print()
    print(f"System has {os.cpu_count()} CPUs")
    print(f"Launched {len(processes)} processes with nice levels: {nice_levels}")
    print(f"Running task with size {task_size}")
    print(f"Press Ctrl+C to stop the experiment")
    print()

    # Ensure all processes complete
    for p in processes:
        p.join()

    print("All tasks completed.")


def process_args():
    parser = argparse.ArgumentParser(description="Run a CPU-intensive task with varying nice levels.")
    parser.add_argument("-t", "--task-size", type=int, default=9, help="Size of the CPU task (adjust to simulate workload)")
    parser.add_argument("-n", "--nice-duplicates", type=int, default=2, help="Number of processes to run per nice level")
    return parser.parse_args()


if __name__ == "__main__":
    args = process_args()

    print("Starting experiment...")

    nice_levels = []
    for i in range(-20, 20):
        for y in range(args.nice_duplicates):
            nice_levels.append(i)

    # Run the experiment
    run_experiment(10**args.task_size, nice_levels)
