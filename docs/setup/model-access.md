# Model access handoff

The cloud pilot is ready to start the GR00T model server, but model access is
intentionally held by the account owner. A Hugging Face token is a credential:
never paste it into chat, Git, a YAML configuration, or shell history.

## One-time owner steps

1. While signed in to Hugging Face, visit the
   [GR00T N1.7 base model](https://huggingface.co/nvidia/GR00T-N1.7-3B) and
   accept any required terms. Also confirm access to the
   [LIBERO Object policy checkpoint](https://huggingface.co/nvidia/gr00t17-lerobot-libero_object-640).
2. Create a Hugging Face **read** access token. It does not need write or
   organization permissions.
3. From a real terminal connected to the running pilot VM, enter the token into
   the prepared CLI prompt:

   ```bash
   /home/robot/.venvs/vla-eval/bin/hf auth login
   /home/robot/.venvs/vla-eval/bin/hf auth whoami
   ```

   The first command prompts privately; do not put the token after the command
   name. The second command should identify the account without revealing the
   token.
4. Tell the project assistant only that the login and terms acceptance are
   complete. Do not include the token or the `whoami` output.

## What happens next

The model server will use the normal Hugging Face cache on the VM's managed
boot disk. The assistant will start it with the pinned GR00T configuration,
watch its local readiness endpoint, run the single LIBERO Object episode, and
save the output before any perturbation work begins.

The VM's ephemeral setup and teardown rules remain in
[cloud-pilot.md](cloud-pilot.md).
