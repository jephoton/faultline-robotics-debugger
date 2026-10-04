# M5 text-only Nemotron pilot: access notes

Research checked 2026-10-04 against Nebius Token Factory's current public pages and official cookbook. This is access research only; it does not settle the wider client design.

## Verified from public sources

- Nebius currently lists **Nemotron-3-Nano-30B-A3B** as a public Token Factory model: 30B total parameters, 262K context, FP8 serving, $0.06/1M input tokens and $0.24/1M output tokens. Its model-specific page says public endpoint available. Rates and public availability are provider-published, not account-specific confirmation. [Nebius Nemotron model page](https://nebius.com/services/token-factory/models/nvidia-nemotron-models-inference)
- Exact API identifier shown by Nebius's official cookbook is `nvidia/nvidia-nemotron-3-nano-30b-a3b` (lowercase). This differs from the previously proposed capitalized candidate `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`; do not assume the two are aliases. The recipe calls the OpenAI-compatible `chat.completions.create` interface. Use text messages only for this pilot, and verify the exact identifier in the active account's `/models` listing before any inference call. [Official Nebius cookbook model recipe](https://github.com/nebius/token-factory-cookbook/blob/main/models/nemotron/nemotron3-nano-30b.md)
- The same model recipe says the model supports function calling and structured output. Token Factory documents JSON Schema (`response_format` type `json_schema`) and arbitrary JSON object mode, but its generic docs say to rely on the model card's JSON mode tag. The model-specific cookbook is positive for structured output; exact JSON Schema behavior still merits a bounded probe. [Token Factory JSON docs](https://docs.tokenfactory.nebius.com/ai-models-inference/json)
- Token Factory quickstart uses `https://api.tokenfactory.nebius.com/v1/`, bearer/API key auth via `NEBIUS_API_KEY`, and the OpenAI-compatible chat completions endpoint. It directs a new user to create an account, sign in with Google or GitHub, and get an API key. [Quickstart](https://docs.tokenfactory.nebius.com/quickstart)
- Token Factory onboarding requires its own billing setup and payment method; its billing page describes a $1 trial credit for first sign-up, valid 30 days. This is distinct from the project's Nebius AI Cloud compute-credit envelope. Public documentation does not establish that AI Cloud credits transfer to or pay for Token Factory inference. Check the Token Factory balance/usage page and current account terms before using it; do not count AI Cloud credits as inference budget. [Token Factory billing and consumption](https://docs.tokenfactory.nebius.com/other-capabilities/billing-new)

## Pilot boundary and access steps

The model-specific cookbook uses the regional
`https://api.tokenfactory.us-central1.nebius.com/v1/` base, whereas the generic
quickstart uses the approved global base. Do not silently switch endpoints or
assume regional account/model access. Check the active account's model listing
first and document which base was used.

The requested pilot remains metadata/evidence-ID only: no video payloads, private paths, or logs. The parent task reports no relevant `NEBIUS` / `TOKEN_FACTORY` / `NEMOTRON` environment variables and no repository environment files; AI Cloud CLI OAuth is not a Token Factory inference key. Account login, key possession, account balance, and model entitlement therefore remain unverified.

When Jethro is ready to enable access, create/sign in to Token Factory directly, review the Token Factory billing page and current balance, and create a dedicated API key there. Store it in a local secret store or user-level environment configuration; do not paste it into chat, source, a checked-in `.env`, or a command literal that may enter shell history. The local caller can then read it as `NEBIUS_API_KEY`. Do not perform a request until the available balance/terms and the pilot's call/token cap are confirmed.

At the published rates, the proposed conservative cap is at most 10 calls, each capped at 6,000 input tokens and 600 output tokens. That is $0.000504 per call ($0.00036 input + $0.000144 output), or $0.00504 total for 10 calls, before retries or other fees. Keep the user-approved $0.02 ceiling; disable automatic retries or count them within the 10-call limit. Token usage, current live rate, and billing display should be checked before and after the pilot. This arithmetic is a planning bound, not a live quote or account-billing verification.

## Open checks before first request

- Confirm the active Token Factory account, available balance/trial expiry, model listing in its live catalog, and the exact identifier above in the Playground/API model card.
- Confirm whether billing requires a card even when trial credit is available, and ensure the account settings cannot exceed the approved $0.02 exposure. The published rates alone do not enforce a spend cap.
- Confirm JSON mode against the exact model card if machine-readable responses are required; otherwise request plain text and store only approved metadata/evidence IDs.
- AI Cloud compute balance, quota, and resource limits are outside this inference check and remain separate.
