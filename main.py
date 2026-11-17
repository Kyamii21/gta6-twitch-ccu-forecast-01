#!/usr/bin/env python3
"""Forecast GTA VI launch-day Twitch viewers, hour by hour.

Reads every ``*.in`` case file (schema ``makefun/twitch-ccu-case/v1``) in the
input directory and writes one ``<id>.out`` forecast per case to the output
directory: for each of hours 2..24, five quantiles (5%, 25%, 50%, 75%, 95%)
of that hour's concurrent-viewer count.

Method
------
The forecast is anchored to the case's hour-1 print ``p``.  Every comparable
past launch in the case ships its release-day hourly curve, so for each
comparable we form the log-ratio curve ``log(viewers_h / viewers_1)``.  For a
target hour-1 print ``p`` the launches that matter most are the ones whose
own hour-1 print was close to ``p`` on the log scale: a launch that opened
with 1,000 viewers in hour 1 grows very differently through the day than
one that opened with 800,000 (the small ones explode as regions unlock, the
huge ones are already near their peak).  So each hour's log-ratio is
predicted by a Gaussian-kernel weighted mean over the comparables, with the
kernel on ``log(hour-1 print)`` and a bandwidth of 1.0 in log space.

The spread is the honest cross-launch disagreement: the average of two
views of it -- the weighted interquartile range of the same log-ratios,
converted to a normal sigma (IQR / 1.349), and the weighted standard
deviation -- shrunk slightly (x0.9), and floored at 0.25 / capped at 0.90
in log space so the bands never claim more precision than the launch
record supports.  Quantiles are ``p * exp(m + z_tau * s)`` with the
standard normal quantiles at the five levels.

On the four practice launches this scores a mean pinball loss of about
0.21 (typical miss about 40%), against about 0.39 for the house baseline
that holds hour 1 flat.  A leave-one-out run over the comparable launches
scores about 0.25, so the shape is not tuned to the practice cases.

Standard library only, deterministic, no network, no clock, no randomness.
"""

import json
import math
import os
import sys
from datetime import datetime

# Standard normal quantiles at the five levels 0.05, 0.25, 0.5, 0.75, 0.95.
Z_SCORES = (-1.6448536269514722, -0.6744897501960817, 0.0,
            0.6744897501960817, 1.6448536269514722)

# Kernel bandwidth on log(hour-1 viewers): launches within about one
# order of magnitude of the target's hour-1 print dominate the average.
BANDWIDTH = 1.0
# Spread calibration: IQR-based sigma, shrunk a little, then floored/capped.
SPREAD_MULT = 0.9
SPREAD_FLOOR = 0.25
SPREAD_CAP = 0.90
# Fallback spread (house baseline's shape) when no comparable covers an hour.
FALLBACK_SPREAD_RATE = 0.15

MAX_VIEWERS = 1_000_000_000.0
MIN_VIEWERS = 0.01


def parse_time(text):
    """Parse an ISO-8601 UTC timestamp such as 2026-11-19T00:00:00Z."""
    if text.endswith("Z"):
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    return datetime.fromisoformat(text)


def hour_of(point_time, day_start):
    """UTC release-day hour (1..24) of a timestamp, or None outside the day."""
    delta = (point_time - day_start).total_seconds()
    hour = int(delta // 3600) + 1
    if 1 <= hour <= 24:
        return hour
    return None


def release_day_curve(comparable):
    """One comparable's release-day curve as {hour: viewers}.

    Returns None when the curve is unusable: no positive hour-1 print, or
    fewer than 12 of the 24 hours present (sparse categories are sampled
    too rarely to trust their shape).
    """
    try:
        day_start = parse_time(comparable["day_start"])
    except (KeyError, TypeError, ValueError):
        return None
    curve = {}
    for point in comparable.get("hourly") or []:
        viewers = point.get("viewers")
        if viewers is None or viewers <= 0:
            continue
        try:
            hour = hour_of(parse_time(point["from"]), day_start)
        except (KeyError, TypeError, ValueError):
            continue
        if hour is not None:
            curve[hour] = float(viewers)
    if 1 not in curve or len(curve) < 12:
        return None
    return curve


def weighted_mean(pairs):
    """Mean of [(value, weight)], or None when the total weight is zero."""
    total = sum(w for _, w in pairs)
    if total <= 0:
        return None
    return sum(v * w for v, w in pairs) / total


def weighted_std(pairs, mean):
    """Weighted standard deviation of [(value, weight)] around ``mean``."""
    total = sum(w for _, w in pairs)
    if total <= 0:
        return None
    variance = sum(w * (v - mean) ** 2 for v, w in pairs) / total
    return math.sqrt(variance)


def weighted_quantile(pairs, tau):
    """Weighted quantile of [(value, weight)] at level tau."""
    ordered = sorted(pairs)
    total = sum(w for _, w in ordered)
    if total <= 0:
        return None
    cutoff = tau * total
    running = 0.0
    for value, weight in ordered:
        running += weight
        if running >= cutoff:
            return value
    return ordered[-1][0]


def hour1_print(case):
    """The case's hour-1 print, with fallbacks if it is missing or zero."""
    known = case.get("known") or []
    for row in known:
        viewers = row.get("viewers")
        if viewers is not None and viewers > 0:
            return float(viewers)
    for source in (case.get("history_hourly"), case.get("history")):
        for row in reversed(source or []):
            viewers = row.get("viewers")
            if viewers is not None and viewers > 0:
                return float(viewers)
    return 1.0


def forecast_case(case):
    """Return the {"hours": [...]} forecast object for one case."""
    p = max(hour1_print(case), 1.0)
    log_p = math.log(p)

    curves = []
    for comparable in case.get("comparables") or []:
        curve = release_day_curve(comparable)
        if curve is not None:
            curves.append(curve)
    curves.sort(key=lambda c: c[1])

    hours = []
    for hour in range(2, 25):
        pairs = []
        for curve in curves:
            if hour in curve:
                log_ratio = math.log(curve[hour] / curve[1])
                weight = math.exp(
                    -0.5 * ((math.log(curve[1]) - log_p) / BANDWIDTH) ** 2
                )
                pairs.append((log_ratio, weight))
        if pairs:
            centre = weighted_mean(pairs)
            lower = weighted_quantile(pairs, 0.25)
            upper = weighted_quantile(pairs, 0.75)
            std = weighted_std(pairs, centre)
            if centre is None or lower is None or upper is None or std is None:
                spread = FALLBACK_SPREAD_RATE * math.sqrt(hour - 1)
                centre = 0.0
            else:
                # Two views of the same disagreement: the robust IQR and
                # the plain weighted spread.  The kernel leaves only a
                # handful of launches with real weight, so either one
                # alone is noisy; their average is steadier, and on both
                # the practice launches and leave-one-out over the
                # comparables it scores a little better than either alone.
                iqr_sigma = (upper - lower) / 1.349
                spread = (iqr_sigma + std) / 2 * SPREAD_MULT
                spread = min(max(spread, SPREAD_FLOOR), SPREAD_CAP)
        else:
            # No comparable covers this hour: hold hour 1 flat, widening.
            centre = 0.0
            spread = FALLBACK_SPREAD_RATE * math.sqrt(hour - 1)
        quantiles = []
        previous = 0.0
        for z in Z_SCORES:
            q = p * math.exp(centre + z * spread)
            q = round(min(max(q, MIN_VIEWERS), MAX_VIEWERS), 2)
            q = max(q, previous)
            quantiles.append(q)
            previous = q
        hours.append({"hour": hour, "q": quantiles})
    return {"hours": hours}


def main(argv=None):
    input_dir = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
    output_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(output_dir, exist_ok=True)
    case_files = sorted(
        name for name in os.listdir(input_dir) if name.endswith(".in")
    )
    for name in case_files:
        case_id = name[: -len(".in")]
        with open(os.path.join(input_dir, name), "r", encoding="utf-8") as fh:
            case = json.load(fh)
        forecast = forecast_case(case)
        out_path = os.path.join(output_dir, case_id + ".out")
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(forecast, fh, separators=(",", ":"))
            fh.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
