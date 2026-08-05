# Security Guardrails

* NEVER expose secrets, API keys, or tokens in code or logs.
* Validate every single input, both from users and internal system boundaries.
* Enforce the principle of least privilege.
* NEVER disable authentication or bypass RBAC checks for testing purposes.
* Escape all user input and sanitize filenames before processing.
* NEVER hardcode configuration values.
* Always retrieve secrets from the configured secret management system.