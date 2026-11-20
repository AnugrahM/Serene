# Contributing to SEREN

Thanks for your interest in SEREN. The project is in an early prototype stage; contributions should be small, focused, and honest about platform and verification status.

## Before starting

- Check open issues and discuss major design changes before investing in implementation.
- Keep changes scoped to one concern and explain what behavior changes.
- Do not claim a prototype feature is release-ready without repeatable validation.

## Development notes

- Current text chat: `python .\main.py` with Python 3 and a local Ollama service and configured model (`qwen3:8b`).
- Experimental voice code: `seren_v3_fast.py`; its Windows/Vulkan/audio/model prerequisites are described in the README. Setup scripts install packages and download/build external components, so inspect them before running.
- No pinned dependency manifest or automated project test suite is currently provided. Include the exact manual checks, platform, and hardware used with a pull request.

## Pull requests

Include the purpose, important implementation details, verification performed, and known limitations. Avoid unrelated formatting churn. Do not include secrets, personal data, private recordings, downloaded model binaries, or generated build output.

By contributing, you agree that maintainers may review and discuss your contribution. No contributor license agreement or code license has been adopted yet; project licensing must be clarified before contributions can be distributed under an open-source license.
