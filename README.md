# GTA VI Twitch CCU forecast

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Kyamii21/gta6-twitch-ccu-forecast-01/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Kyamii21/gta6-twitch-ccu-forecast-01/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

Forecasts how many people watch Grand Theft Auto VI live on Twitch in each
hour of its release day, 2026-11-19 (UTC), as five quantiles an hour
(5%, 25%, 50%, 75%, 95%), from everything recorded up to the end of the
day's first hour, that hour's count included.

Entry for the [make.fun](https://make.fun) competition
`gta6-twitch-ccu-forecast-01`. Run it with `python3 main.py`; it reads every
`*.in` case in `$MAKEFUN_INPUT_DIR` (else `/input`) and writes one
`<id>.out` per case to `$MAKEFUN_OUTPUT_DIR` (else `/output`).
Standard library only, deterministic, no network.

## Method

The forecast is anchored to the case's hour-1 print `p`. Every comparable
past launch in the case ships its release-day hourly curve, so for each
comparable we form the log-ratio curve `log(viewers_h / viewers_1)`. For a
target hour-1 print the launches that matter most are the ones whose own
hour-1 print was close to `p` on the log scale: a launch that opened with
1,000 viewers in hour 1 grows very differently through the day than one
that opened with 800,000 (the small ones explode as regions unlock, the
huge ones are already near their peak). So each hour's log-ratio is
predicted by a Gaussian-kernel weighted mean over the comparables, with
the kernel on `log(hour-1 print)` and a bandwidth of 1.0 in log space.

The spread is the honest cross-launch disagreement: the average of two
views of it — the weighted interquartile range of the same log-ratios,
converted to a normal sigma (IQR / 1.349), and the weighted standard
deviation — shrunk slightly (×0.9), floored at 0.25 and capped at 0.90
in log space, so the bands never claim more precision than the launch
record supports. Quantiles are `p * exp(m + z_tau * s)`.

The typical launch-day shape this recovers: a dip in hours 2–4 (night in
Europe, the US not yet unlocked), jumps at the US East (hour 5) and US
West (hour 8) unlocks, then a climb to an evening peak around hours
19–21, with the peak-to-hour-1 ratio shrinking as the hour-1 print grows
(about 4× for a 20k opening, about 1.2× for a 1M opening).

## Local validation

Scored locally against the four practice launches' release-day counts
(SullyGnome hourly averages, the same source the kit uses):

| forecast | mean pinball loss | typical miss | 90% coverage |
|---|---:|---:|---:|
| this entry | **0.211** | 41% | 0.96 |
| house baseline (hour 1 held flat) | 0.387 | 83% | 0.78 |

Leave-one-out over the 38 comparable launches scores about 0.25, so the
shape is not tuned to the practice cases. The weekday and
pre-midnight-ramp signals were tested and dropped: they helped the
practice cases but hurt leave-one-out, i.e. they were overfitting.

## Files

- `main.py` — the entrypoint: reads the case, writes the forecast
- `LICENSE` — MIT
- `.makefun/owner.json` — payout wallet
