# Serverless Jobs: prepare-only configuration

## Current status

Faultline can validate a bounded Nebius AI Job configuration and render its
argument vector for review. The preparation path is deliberately local and
side-effect free: it does not authenticate, contact Nebius, run subprocesses,
create a Job, or provide an `--execute` option.

The container image and `scripts/run_serverless_workload.py` runtime referenced
by the rendered command are not part of this prepare-only change and are not yet
ready. No image, GPU, renderer, inference, private Object Storage mount, or live
Job has been validated. Do not submit the example configuration.

The future live pilot remains subject to the project cloud gates: verify the
active account and project, credit balance and expiry, quota, capacity, live
prices, storage charges, and the approved run cap immediately before any paid
action. The accepted pilot boundary is one `gpu-l40s-a` GPU with preset
`1gpu-16vcpu-64gb`, no more than one hour, and an all-in cap of US$3. A local
image verification must pass first.

## Configuration contract

Copy `configs/serverless-job.example.json` to a local ignored file and replace
every illustrative placeholder. The checked-in example intentionally contains
invalid IDs, selectors, image reference, and workload path so it cannot be
submitted accidentally.

The validator requires:

- a unique lowercase `run_id` of at most 63 characters;
- explicit `project-*`, `vpcsubnet-*`, and `storagebucket-*` resource IDs;
- an immutable image reference ending in `@sha256:` plus 64 lowercase
  hexadecimal characters;
- exactly platform `gpu-l40s-a` and preset `1gpu-16vcpu-64gb`;
- a Secret Stash selector (`mbsec-*`, optionally pinned to `@mbsecver-*`) for
  `hf_secret` and, when needed, `registry_secret`—never a credential value;
- an existing local workload JSON file using a safe POSIX path and no more than
  64 KiB.

The generated Job request fixes the provider timeout to one hour, restart policy
to `never`, and injects the workload at
`/etc/faultline/workload.json`. Nebius documents `--inject-file` as read-only in
the container and limited to 64 KiB. The private bucket is mounted at
`/persistent` and the command contains only Secret Stash selectors, not secret
values.

Unknown fields, wrong JSON types, mutable images, wrong resource-ID kinds,
unsafe names or paths, and raw secret-looking values in selector fields are
rejected.

## Prepare and review

From the repository root, validate a local configuration and save the JSON argv
preview:

```console
python scripts/prepare_serverless_job.py \
  --config configs/serverless-job.local.json \
  > serverless-job.argv.json
```

Keep both local files ignored and inspect `serverless-job.argv.json`. The array
must begin with `nebius ai job create` and end with `--dry-run --async`. It must
include the intended project, subnet, bucket, digest, run ID, and selectors, and
must not contain credentials. This script only prepares the provider dry-run;
it cannot execute even that dry-run.

The exact flags in the builder were checked against `nebius` CLI 0.12.275 help.
In particular, the installed CLI documents `--args`, `--container-command`,
`--inject-file`, `--env-secret`, `--registry-secret`, `--volume`, `--dry-run`,
`--async`, `--name`, `--parent-id`, `--platform`, `--preset`, `--subnet-id`,
`--disk-size`, `--shm-size`, `--timeout`, `--restart-policy`, and
`--working-dir` for `nebius ai job create`.

## Future root-owned live workflow

These commands describe the provider lifecycle confirmed by installed CLI help;
they are not authorization to run it. The root integration owner must first
satisfy the image, account, pricing, and spending gates above.

1. Review the prepared argv and run its `nebius ai job create ... --dry-run`
   request. A later real submission must remove only `--dry-run`, use the same
   reviewed configuration, and be submitted once.
2. Save the full JSON response and exact Job ID immediately in a new ignored,
   run-specific local directory. Continue every observation by exact ID:

   ```console
   nebius ai job get JOB_ID --format json
   nebius ai job logs JOB_ID --timestamps
   nebius ai job logs JOB_ID --follow --timestamps
   ```

3. If submission returns an ambiguous response, do **not** recreate the Job.
   Resolve the unique configured name in the same explicit project first:

   ```console
   nebius ai job get-by-name \
     --parent-id PROJECT_ID \
     --name RUN_ID \
     --format json
   ```

   Persist the recovered ID, then resume `get` and `logs` by that exact ID. If
   identity is still uncertain, stop for human review; there is no safe automatic
   retry.
4. Cancel only the stored exact identity, then poll that same identity to a
   terminal state:

   ```console
   nebius ai job cancel JOB_ID
   nebius ai job get JOB_ID --format json
   ```

5. Download the closed export from the configured private Object Storage bucket
   into a fresh ignored artifacts directory, then verify the export manifest and
   readable media/JSONL before treating recovery as successful. The installed
   `nebius ai job` command has no `download` subcommand, and the generic
   `nebius storage` help does not expose object copy/download. Therefore this
   repository does not guess a download command: the exact authenticated Object
   Storage client and command must be selected and verified during the live-pilot
   gate before submission.

The provider timeout and container deadline are backups, not reasons to abandon
the workstation-side exact-ID cancel-and-poll guard. Never automatically restart,
retry, or recreate an uncertain Job submission.
