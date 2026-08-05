# Architecture Guardrails (Non-Negotiable)

## Strictly Forbidden Actions
* **NEVER** create new REST APIs, WebSockets, or endpoints without an approved specification or ADR.
* **NEVER** change architecture boundaries, module ownership, or integration style without a documented ADR.
* **NEVER** query or join another module's database tables directly; cross-module communication occurs EXCLUSIVELY via internal Domain Events.
* **NEVER** hardcode vendor-specific CLI commands, brand names, or proprietary logic in core application layers.
* **NEVER** modify unrelated files or modules outside the explicit task scope.
* **NEVER** duplicate business logic across backend services or frontend components.
* **NEVER** bypass Pydantic input validation or return unhandled raw internal stack traces.
* **NEVER** invent undocumented domain event names or message payload formats.