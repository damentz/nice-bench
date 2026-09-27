from nice_bench import order_stats, outlier_threshold


def task(nice, finish_s):
    return {"nice": nice, "pid": nice, "finish_s": finish_s}


# Perfect order, duplicates of a nice level are ignored
assert order_stats([task(-1, 1.0), task(0, 2.0), task(0, 1.5), task(1, 3.0)]) == (
    1.0,
    0,
    None,
    {1: (0, 4), 2: (0, 1)},
)

# One swapped pair: nice 1 finished 0.5s before nice 0
tau, inversions, worst, by_distance = order_stats(
    [task(-1, 1.0), task(0, 3.0), task(1, 2.5)]
)
assert by_distance == {1: (1, 2), 2: (0, 1)}
assert inversions == 1 and abs(tau - 1 / 3) < 1e-9
assert worst[1]["nice"] == 0 and worst[2]["nice"] == 1 and abs(worst[0] - 0.5) < 1e-9

assert outlier_threshold([10, 11, 12, 13, 1000]) == 12 + 5 * 1
assert outlier_threshold([5, 5, 5]) == float("inf")
print("ok")
