# SEREN Roadmap

This roadmap distinguishes code present today from experiments and future product direction. Statuses describe source inspection, not a release certification.

| Module | Status | Current scope / next step |
|---|---|---|
| SEREN Core | Planned | Design modular orchestration and stable interfaces; current scripts are separate prototypes. |
| SEREN Brain | Implemented (prototype) | Local Ollama text conversation in `main.py`; make model/configuration selectable. |
| SEREN Ears | Experimental | whisper.cpp server integration exists in the voice core; make setup reproducible and validate language/audio behavior. |
| SEREN Voice | Experimental | Edge TTS is present; evaluate user-selectable voices and a local synthesis option. |
| SEREN Wake | Experimental | Standalone “Hey Jarvis” openWakeWord listener; custom “Hey Seren” model and integrated lifecycle are future work. |
| SEREN Memory | Planned | Define opt-in persistence, visibility, export, and deletion controls. |
| SEREN Vision | Planned | Design consent-based screen capture and contextual assistance. |
| SEREN Mail | Planned | Define authorized integrations and user-reviewed drafts before implementation. |
| SEREN Desktop | Planned | Plan a Windows interface and permission controls. |
| SEREN Automation | Planned | Design scoped tools, user confirmation, and safe failure behavior. |

## Suggested sequencing

1. Stabilize the current text-chat entry point and document supported setup.
2. Pin voice dependencies and make the Windows voice path reproducible.
3. Validate speech recognition, turn handling, voice output, and lifecycle behavior on documented hardware.
4. Integrate a wake flow only after reliable permission and stop controls exist.
5. Design memory, vision, mail, and automation around explicit user control before building integrations.

The order is a proposal, not a delivery commitment. No dates or completion estimates are assigned.
