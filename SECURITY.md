# Security and privacy

Tidal Memory stores conversational data. Treat its database as sensitive.

- Never publish a real database, chat transcript, prompt, API key, or log.
- Do not use memory as a secret manager.
- Apply authentication and authorization in the host application.
- Provide deletion and export paths before serving multiple users.
- Use one database or an enforced tenant key per trust boundary.
- Review custom LLM and retriever adapters: they may send memory content to
  external services.

For a public release, run secret scanning against the complete Git history,
not only the current working tree.

