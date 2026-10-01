# Milestone commit audit

Frozen checkpoint: `7d08e01` (October 1, 2026). Counts intentionally exclude subsequent audit/recovery documentation so the snapshot stays reproducible.

| Scope | Non-merge commits | Singapore author-date span |
| --- | ---: | --- |
| M1: runner and nominal baseline | 13 | September 12–13 |
| M2: occlusion search and failure confirmation | 38 | September 13–16 |
| M3: HPC, containment, recovery, adaptive loop and portfolio | 132 | September 27–October 1 |
| M4: bounded counterexample reduction | 17 | September 21–27 |
| M5 viewer | 19 | Separate from M1–M4 |
| Other product/submission work | 5 | Separate from M1–M4 |
| Shared setup, CI, governance and cross-cutting work | 31 | Separate from M1–M4 |

The 255 non-merge commits plus five merge commits account for all 260 reachable commits at this checkpoint. An independent scope audit classified by explicit milestone labels/dedicated paths, then subjects and changed files; root independently verified complete SHA coverage, uniqueness and bucket totals. These are audited scope-attribution counts, not native Git milestone metadata or hours worked.

M3 is 66% of the 200 commits attributed to M1–M4, or about 52% of all non-merge commits. It genuinely has more recorded engineering work, but frequent small conventional commits inflate counts relative to larger batches. Its scope includes fixed replay throughput, process containment, durable ownership, watchdogs, interruption recovery, adaptive diagnostic flows, portfolio scheduling, task selection, and infrastructure attempts. Counts cannot show that the time was wasted or estimate active hours. Author-date spans include gaps/waits and are not durations of continuous work.

Seven M3 assignments require explicit manual rationale: `8176ca7 2ad7677 096f6a1 fd773dc 46d6ef4` implement/check the M3 pilot watchdog and teardown; `a9cc776 f0d7c34` implement portfolio task selection/configuration. M1 includes `1b62407 2090554 ba4f77f` because their LIBERO changes establish the nominal runner, not perturbation search. Viewer and generic setup work were not forced into M1–M4.

## Reproduction

Run `git rev-list --count 7d08e01` (260), `git rev-list --count --no-merges 7d08e01` (255), and `git log 7d08e01 --no-merges --format='%h|%aI|%s' --name-only`. Every author timestamp in the audit uses +08:00. The exclusive abbreviated-SHA partition below defines the exact classification; reassignment should be explicit rather than silently changing counts.

## Exclusive SHA partition

### M1

```text
0f9dd74 ce376aa 341a6ff 25abd09 5966098 b5a02dc a76e745 1b62407 2090554 fe079b6
0423dfa ba4f77f 80122e5
```

### M2

```text
bb7be0d 05a4944 7c737d8 d4f45dc c384c97 f073133 becbde1 30bf3a4 b055562 a703590
8d2e6ce 7747227 d884e33 2c5cbf9 c8fbd86 93b9306 03fd9cf bcef0ad ea1d7e8 fb0b727
347f16f d8c9912 01cc304 cd2b5ff 8939ac0 c4cd678 62e953c 4b6885e a1f4177 3d724cb
75f90d7 f332601 be9adea 2154077 47947a6 39b2d52 2539f2a a2e8f20
```

### M3

```text
ecbadea 504816a 5a5f294 8e200a3 9dde750 e109640 126e5ff 59f2479 ca5e4bd 7fa0615
49b27f2 7af4111 9840a58 5f4f03b 2eb4085 6fc2915 b49e8fe a9312c9 e4ac899 31c797b
792f131 a360b28 8a6e1e5 888fd9d f13988b 79c9001 8c53ba5 85cc91b 9d61413 52d9c60
12253fb c832374 645310f a3d8dff a885540 6cee476 6c12a9a e13538d 86f0154 dc9020c
aa60c79 442dcd7 1059cfd ef00d14 c1cb358 434a60b 023c5b0 e840cbe 1475952 7da8439
8176ca7 95e2018 2ad7677 6e25438 096f6a1 e912543 fd773dc b8a7d4e 28f6ac2 85d190b
4116ed5 261e665 ce3bf1a 82ccaf2 530fe59 4fe996a 5fe0507 da3ec33 84bd2c4 3c9976c
91c8cb1 794c4d9 d08fc5b c20ee9e 027807f a9b9972 52ba02a 4c939c3 ec3d6d9 c0afc75
bc911bd a493372 bbd01ee 9704e5a 00cbf35 f705a7a a9cc776 f0d7c34 2022002 bef5473
397bbaa 313577b 191ced0 069a450 c45a830 4f54817 88ffa06 e4b94ec 54afccd e6c2f53
46d6ef4 b848b56 1801479 ca5ec40 a82ae5d a194783 7ba72b6 590116f f0c4810 ac4e61f
feca8a6 d78b8de b8956e7 03515cf 9344c62 e64f5e8 ba092a8 f1db82a 7ff87bb f1e7e4f
6c79edd 3b0e631 3264103 bfd26b0 f08ce6b 658e2ad 685a184 b9da038 797df18 9324fab
b4b43c4 7d08e01
```

### M4

```text
c92ba91 fb8727d 285237c f531ec7 86e22bb fd314ab bd5af06 9636183 30cebb1 49b9357
830bb0b 5b20c84 bc1ae50 11fabb7 b24d625 d858046 78ce25d
```

### M5_viewer

```text
0908dce 51451ac 9f2bab9 74364a8 1866508 dfbfed2 18eb85c 2a41ed3 bd3bac5 5e9c50e
472e2d0 e9ae558 6f487f5 a63982d 130a375 fafc664 3791fa7 14e3107 c73952c
```

### Product_submission

```text
0b4cd5f 8a8d24e 901b131 e58a1c3 4c657ae
```

### Shared

```text
3875238 13312ac 064b173 fd1125b ee32407 74f3958 9677972 cf55e05 ac22bea c9a7fe7
96cb2d2 b439691 2690003 8bd8ce2 8fc23de ba4462a 1d0e5d9 9781cee a46b5b3 9dea96f
51c38c8 a3fc20a 7d2d54e 1b238aa ef787c0 c4ec448 cd39f22 edca646 f70f10e 7d7b679
f2eb6b5
```
