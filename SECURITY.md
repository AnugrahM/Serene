# Security Policy

SEREN is an early-stage project and does not yet publish supported release versions or response-time guarantees.

## Reporting a vulnerability

Please report suspected vulnerabilities privately to the repository owner through GitHub’s private reporting/contact mechanism, if available. Do not open a public issue for an unpatched vulnerability. Include only the information needed to reproduce the problem, and redact credentials, personal data, private audio, and unrelated logs.

If private reporting is unavailable, contact the maintainer through a trusted private channel before sharing details publicly.

## Scope and current cautions

- Do not use prototype software with sensitive screen, email, or audio data; those integrations are not implemented in the public source.
- The voice prototype uses an external text-to-speech service and setup scripts that download/build third-party software and model files.
- Do not expose local Ollama or Whisper endpoints to untrusted networks.
- The project has not undergone a security audit. This policy is not a claim that the software is secure or production-ready.
