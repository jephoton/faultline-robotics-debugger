# ADR 0016: Narrow external LIBERO state restoration

Status: Accepted October 5, 2026, by Jethro's explicit design checkpoint.

Support only LIBERO Object task 0, demo_0, state 0 from the acquired HDF5.
Restore scene XML and the selected state against pinned installed dependencies,
then retain the harness's ten settling steps and generate fresh GR00T actions.
Record pre/post-settle simulator-state hashes. Saved demonstration images and
actions are not policy replay and cannot establish a new outcome.

Resolve assets by full normalized paths inside explicitly selected installed
LIBERO/robosuite asset roots, never by basename. Reject missing, ambiguous,
escaping and linked assets. Use the known pinned task BDDL rather than an
arbitrary dataset-provided file. Preserve current live camera preprocessing.

Local implementation/tests are approved. They do not establish actual simulator
compatibility. Live GPU validation requires its own exact execution plan,
credential/preflight checks and fresh numeric spend approval. Expanded M3 stays
frozen. Dataset redistribution remains unapproved because license metadata
conflicts.

Research: `../research/2026-10-04-m5-external-sample.md`.
