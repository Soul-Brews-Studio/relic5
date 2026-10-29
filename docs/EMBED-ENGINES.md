# Embed engines compared: m5 (ANE + GPU) vs gb300

Measured 2026-10-29 on m5 (Apple M5 Max) and gb300 (NVIDIA GB300). The model is embeddinggemma-300m
(`unsloth--embeddinggemma-300m@806f5f90`). The texts are 2,252 real chunks the hub was missing that morning (median
356 characters). The "×9" rows are the same chunks nine times over (20,268), to see how each engine scales.

## Answer

| backlog | fastest | why |
|---|---|---|
| up to ~2,500 chunks (a day's increment) | `ane2` on m5 | as fast as gb300 end to end, no network, the text stays on m5 |
| more than ~2,500 | `gb300` | 4× faster at 20k; its fixed cost (ssh, upload, model load) is spread over more texts |

The `auto` policy follows this: `backlog_gb300 = 2500` in `worker.py` (it was 50,000).

## Speed (texts/s)

| engine | 2,252 chunks | 20,268 chunks | what is timed |
|---|---|---|---|
| `mps`-style GPU alone, m5 | 83.7 | | model loaded, encode only |
| ANE alone, m5 (ANEEmbedBar packages) | 99.1 | | model loaded, encode only |
| `ane2` split, ANE share 0.7, m5 | 150.7 (151.6 / 151.9 / 151.1 earlier) | 146.2 | model loaded, encode only |
| `gb300` through `relic5 embed --engine gb300` | 151.4 | 620.0 | end to end: ssh, upload, model load, encode, rsync back |
| gb300 with the model already loaded | 280.7 / 368.4 | 654.9 / 743.9 | encode only, two runs each |

- **gb300 against the m5.** With the model already loaded, gb300's GPU is 2.4–5× faster. Through relic5's real path it also reloads the model on every call, which makes it a tie at 2,252 chunks.
- **ane2's ANE share.** Ten split runs were measured: 0.3 gave 134.6; 0.5 gave 101.0 / 137.3 / 191.9; 0.6 gave 174.6 / 137.9; 0.7 gave 151.6 / 151.9 / 151.1; 0.8 gave 131.5 / 132.1. 0.7 has the best mean and is the steadiest, so it is the default (`RELIC5_ANE2_SHARE` overrides it).

## Same vectors?

| comparison | n | min | p05 | mean |
|---|---|---|---|---|
| `ane2` split vs the hub's stored vectors (made on gb300) | 140 | 0.9979 | 0.9984 | 0.9995 |
| `ane2` ANE share alone vs stored | 140 | 0.9974 | 0.9980 | 0.9990 |
| `ane2` GPU share alone vs stored | 140 | 0.9949 | 0.9999 | 0.9999 |
| `ane2` vs `gb300` on the 2,252 chunks | 2,252 | 0.9972 | 0.9984 | 0.9992 |
| `relic5 embed --probe --engine ane2` on merged main | 68 | 0.9971 | 0.9974 | |
| `relic5 embed --probe --engine mps` on merged main | 68 | | 0.9982 | |

Every engine clears the parity gate (p05 > 0.99), so all of them write into the same `model@hash`.

## Things found on the way

- **Plain Gemma does not run in float16.** The residual stream peaks at 161,809 in layer 23, above float16's maximum of 65,504. In float16 all 152 test texts came out NaN.
- **An exact fp16 fix works on CPU and GPU but not on the ANE.**
  - The fix runs the residual stream at 1/16 and pre-scales each RMSNorm by its input's max, with eps scaled to match. In float16 on CPU and GPU that gives cos p05 0.99965.
  - On the ANE hardware the same graph reached only p05 0.9886. Rescale size, the norm patch and where pooling runs were each ruled out.
  - ANEEmbedBar's ANE-native graph (1×1 conv, per-head einsum) gives p05 0.99928 on the same texts, so `ane2` loads those packages.
- **`--engine gb300` had never completed.** relic4 rsyncs each shard into `RELIC4_ROOT/vec/_cache/<model@hash>/`, and relic5 never created that folder, so every run failed at the rsync after gb300 had done the work. Fixed in #265.

## Reproduce

```
relic5 embed --probe --engine ane2          # parity against stored vectors (reads the hub only)
relic5 embed --engine ane2 --limit 5000     # m5: ANE + GPU, ANE share 0.7
relic5 embed --engine gb300                 # gb300 over ssh
```

PRs: #259 (engine `ane2`), #265 (gb300 fix), and this one (policy threshold + this report).
