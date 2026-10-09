# Serverless model dependency resolution — October 9

Generated packaging evidence, not a successful model install or inference test.
Root ran the inherited `uv 0.11.25` in the pinned LIBERO container with a
512 MiB temporary cache, read-only root filesystem and no injected credentials.
Only public source/metadata were fetched; no model weights or ML wheels installed.

Input: pinned vla-eval bridge, `lerobot[groot]` v0.6.0, torch>=2.7,<2.12,
sentencepiece and protobuf. `uv pip compile` targeted Python 3.12 and
x86_64-manylinux_2_35, with `--exclude-newer 2026-07-04T00:00:00Z`, matching
the [pinned model script](https://raw.githubusercontent.com/allenai/vla-evaluation-harness/35f1200eb15608aa898f727a3722f7eef889c6cd/src/vla_eval/model_servers/lerobot.py).
Resolution succeeded with 122 packages in 20.92 seconds. The v0.6.0 tag resolved
to immutable LeRobot commit `30da8e687a6dfc617fcd94afc367ac7071c376ce`.

Important limit: Python 3.12 was not installed in that container; uv warned
that available Python 3.13.13 was used for dependency metadata builds, while
the resolution target remained 3.12. Actual Python 3.12 installation, native
library imports, torch/TorchCodec compatibility and CUDA remain unverified.
The base is Ubuntu 22.04.3 and has no system `ffmpeg` command on its default
PATH; final packaging needs shared FFmpeg libraries and an actual import probe.
Do not infer native-library compatibility from resolution alone.

The target model environment must remain separate from simulator Python 3.8:
LeRobot resolved NumPy 2.2.6, whereas the pinned simulator contains 1.24.4.
Do not install Faultline's NumPy-constrained package into the model environment.
PyTorch/Torchvision local `+cu128` versions require their explicit CUDA index;
preserve index routing, rather than silently substituting PyPI builds. Keep
TorchCodec CPU decoding unless a new requirement justifies GPU decoding.

## Resolved requirements data

This is data for the packaging builder, not proof of an installed lock.
The extra on LeRobot preserves the requested GR00T dependency group; all
resolved dependencies are enumerated. Two VCS references are immutable.

```text
absl-py==2.5.0
accelerate==1.14.0
aiohappyeyeballs==2.7.1
aiohttp==3.14.1
aiosignal==1.4.0
annotated-doc==0.0.4
annotated-types==0.7.0
antlr4-python3-runtime==4.9.3
anyio==4.14.1
attrs==26.1.0
av==15.1.0
certifi==2026.6.17
charset-normalizer==3.4.7
click==8.4.2
cloudpickle==3.1.2
cmake==4.1.3
cuda-bindings==12.9.7
cuda-pathfinder==1.5.6
cuda-toolkit==12.8.1
datasets==4.8.5
decord==0.6.0
diffusers==0.35.2
dill==0.4.1
dm-tree==0.1.10
docstring-parser==0.18.0
draccus==0.10.0
einops==0.8.2
farama-notifications==0.0.6
filelock==3.29.5
frozenlist==1.8.0
fsspec==2026.2.0
gymnasium==1.3.0
h11==0.16.0
hf-xet==1.5.1
httpcore==1.0.9
httpx==0.28.1
huggingface-hub==1.22.0
idna==3.18
imageio==2.37.3
imageio-ffmpeg==0.6.0
importlib-metadata==9.0.0
importlib-resources==7.1.0
jinja2==3.1.6
jsonargparse==4.49.0
jsonlines==4.0.0
lazyregistry==0.4.0
lerobot[groot] @ git+https://github.com/huggingface/lerobot.git@30da8e687a6dfc617fcd94afc367ac7071c376ce
markdown-it-py==4.2.0
markupsafe==3.0.3
mdurl==0.1.2
mergedeep==1.3.4
mpmath==1.3.0
msgpack==1.2.1
multidict==6.7.1
multiprocess==0.70.19
mypy-extensions==1.1.0
networkx==3.6.1
numpy==2.2.6
nvidia-cublas-cu12==12.8.4.1
nvidia-cuda-cupti-cu12==12.8.90
nvidia-cuda-nvrtc-cu12==12.8.93
nvidia-cuda-runtime-cu12==12.8.90
nvidia-cudnn-cu12==9.19.0.56
nvidia-cufft-cu12==11.3.3.83
nvidia-cufile-cu12==1.13.1.3
nvidia-curand-cu12==10.3.9.90
nvidia-cusolver-cu12==11.7.3.90
nvidia-cusparse-cu12==12.5.8.93
nvidia-cusparselt-cu12==0.7.1
nvidia-nccl-cu12==2.28.9
nvidia-nvjitlink-cu12==12.8.93
nvidia-nvshmem-cu12==3.4.5
nvidia-nvtx-cu12==12.8.90
omegaconf==2.3.1
opencv-python-headless==4.13.0.92
packaging==25.0
pandas==2.3.3
peft==0.19.1
pillow==12.3.0
propcache==0.5.2
protobuf==7.35.1
psutil==7.2.2
pyarrow==24.0.0
pydantic==2.13.4
pydantic-core==2.46.4
pygments==2.20.0
python-dateutil==2.9.0.post0
pytz==2026.2
pyyaml==6.0.3
pyyaml-include==1.4.1
regex==2026.6.28
requests==2.34.2
rich==15.0.0
safetensors==0.8.0
sentencepiece==0.2.1
setuptools==80.10.2
shellingham==1.5.4
six==1.17.0
sympy==1.14.0
termcolor==3.3.0
timm==1.0.27
tokenizers==0.22.2
toml==0.10.2
torch==2.11.0+cu128
torchcodec==0.11.1
torchvision==0.26.0+cu128
tqdm==4.68.3
transformers==5.5.4
triton==3.6.0
typer==0.26.8
typeshed-client==2.12.0
typing-extensions==4.16.0
typing-inspect==0.9.0
typing-inspection==0.4.2
tzdata==2026.2
urllib3==2.7.0
vla-eval @ git+https://github.com/allenai/vla-evaluation-harness.git@35f1200eb15608aa898f727a3722f7eef889c6cd
websockets==16.0
wrapt==2.2.2
xxhash==3.8.0
yarl==1.24.2
zipp==4.1.0
```

Runtime model weights must still resolve the two approved exact Hugging Face
revisions; this package data does not download, pin or validate their caches.
Final image build context/secret audit and actual imports precede publication
or a paid Job. No cloud spend occurred during this metadata-only probe.
