# Model access status

The selected GR00T base model and LIBERO Object policy checkpoint are public,
not gated repositories. This was verified against the Hugging Face Hub API on
September 13, 2026:

| Repository | Revision | Access state |
| --- | --- | --- |
| [GR00T N1.7 base](https://huggingface.co/nvidia/GR00T-N1.7-3B) | `2fc962b973bccdd5d8ce4f67cc63b264d6886495` | public, not gated |
| [LIBERO Object checkpoint](https://huggingface.co/nvidia/gr00t17-lerobot-libero_object-640) | `1499db357f6ca3762b56c2e8c00b530eb9a09444` | public, not gated |

There is therefore no “request access” or “accept terms” button required for
this baseline. A Hugging Face read token is optional; it may help with rate
limits, but it is not a prerequisite. If one is later useful, enter it only
through the VM's `hf auth login` prompt and never send it in chat.

## What happens next

The model server will use the normal Hugging Face cache on the VM's managed
boot disk. The assistant can now start it with the pinned GR00T configuration,
watch its local readiness endpoint, run the single LIBERO Object episode, and
save the output before any perturbation work begins.

The VM's ephemeral setup and teardown rules remain in
[cloud-pilot.md](cloud-pilot.md).
