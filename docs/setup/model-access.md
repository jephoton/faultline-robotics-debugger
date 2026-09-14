# Model access status

The selected GR00T base model and LIBERO Object policy checkpoint are public,
not gated repositories. This was verified against the Hugging Face Hub API on
September 13, 2026:

| Repository | Revision | Access state |
| --- | --- | --- |
| [GR00T N1.7 base](https://huggingface.co/nvidia/GR00T-N1.7-3B) | `2fc962b973bccdd5d8ce4f67cc63b264d6886495` | public, not gated |
| [LIBERO Object checkpoint](https://huggingface.co/nvidia/gr00t17-lerobot-libero_object-640) | `1499db357f6ca3762b56c2e8c00b530eb9a09444` | public, not gated |

There is therefore no “request access” or “accept terms” button required for
either direct GR00T repository. A Hugging Face read token is optional for those
two downloads; it may help with rate limits, but it is not a prerequisite.

## Transitive Cosmos dependency

The first live inference attempt on September 13, 2026 revealed one additional
dependency: the GR00T runtime loads
[Cosmos-Reason2-2B](https://huggingface.co/nvidia/Cosmos-Reason2-2B) when it
processes an observation. That repository is gated. Its model page requires
the account holder to agree to share contact information and accept NVIDIA's
model terms. After that is accepted in the browser, the VM also needs a Hugging
Face **read** token from that same account; enter it only through the VM's
`hf auth login` prompt and never send it in chat.

The action sequence is deliberately explicit:

1. Log into Hugging Face in a browser and open the Cosmos repository above.
2. Complete the “agree and access” form shown on the page.
3. Create a read-scoped Hugging Face token, then enter it interactively on the
   VM with `hf auth login` (the token must not be pasted into this repository
   or a chat).
4. Restart the local model server so it inherits the authenticated cache/client,
   then repeat the same pinned one-episode baseline.

## What happens next

The model server uses the normal Hugging Face cache on the VM's managed boot
disk. The direct model files are already cached; only the authenticated Cosmos
dependency remains before the pinned baseline can produce a valid score.

The VM's ephemeral setup and teardown rules remain in
[cloud-pilot.md](cloud-pilot.md).
