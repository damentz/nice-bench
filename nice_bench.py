#!/usr/bin/env python3

from __future__ import annotations
import argparse
import collections
import functools
import json
import logging
import multiprocessing
import os
import resource
import shutil
import statistics
import threading
import time

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

# Constants
SLEEP_NS = 1_000_000
SLEEPS_PER_CPU_SECOND = 100  # One wake-up sample per ~10ms of CPU work
START_LEAD_NS = 100_000_000  # Tasks wake from a timed sleep this long after the barrier
OUTLIER_MADS = 5  # Flag tasks this many median absolute deviations above the median


def calibrate_task_size() -> int:
    """Calibrate task size over one second."""
    task_size = 0
    total = 0
    start_time = time.time()

    while time.time() - start_time < 1:
        task_size += 1
        total += task_size**2

    return task_size


def read_schedstat() -> list[int] | None:
    """Return [cpu_ns, runqueue_wait_ns, timeslices] for this process (Linux only)."""
    try:
        with open("/proc/self/schedstat", encoding="ascii") as f:
            return [int(x) for x in f.read().split()]
    except OSError:
        return None


def read_timer_slack() -> int | None:
    """Return this process's timer slack in nanoseconds (Linux only)."""
    try:
        with open("/proc/self/timerslack_ns", encoding="ascii") as f:
            return int(f.read())
    except OSError:
        return None


def set_timer_slack(ns: int) -> None:
    """Set this process's timer slack; writing to self needs no privileges."""
    with open("/proc/self/timerslack_ns", "w", encoding="ascii") as f:
        f.write(str(ns))


def open_cpu_reader():
    """Return a function giving the CPU this process is running on, or None (Linux only)."""
    try:
        fd = os.open("/proc/self/stat", os.O_RDONLY)
    except OSError:
        return lambda: None
    # Field 39 (processor) is the 37th field after the ")" closing comm
    return lambda: int(os.pread(fd, 1024, 0).rsplit(b")", 1)[1].split()[36])


def set_start_time(start_ns) -> None:
    """Barrier action: pick a common start time shortly in the future."""
    start_ns.value = time.monotonic_ns() + START_LEAD_NS


def cpu_intensive_task(
    task_size: int, sleep_interval: int
) -> tuple[list[int], list[int], list[int | None], bool]:
    """Simulate a CPU-intensive task with periodic sleeps to measure wake-up latency.

    Returns (wake timestamps, wake-up latencies, wake CPUs, interrupted), times in
    nanoseconds.
    """

    total = 0
    wake_ns: list[int] = []
    latency_ns: list[int] = []
    wake_cpu: list[int | None] = []
    current_cpu = open_cpu_reader()

    try:
        for i in range(task_size):
            total += i**2

            if i % sleep_interval == 0:
                sleep_start = time.monotonic_ns()
                time.sleep(SLEEP_NS / 1_000_000_000)
                sleep_end = time.monotonic_ns()
                wake_ns.append(sleep_end)
                latency_ns.append(sleep_end - sleep_start - SLEEP_NS)
                wake_cpu.append(current_cpu())  # Read after timing, costs ~2us
    except KeyboardInterrupt:
        return wake_ns, latency_ns, wake_cpu, True

    return wake_ns, latency_ns, wake_cpu, False


def pct(sorted_values: list, q: float):
    """Nearest-rank percentile of an already sorted list."""
    return sorted_values[min(len(sorted_values) - 1, int(q * len(sorted_values)))]


def measure_task(
    nice_level: int,
    task_size: int,
    sleep_interval: int,
    min_timer_slack: bool,
    barrier,
    start_ns,
    results,
) -> None:
    """Run a task at a specific nice level and send its telemetry to the parent."""
    result: dict = {"nice": nice_level, "pid": os.getpid()}

    try:
        os.setpriority(
            os.PRIO_PROCESS, 0, nice_level
        )  # Absolute, not relative to parent
        if min_timer_slack:
            set_timer_slack(1)  # 0 would mean "reset to default"
    except OSError as e:
        result["error"] = str(e)
        logging.warning(
            f"Could not set up process {result['pid']} with nice level {nice_level}: {e}"
        )

    result["actual_nice"] = os.getpriority(os.PRIO_PROCESS, 0)
    result["timer_slack_ns"] = read_timer_slack()

    try:
        # Waking from the barrier is serialized through its lock, so a starved waker
        # delays everyone behind it. Instead every task arms its own timer for one
        # common start time and the scheduler alone decides who runs first.
        barrier.wait()
        time.sleep(max(0, start_ns.value - time.monotonic_ns()) / 1_000_000_000)
    except (KeyboardInterrupt, threading.BrokenBarrierError):
        result.setdefault("error", "interrupted before start")

    if "error" not in result:
        sched_before = read_schedstat()
        rusage_before = resource.getrusage(resource.RUSAGE_SELF)
        result["start_ns"] = time.monotonic_ns()

        wake_ns, latency_ns, result["wake_cpu"], result["interrupted"] = (
            cpu_intensive_task(task_size, sleep_interval)
        )

        result["end_ns"] = time.monotonic_ns()
        sched_after = read_schedstat()
        rusage_after = resource.getrusage(resource.RUSAGE_SELF)

        result["wake_ns"] = wake_ns
        result["latency_ns"] = latency_ns
        if sched_before and sched_after:
            result["cpu_ns"], result["rq_wait_ns"], result["timeslices"] = (
                a - b for a, b in zip(sched_after, sched_before)
            )
        result["vol_csw"] = rusage_after.ru_nvcsw - rusage_before.ru_nvcsw
        result["invol_csw"] = rusage_after.ru_nivcsw - rusage_before.ru_nivcsw

        duration = (result["end_ns"] - result["start_ns"]) / 1_000_000_000
        lat = sorted(latency_ns) or [0]
        logging.info(
            f"Task completed with nice level {nice_level} in {duration:.2f} "
            f"seconds, with wakeup latency p50/p90/p99 of "
            f"{pct(lat, 0.5) / 1000:.2f} / {pct(lat, 0.9) / 1000:.2f} / "
            f"{pct(lat, 0.99) / 1000:.2f} microseconds"
        )

    results.put(result)


def outlier_threshold(values: list[float]) -> float:
    """Median + OUTLIER_MADS * median absolute deviation."""
    med = statistics.median(values)
    mad = statistics.median(abs(v - med) for v in values)
    return med + OUTLIER_MADS * mad if mad else float("inf")


def order_stats(tasks: list[dict]) -> tuple[float, int, tuple | None, dict]:
    """Kendall tau-a of finish order vs nice order, ignoring same-nice pairs.

    Returns (tau, inversions, worst inversion as (gap_s, lower_nice_task, higher_nice_task),
    {nice distance: (inversions, pairs)}).
    Tau is 1.0 when every lower nice level finished before every higher one.
    """
    concordant = discordant = 0
    worst: tuple = (0.0, None, None)
    pairs_by_distance: collections.Counter = collections.Counter()
    inversions_by_distance: collections.Counter = collections.Counter()

    # ponytail: O(n^2) pair scan, fine for hundreds of tasks
    for i, a in enumerate(tasks):
        for b in tasks[i + 1 :]:
            if a["nice"] == b["nice"]:
                continue
            lo, hi = (a, b) if a["nice"] < b["nice"] else (b, a)
            gap = lo["finish_s"] - hi["finish_s"]  # > 0: higher priority finished later
            distance = hi["nice"] - lo["nice"]
            pairs_by_distance[distance] += 1
            if gap > 0:
                discordant += 1
                inversions_by_distance[distance] += 1
                if gap > worst[0]:
                    worst = (gap, lo, hi)
            else:
                concordant += 1

    pairs = concordant + discordant
    tau = (concordant - discordant) / pairs if pairs else 1.0
    by_distance = {
        d: (inversions_by_distance[d], pairs_by_distance[d])
        for d in sorted(pairs_by_distance)
    }
    return tau, discordant, worst if discordant else None, by_distance


def fmt(value, spec: str) -> str:
    """Format a possibly missing value."""
    return "-" if value is None else format(value, spec)


def report(tasks: list[dict]) -> None:
    """Print a per-task table with a finish-time timeline, ordering and latency summary."""
    done = sorted(
        (t for t in tasks if "error" not in t), key=lambda t: (t["nice"], t["pid"])
    )
    skipped = len(tasks) - len(done)
    if skipped:
        logging.warning(
            f"{skipped} tasks failed to start and are excluded from the report"
        )
    if not done:
        return

    for rank, t in enumerate(sorted(done, key=lambda t: t["finish_s"]), 1):
        t["rank"] = rank
        lat = sorted(t["latency_ns"])
        t["lat_us"] = (
            {
                "p50": pct(lat, 0.5) / 1000,
                "p90": pct(lat, 0.9) / 1000,
                "p99": pct(lat, 0.99) / 1000,
                "max": lat[-1] / 1000,
            }
            if lat
            else None
        )

    with_lat = [t for t in done if t["lat_us"]]
    p99_limit = (
        outlier_threshold([t["lat_us"]["p99"] for t in with_lat]) if with_lat else 0
    )
    max_limit = (
        outlier_threshold([t["lat_us"]["max"] for t in with_lat]) if with_lat else 0
    )

    header = (
        f"{'nice':>4} {'pid':>7} {'finish(s)':>9} {'rank':>4} {'cpu(s)':>7} "
        f"{'rq_wait(s)':>10} {'invol_csw':>9} {'lat p50/p90/p99/max (us)':>29}    "
    )
    bar_width = max(10, shutil.get_terminal_size().columns - len(header) - 1)
    longest = max(t["finish_s"] for t in done) or 1

    print()
    print(header + "timeline")
    for t in done:
        lat = t["lat_us"]
        flag = (
            "!!" if lat and (lat["p99"] > p99_limit or lat["max"] > max_limit) else ""
        )
        cpu = t["cpu_ns"] / 1e9 if "cpu_ns" in t else None
        rq_wait = t["rq_wait_ns"] / 1e9 if "rq_wait_ns" in t else None
        lat_col = " / ".join(f"{v:.0f}" for v in lat.values()) if lat else "-"
        bar = "█" * max(1, round(t["finish_s"] / longest * bar_width))
        print(
            f"{t['nice']:>4} {t['pid']:>7} {t['finish_s']:>9.2f} {t['rank']:>4} "
            f"{fmt(cpu, '.2f'):>7} {fmt(rq_wait, '.2f'):>10} {t['invol_csw']:>9} "
            f"{lat_col:>29} {flag:<2} {bar}"
        )

    tau, inversions, worst, by_distance = order_stats(done)
    print(
        f"\nOrder agreement: Kendall tau = {tau:.3f}, {inversions} inversions", end=""
    )
    if worst:
        gap, lo, hi = worst
        print(
            f" (worst: nice {hi['nice']} pid {hi['pid']} finished {gap:.2f}s before "
            f"nice {lo['nice']} pid {lo['pid']})"
        )
    else:
        print()
    inverted = {d: v for d, v in by_distance.items() if v[0]}
    if inverted:
        print(
            "Inversions by nice distance: "
            + ", ".join(f"{d}: {inv}/{pairs}" for d, (inv, pairs) in inverted.items())
            + f" pairs; none beyond distance {max(inverted)}"
        )

    samples = [
        (lat, t, w) for t in done for lat, w in zip(t["latency_ns"], t["wake_s"])
    ]
    if samples:
        all_lat = sorted(s[0] for s in samples)
        lat, t, when = max(samples, key=lambda s: s[0])
        print(
            f"Wake-up latency over {len(all_lat)} samples: p50 {pct(all_lat, 0.5) / 1000:.0f}us, "
            f"p90 {pct(all_lat, 0.9) / 1000:.0f}us, "
            f"p99 {pct(all_lat, 0.99) / 1000:.0f}us, p99.9 {pct(all_lat, 0.999) / 1000:.0f}us, "
            f"max {lat / 1000:.0f}us (nice {t['nice']} pid {t['pid']} at {when:.2f}s)"
        )
    if with_lat:
        print(f"!! = p99 above {p99_limit:.0f}us or max above {max_limit:.0f}us")


def run_experiment(
    task_size: int, nice_levels: list[int], min_timer_slack: bool, output: str
) -> None:
    """Run the experiment launching processes with given task size and nice levels."""

    task_multiplier = calibrate_task_size()
    sleep_interval = max(1, task_multiplier // SLEEPS_PER_CPU_SECOND)
    logging.info(
        f"Calibrated task size: {task_multiplier}, sleeping every {sleep_interval}"
    )

    start_ns = multiprocessing.Value("q", 0, lock=False)
    barrier = multiprocessing.Barrier(
        len(nice_levels) + 1, action=functools.partial(set_start_time, start_ns)
    )
    results: multiprocessing.Queue = multiprocessing.Queue()
    processes = [
        multiprocessing.Process(
            target=measure_task,
            args=(
                nice_level,
                task_size * task_multiplier,
                sleep_interval,
                min_timer_slack,
                barrier,
                start_ns,
                results,
            ),
        )
        for nice_level in nice_levels
    ]

    for p in processes:
        p.start()

    logging.info(f"System has {os.cpu_count()} CPUs")
    logging.info(f"Launched {len(processes)} processes with nice levels: {nice_levels}")
    logging.info(
        f"Running task with size {task_size}. Press Ctrl+C to stop the experiment"
    )

    try:
        barrier.wait()
    except KeyboardInterrupt:
        barrier.abort()
        start_ns.value = start_ns.value or time.monotonic_ns()
    started = time.time() + (start_ns.value - time.monotonic_ns()) / 1_000_000_000

    # Drain the queue before joining, or children block flushing large results
    tasks: list[dict] = []
    while len(tasks) < len(processes):
        try:
            tasks.append(results.get())
        except KeyboardInterrupt:
            logging.info("Experiment interrupted, collecting partial results")
    for p in processes:
        p.join()

    total_duration = (time.monotonic_ns() - start_ns.value) / 1_000_000_000
    logging.info(f"All tasks completed in {total_duration:.2f} seconds")

    # Make all times relative to the common start
    for t in tasks:
        if "start_ns" in t:
            t["start_skew_s"] = (t.pop("start_ns") - start_ns.value) / 1_000_000_000
            t["finish_s"] = (t.pop("end_ns") - start_ns.value) / 1_000_000_000
            t["wake_s"] = [
                (w - start_ns.value) / 1_000_000_000 for w in t.pop("wake_ns")
            ]

    report(tasks)

    meta = {
        "started": started,
        "kernel": os.uname().release,
        "cpu_count": os.cpu_count(),
        "task_size": task_size,
        "task_multiplier": task_multiplier,
        "sleep_interval": sleep_interval,
        "sleep_ns": SLEEP_NS,
        "min_timer_slack": min_timer_slack,
        "nice_levels": nice_levels,
        "total_s": total_duration,
    }
    with open(output, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "tasks": tasks}, f)
    logging.info(f"Wrote telemetry to {output}")


def process_args():
    """Process command-line arguments for task size and nice level duplicates."""
    parser = argparse.ArgumentParser(
        description="Run a CPU-intensive task with varying nice levels."
    )
    parser.add_argument(
        "-t",
        "--task-size",
        type=int,
        default=9,
        help="CPU work per task, in calibrated seconds of single-core work",
    )
    parser.add_argument(
        "-n",
        "--nice-duplicates",
        type=int,
        default=2,
        help="Number of processes to run per nice level",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=time.strftime("nice-bench-%Y%m%d-%H%M%S.json"),
        help="Telemetry JSON output path",
    )
    parser.add_argument(
        "--default-timer-slack",
        action="store_true",
        help="Keep the kernel's default timer slack (usually 50us) instead of 1ns, "
        "so wake-up latency includes it like normal applications see",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = process_args()
    logging.info("Starting experiment...")

    nice_levels = [i for i in range(19, -21, -1) for _ in range(args.nice_duplicates)]
    run_experiment(
        args.task_size, nice_levels, not args.default_timer_slack, args.output
    )
