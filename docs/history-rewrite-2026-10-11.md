# Commit history rewrite, October 11, 2026

The project owner asked for AI co-author trailers to be removed from every commit. The
88 commits from `71e3188` (October 9) onward were rewritten on October 11 with
only their messages changed: file trees and author/committer dates are
identical. Short hashes quoted in docs were updated to the new commits.

Container image tags in the private registry (for example `b233199a9abc`,
`cc23a893ea25`, `9413ad4ea434`, `05dd5fd7b862`) keep their **old** hashes.
Use this table to find the commit an image was built from.

| Old | New | Subject |
| --- | --- | --- |
| `71e3188` | `664fe40` | perf(jobs): keep model dependency layer cached across app edits |
| `7ba5b3c` | `0da21a4` | refactor(jobs): share bounded owned-process cleanup |
| `5dc0234` | `fbdcc57` | feat(jobs): bound model startup readiness and shutdown |
| `4fa6784` | `34b4e85` | fix(jobs): use neutral wording for shared cleanup failure |
| `e1078cb` | `9d60c22` | docs(jobs): record integrated model process checkpoint |
| `9a8b766` | `ab3e470` | docs(jobs): plan serverless entrypoint and pinned model prefetch |
| `214f344` | `2cec408` | feat(jobs): wire serverless entrypoint with pinned model prefetch |
| `288ebc2` | `723486a` | fix(jobs): defer SIGTERM until owned group cleanup is confirmed |
| `2aaede9` | `20dff3a` | fix(jobs): harden entrypoint secrets, cache overrides and error reporting |
| `5239ec5` | `a8eec34` | docs(jobs): record entrypoint integration and October billing check |
| `23d07cd` | `759fc8e` | docs(jobs): plan bounded cloud build of the serverless image |
| `d502892` | `1577cb4` | docs(feedback): record registry setup and zero CPU quota friction |
| `096f5e2` | `c1c4759` | docs(jobs): record serverless image build, probes and private push |
| `694c51c` | `7563c7e` | fix(jobs): accept a Nebius registry tag pinned to an expected digest |
| `e7d6604` | `b38c81e` | fix(jobs): export to object-storage mounts without rename or inode checks |
| `5ed59aa` | `250e6a5` | feat(jobs): log workload progress and preflight the export destination |
| `c91383c` | `74fe81e` | fix(jobs): map raw I/O errors to runtime exit and guard export preflight |
| `00a9115` | `91e8ee3` | docs(jobs): plan bounded preflight deadline repair |
| `7f78b69` | `0674741` | docs(jobs): record failed pilot and verified partial recovery |
| `dadd25f` | `d2ddc08` | fix(jobs): preserve absolute deadline across export preflight |
| `186ebdb` | `e7b7eab` | fix(jobs): bound export preflight process lifetime |
| `bb74578` | `812eaa8` | fix(jobs): reject unrepresentable absolute deadlines |
| `b12047e` | `fa0c2af` | test(jobs): scope preflight fixture cleanup |
| `9c49c3d` | `b3f531b` | docs(jobs): record integrated preflight repair and prepared retry |
| `72c17db` | `8a63ac9` | docs(jobs): gate retry on preflight launch ownership |
| `272ff7a` | `fbfe13d` | docs(jobs): record reproduced probe launch signal race |
| `1f3a4a6` | `7f438b8` | fix(jobs): retain preflight ownership during launch interruption |
| `a0fd895` | `b58324b` | fix(jobs): preserve cleanup uncertainty during handler restore |
| `34273ab` | `d0510ab` | fix(jobs): finish preflight signal handler restoration |
| `f1f5b78` | `6620bd1` | test(jobs): guard constructor probe child cleanup |
| `b233199` | `f87ebb5` | test(jobs): support Python 3.8 preflight constructor hook |
| `580d919` | `c2ac61d` | docs(jobs): record launch-guard integration and v5 retry readiness |
| `c072d79` | `63acdee` | docs(jobs): record validated serverless pilot and recovered evidence |
| `2a8c450` | `c05d50b` | docs(jobs): record deletion of the stopped pilot VM and disk |
| `0bf3321` | `1b2b249` | docs(jobs): record download identity teardown and viewer acceptance |
| `939e20c` | `71fe4d7` | docs(jobs): correct pilot mask claim against the certified M4 rectangle |
| `606a487` | `a84b233` | docs(m5): plan geometry-aware Nemotron packet and prompt |
| `58aa33b` | `cbe1bb6` | feat(m5): add geometry-aware evidence packet v2 |
| `f1ff3fd` | `0c57cf1` | feat(m5): send counts and mask groups with a v2 interpretation prompt |
| `193de65` | `c19dde9` | feat(m5): version reports and attempts in the explanation CLI |
| `5e1d21d` | `0897651` | fix(m5): disable Nemotron thinking for v2 interpretations |
| `f637f68` | `a0ca355` | feat(m5): give Nemotron precomputed totals and untested-rectangle rules |
| `6bab798` | `6a3ed39` | feat(m5): name success-bearing masks for Nemotron and guard overclaims |
| `6b7bdb6` | `188f8f4` | docs(m5): record Nemotron v2 attempts and assessment |
| `73af7b6` | `fa51c78` | docs(m5): record Nemotron v2 state and M5B next step |
| `97a1f6a` | `7796e5d` | docs(m5): plan external replay and certified-case re-run |
| `3da0b13` | `a9c6ef2` | feat(m5): label mask group outcomes and diagnose rejected interpretations |
| `5986997` | `4578a57` | feat(m5): give Nemotron plain-language mask regions and exact suite name |
| `99d7204` | `598fe16` | docs(m5): record Nemotron v2-05/06 results and recommendation |
| `06c1b2e` | `3c1f927` | feat(m5): start LIBERO episodes from the accepted external demo state |
| `3728e88` | `08fa4b9` | feat(m5): thread an external start state through stage configs and reduction |
| `730835c` | `c285242` | feat(m5): add m5b workload mode for certified re-run and external reduction |
| `cc23a89` | `d434664` | feat(m5): inject the private external reset candidate into the Job |
| `436fd0f` | `a790ac4` | docs(m5): record external-start reduction wiring and submitted Job |
| `8b7de92` | `0931ee2` | docs(m5): record external-start reduction and certified re-run results |
| `9659806` | `18ae40c` | feat(m5): ask Nemotron for plain wording, scoped citations and sample size |
| `f8bcb0b` | `cf61a42` | feat(m5): cap Nemotron observations and state the occlusion inference rule |
| `83773bf` | `ad002f1` | revert(m5): restore the v2-06 Nemotron prompt after worse v2-07/08 attempts |
| `12ee2a6` | `8852a27` | docs(m5): record final Nemotron attempts and keep v2-06 |
| `bd1a59e` | `4507e66` | feat(m5): run the position grid from an external start and reduce any parent |
| `afb8eaa` | `9e0902d` | feat(m5): add m5b-grid mode that reduces a confirmed external-start failure |
| `3043e79` | `18c0a4c` | docs(m5): record external-start position grid results |
| `b09f60e` | `ea1c286` | docs(jobs): record Serverless search validation and external grid state |
| `17db68e` | `36540ae` | docs(jobs): record M5B identity teardown and pending bucket deletions |
| `13e6b5e` | `b7398aa` | docs(m5): accept external demo_1 and the v2-06 Nemotron report |
| `9413ad4` | `0f61d8f` | feat(m5): accept external demo_1 with its own pinned state hash |
| `65aeff0` | `efe4fba` | docs(m5): record M5C acceptance and the demo_1 external run |
| `84be351` | `0fa2c38` | docs(m5): record demo_1 external grid result |
| `ba627a2` | `c1e3ec3` | docs(m5): record demo_1 outcome and pending bucket deletions |
| `1dc9e70` | `3c6a718` | docs(m5): accept grid search continuing after unreproducible failures |
| `6f3443a` | `0e94767` | feat(m5): keep the position grid searching after unreproducible failures |
| `ffbd1e3` | `8c0a75d` | docs(m5): record reduced failure from external demo_1 |
| `0935127` | `cefaf4f` | docs(m5): mark M5 complete |
| `05dd5fd` | `5c59247` | docs: correct repository visibility record to public |
| `3d361b5` | `2320943` | docs: record post-M5 roadmap order |
| `54c109c` | `be0a75e` | docs: record v9 image, balance and M5D handover |
| `bb86d75` | `3281dac` | docs(m5d): accept Tavily research design and tighter M3 timeboxes |
| `ae289d0` | `4df141b` | feat(viewer): show related public research beside explanations |
| `6235ca9` | `0b46c98` | feat(m5d): build deterministic research queries from case evidence |
| `7da4b0f` | `e93533b` | feat(m5d): add bounded Tavily search client with credit ledger and cache |
| `fbf0282` | `dc37d20` | feat(m5d): store immutable case research records |
| `08119ca` | `e9dfb92` | feat(m5d): add source-cited Nemotron research summary |
| `c0595a8` | `492cba2` | feat(m5d): add research_case CLI |
| `e3b0a82` | `26a1247` | fix(m5d): reject hidden key echoes and count reported credits |
| `f929e07` | `e204ae7` | fix(m5d): store the paid summary before writing the rejection diagnosis |
| `f8ee7ad` | `2ebf1d4` | fix(m5d): reject generic domains and causal-proof language in summaries |
| `fe29a19` | `9554051` | fix(m5d): ignore in-progress temp files when scanning research records |
| `fc3a7b1` | `3de816e` | fix(m5d): keep non-ASCII research context within the request size cap |
