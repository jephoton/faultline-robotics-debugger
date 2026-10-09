FROM ghcr.io/allenai/vla-evaluation-harness/libero@sha256:d0c45bc5a3720d569180e6b8dd92510da895f16c3cc509ccc76e4b4ffbb9e0f0

# The final ENTRYPOINT replaces inherited startup behavior; use sh for RUN commands.
SHELL ["/bin/sh", "-c"]

ENV FAULTLINE_MODEL_PYTHON=/opt/model-env/bin/python

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --no-checkout https://github.com/allenai/vla-evaluation-harness.git /opt/upstream \
    && git -C /opt/upstream checkout --detach 35f1200eb15608aa898f727a3722f7eef889c6cd \
    && test "$(git -C /opt/upstream rev-parse HEAD)" = "35f1200eb15608aa898f727a3722f7eef889c6cd"

WORKDIR /opt/robot-debug
COPY src /opt/robot-debug/src
COPY scripts /opt/robot-debug/scripts
COPY configs /opt/robot-debug/configs
COPY pyproject.toml /opt/robot-debug/pyproject.toml
COPY LICENSE /opt/robot-debug/LICENSE
COPY deploy/serverless/requirements-model.txt /opt/robot-debug/requirements-model.txt

# Keep the model interpreter and package cache under the build layer; delete cache afterward.
RUN export UV_PYTHON_INSTALL_DIR=/opt/uv-python UV_CACHE_DIR=/tmp/uv-cache \
    && test "$(/usr/local/bin/uv --version)" = "uv 0.11.25 (x86_64-unknown-linux-musl)" \
    && /usr/local/bin/uv python install 3.12.13 \
    && /usr/local/bin/uv venv --python 3.12.13 /opt/model-env \
    && /usr/local/bin/uv pip install --python /opt/model-env/bin/python --no-deps \
        --index-url https://download.pytorch.org/whl/cu128 \
        --exclude-newer 2026-07-04T00:00:00Z \
        torch==2.11.0+cu128 torchvision==0.26.0+cu128 \
    && /usr/local/bin/uv pip install --python /opt/model-env/bin/python --no-deps \
        --index-url https://pypi.org/simple \
        --exclude-newer 2026-07-04T00:00:00Z \
        -r /opt/robot-debug/requirements-model.txt \
    && rm -rf /tmp/uv-cache

# Import checks load modules and the policy class only; they never create a policy or fetch weights.
RUN /opt/model-env/bin/python -c "import torch; import torchcodec; from lerobot.policies.groot.modeling_groot import GrootPolicy; import vla_eval.model_servers.lerobot" \
    && /opt/conda/envs/libero/bin/python -c "import importlib.metadata as m, json, sys; names=['numpy','torch','robosuite','mujoco','libero']; versions={name:(m.version(name) if name in {d.metadata['Name'].lower() for d in m.distributions() if d.metadata.get('Name')} else None) for name in names}; json.dump({'simulator':{'python':sys.version.split()[0],'packages':versions}},open('/opt/robot-debug/simulator-packages.json','w'),sort_keys=True,indent=2)" \
    && /opt/model-env/bin/python -c "import importlib.metadata as m, json, sys; names=['torch','torchvision','torchcodec','lerobot','vla-eval']; versions={name:(m.version(name) if name in {d.metadata['Name'].lower() for d in m.distributions() if d.metadata.get('Name')} else None) for name in names}; json.dump({'model':{'python':sys.version.split()[0],'packages':versions}},open('/opt/robot-debug/model-packages.json','w'),sort_keys=True,indent=2)"

ENTRYPOINT ["/opt/conda/envs/libero/bin/python", "-B", "/opt/robot-debug/scripts/run_serverless_workload.py", "--config", "/etc/faultline/workload.json"]
