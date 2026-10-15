"""A stateful fake of the `nebius` CLI and of a boto3 S3 client (no network)."""

import json
from datetime import datetime, timezone

from tests.fakes.backend_fakes import completed

DIGEST = "sha256:" + "ab" * 32
PROJECT = "project-e00fakeproject0001"
TENANT = "tenant-e00faketenant0001"
SUBNET = "vpcsubnet-e00fakesubnet00001"
SECRET = "mbsec-e00fakesecret000001"
REGISTRY = "registry-e00fakeregistry001"
IMAGE_NAME = "cr.eu-north1.nebius.cloud/e00fakeregistry001/faultline-serverless"
IMAGE = IMAGE_NAME + "@" + DIGEST
TAG = "abc123def456"


def iso(epoch):
    stamp = datetime.fromtimestamp(epoch, tz=timezone.utc)
    return stamp.strftime("%Y-%m-%dT%H:%M:%S.") + "%06dZ" % stamp.microsecond


def option(args, name):
    args = list(args)
    return args[args.index(name) + 1] if name in args else None


class FakeNebius:
    """Answers `nebius ...` calls from an in-memory model of the cloud.

    ``fail`` queues scripted failures; ``job_plan`` scripts a Job's states by
    seconds since creation as (offset, state, error_code).
    """

    def __init__(self, clock, job_plan=None, json_create=False):
        self.clock = clock
        self.calls = []
        self.argv = []
        self.failures = []
        self.groups = {}
        self.service_accounts = {}
        self.memberships = []
        self.buckets = {}
        self.keys = {}
        self.jobs = {}
        self.secrets = {"faultline-hf-token": SECRET}
        self.registry_images = [{"digest": DIGEST, "tags": [TAG]}]
        self.subnets = [SUBNET]
        self.job_plan = job_plan or [(0, "PROVISIONING", None), (120, "RUNNING", None),
                                      (900, "COMPLETED", None)]
        self.json_create = json_create
        self.cancel_ignored = False
        self.bucket_nonempty = False       # a bucket delete is refused while the bucket holds objects
        self.project_output = PROJECT + "\n"
        self.counter = 0
        self.secret_value = "SECRET-VALUE-FOR-TESTS"
        self.logs = "[t] provisioning\n[t] running\n"

    # -- scripting -----------------------------------------------------------
    def fail(self, prefix, stderr, times=1, returncode=1):
        self.failures.append([tuple(prefix), stderr, times, returncode])

    def count(self, *prefix):
        prefix = tuple(prefix)
        return sum(1 for call in self.calls if tuple(call[:len(prefix)]) == prefix)

    def next_id(self, kind):
        self.counter += 1
        return "%s-e00fake%014d" % (kind, self.counter)

    # -- runner --------------------------------------------------------------
    def __call__(self, argv, cwd=None, timeout=None):
        args = list(argv[1:])
        self.argv.append(list(argv))
        self.calls.append(args)
        for failure in self.failures:
            prefix, stderr, times, returncode = failure
            if times > 0 and tuple(args[:len(prefix)]) == prefix:
                failure[2] -= 1
                return completed(argv, returncode, "", stderr)
        handler = self.dispatch(args)
        if handler is None:
            return completed(argv, 1, "", "unknown command: %s" % " ".join(args[:4]))
        return handler(argv, args)

    def ok(self, argv, payload):
        return completed(argv, 0, payload if isinstance(payload, str) else json.dumps(payload), "")

    def op(self, argv, resource_id):
        return self.ok(argv, {"id": "operation-e00fakeoperation01", "resource_id": resource_id})

    def dispatch(self, args):
        head = tuple(args[:4])
        table = [
            (("config", "get"), self.config_get),
            (("iam", "project", "get"), self.project_get),
            (("iam", "group", "list"), self.group_list),
            (("iam", "group", "create"), self.group_create),
            (("iam", "service-account", "list"), self.sa_list),
            (("iam", "service-account", "create"), self.sa_create),
            (("iam", "group-membership", "list-members"), self.membership_list),
            (("iam", "group-membership", "create"), self.membership_create),
            (("storage", "bucket", "create"), self.bucket_create),
            (("storage", "bucket", "get-by-name"), self.bucket_by_name),
            (("storage", "bucket", "delete"), self.bucket_delete),
            (("iam", "v2", "access-key", "create"), self.key_create),
            (("iam", "v2", "access-key", "get"), self.key_get),
            (("iam", "v2", "access-key", "delete"), self.key_delete),
            (("mysterybox", "secret", "list"), self.secret_list),
            (("vpc", "subnet", "list"), self.subnet_list),
            (("registry", "image", "list"), self.image_list),
            (("ai", "job", "create"), self.job_create),
            (("ai", "job", "get-by-name"), self.job_by_name),
            (("ai", "job", "get"), self.job_get),
            (("ai", "job", "logs"), self.job_logs),
            (("ai", "job", "cancel"), self.job_cancel),
        ]
        for prefix, handler in table:
            if head[:len(prefix)] == prefix:
                return handler
        return None

    # -- handlers ------------------------------------------------------------
    def config_get(self, argv, args):
        return self.ok(argv, self.project_output)

    def project_get(self, argv, args):
        return self.ok(argv, {"metadata": {"id": args[3], "parent_id": TENANT}})

    def group_list(self, argv, args):
        return self.ok(argv, {"items": [{"metadata": {"id": i, "name": n}} for n, i in self.groups.items()]})

    def group_create(self, argv, args):
        name = option(args, "--name")
        if name in self.groups:
            return completed(argv, 1, "", "AlreadyExists: group %s" % name)
        self.groups[name] = self.next_id("group")
        return self.op(argv, self.groups[name])

    def sa_list(self, argv, args):
        return self.ok(argv, {"items": [{"metadata": {"id": i, "name": n}} for n, i in self.service_accounts.items()]})

    def sa_create(self, argv, args):
        name = option(args, "--name")
        if name in self.service_accounts:
            return completed(argv, 1, "", "AlreadyExists: service account %s" % name)
        self.service_accounts[name] = self.next_id("serviceaccount")
        return self.op(argv, self.service_accounts[name])

    def membership_list(self, argv, args):
        group = option(args, "--parent-id")
        return self.ok(argv, {"memberships": [
            {"metadata": {"id": mid, "parent_id": g}, "spec": {"member_id": member}}
            for g, member, mid in self.memberships if g == group]})

    def membership_create(self, argv, args):
        group, member = option(args, "--parent-id"), option(args, "--member-id")
        if any(g == group and m == member for g, m, _ in self.memberships):
            return completed(argv, 1, "", "AlreadyExists: membership")
        mid = self.next_id("groupmembership")
        self.memberships.append((group, member, mid))
        return self.op(argv, mid)

    def bucket_create(self, argv, args):
        name = option(args, "--name")
        if name in self.buckets:
            return completed(argv, 1, "", "AlreadyExists: bucket %s" % name)
        bucket_id = self.next_id("storagebucket")
        self.buckets[name] = {
            "id": bucket_id,
            "max_size": option(args, "--max-size-bytes"),
            "policy": json.loads(option(args, "--bucket-policy-rules")),
            "lifecycle": json.loads(option(args, "--lifecycle-configuration-rules")),
        }
        return self.op(argv, bucket_id)

    def bucket_by_name(self, argv, args):
        bucket = self.buckets.get(option(args, "--name"))
        if bucket is None:
            return completed(argv, 1, "", "NotFound: bucket")
        return self.ok(argv, {"metadata": {"id": bucket["id"], "name": option(args, "--name")}})

    def bucket_delete(self, argv, args):
        bucket_id = option(args, "--id")
        for name, bucket in self.buckets.items():
            if bucket["id"] == bucket_id:
                if self.bucket_nonempty:
                    return completed(argv, 1, "", "FailedPrecondition: bucket is not empty")
                del self.buckets[name]
                return self.op(argv, bucket_id)
        return completed(argv, 1, "", "NotFound: bucket")

    def key_create(self, argv, args):
        key_id = self.next_id("accesskey")
        self.keys[key_id] = {"sa": option(args, "--account-service-account-id")}
        return self.op(argv, key_id)

    def key_get(self, argv, args):
        key_id = option(args, "--id")
        if key_id not in self.keys:
            return completed(argv, 1, "", "NotFound: access key")
        return self.ok(argv, {"metadata": {"id": key_id}, "status": {
            "aws_access_key_id": "AKIAFAKEKEYID", "secret": self.secret_value}})

    def key_delete(self, argv, args):
        key_id = option(args, "--id")
        if key_id not in self.keys:
            return completed(argv, 1, "", "NotFound: access key")
        del self.keys[key_id]
        return self.op(argv, key_id)

    def secret_list(self, argv, args):
        return self.ok(argv, {"items": [{"metadata": {"id": i, "name": n}} for n, i in self.secrets.items()]})

    def subnet_list(self, argv, args):
        return self.ok(argv, {"items": [{"metadata": {"id": s}} for s in self.subnets]})

    def image_list(self, argv, args):
        return self.ok(argv, {"items": self.registry_images})

    def job_create(self, argv, args):
        if "--dry-run" in args:
            return completed(argv, 0, "dry run ok\n", "")
        name = option(args, "--name")
        if name in self.jobs:
            return completed(argv, 1, "", "AlreadyExists: job %s" % name)
        job_id = self.next_id("aijob")
        self.jobs[name] = {"id": job_id, "created": self.clock(), "cancelled_at": None, "args": list(args)}
        if self.json_create:
            return self.op(argv, job_id)
        return completed(argv, 0, "Job ID: %s\n" % job_id, "")

    def find_job(self, job_id):
        for name, job in self.jobs.items():
            if job["id"] == job_id:
                return name, job
        return None, None

    def job_json(self, name, job):
        elapsed = self.clock() - job["created"]
        state, code, started, finished = "PROVISIONING", None, None, None
        for offset, plan_state, plan_code in self.job_plan:
            if elapsed >= offset:
                state, code = plan_state, plan_code
                if plan_state == "RUNNING" and started is None:
                    started = job["created"] + offset
                if plan_state in ("COMPLETED", "FAILED", "ERROR", "CANCELLED"):
                    finished = job["created"] + offset
        cancelled = job["cancelled_at"]
        if cancelled is not None and state not in ("COMPLETED", "FAILED", "ERROR"):
            state, code, finished = "CANCELLED", None, cancelled
        status = {"state": state}
        if code:
            status["state_details"] = {"code": code, "message": "details redacted in fake"}
        if started is not None:
            status["started_at"] = iso(started)
            if finished is not None:
                status["finished_at"] = iso(finished)
        return {"metadata": {"id": job["id"], "name": name, "parent_id": PROJECT,
                              "created_at": iso(job["created"])}, "status": status}

    def job_by_name(self, argv, args):
        name = option(args, "--name")
        if name not in self.jobs:
            return completed(argv, 1, "", "NotFound: job")
        return self.ok(argv, self.job_json(name, self.jobs[name]))

    def job_get(self, argv, args):
        name, job = self.find_job(args[3])
        if job is None:
            return completed(argv, 1, "", "NotFound: job")
        return self.ok(argv, self.job_json(name, job))

    def job_logs(self, argv, args):
        return self.ok(argv, self.logs)

    def job_cancel(self, argv, args):
        name, job = self.find_job(args[3])
        if job is None:
            return completed(argv, 1, "", "NotFound: job")
        if not self.cancel_ignored:
            job["cancelled_at"] = self.clock()
        return self.ok(argv, "")


class FakeS3:
    """A fake boto3 S3 client over a dict of {key: bytes}."""

    def __init__(self, objects, wrong_size=None, list_failures=0):
        self.objects = dict(objects)
        self.wrong_size = wrong_size
        self.list_failures = list_failures
        self.listed_prefixes = []
        self.downloaded = []

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        client = self

        class Paginator:
            def paginate(self, Bucket, Prefix=""):
                client.listed_prefixes.append(Prefix)
                if client.list_failures > 0:
                    client.list_failures -= 1
                    raise OSError("InvalidAccessKeyId (not propagated yet)")
                keys = sorted(k for k in client.objects if k.startswith(Prefix))
                yield {"Contents": [{"Key": k, "Size": len(client.objects[k])} for k in keys]}

        return Paginator()

    def download_file(self, Bucket, Key, Filename):
        self.downloaded.append(Key)
        data = self.objects[Key]
        if self.wrong_size == Key:
            data = data[:-1]
        with open(Filename, "wb") as handle:
            handle.write(data)
