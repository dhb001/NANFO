# Coding Standards

## Scope
Naming, formatting, dependency patterns, logging, error handling, and configuration hygiene.

## Standards
- Naming: PascalCase for classes, camelCase for variables/functions, UPPER_SNAKE_CASE for constants.
- Keep functions focused; avoid mixed responsibilities.
- Use dependency injection for services that touch external systems.
- Keep configuration in environment/config modules; avoid hardcoded operational values.
- Use structured logging with correlation/request identifiers where available.
- Return handled, explicit errors; never leak raw internal traces.
- Keep comments concise and explain intent, not obvious syntax.

## Non-Goals
- This file does not define architecture boundaries or feature requirements.
