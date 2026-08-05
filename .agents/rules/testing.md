# Testing Standards

* **Unit Tests:** Must test isolated logic without hitting databases or external services. Use dependency injection and mocking.
* **Integration Tests:** Must verify inter-module event communication across the internal Event Bus.
* **Test Coverage:** All new features must include passing unit tests before being marked as done.
* **Fixtures & Data:** Use deterministic, seeded data for tests to ensure mathematical reproducibility.
* **Regression Testing:** Regression tests must be added for every resolved bug to prevent reappearance.