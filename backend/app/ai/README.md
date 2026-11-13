# AI services

This package owns the shared model client (`llm`), assistant prompts and
attachment transcription, paper translation and reusable AI workflows.
Existing `app.services` imports are aliases to the same module objects for
compatibility; in particular, the translation queue must remain a singleton.
New AI-specific services should be added here.

Assistant and diary model prompts and calls live in `assistant_workflows` and
`diary`. HTTP routing, data retrieval, validation, persistence and UI remain in
their respective modules; those modules still handle AI availability and errors
as part of their business flow. Settings and storage locations are unchanged.
