# Design Playbook

The method every case in this repo follows, from a one-paragraph product ask to a design ready for implementation.

1. **Clarify the ask.** Restate it in your own words. List what's ambiguous before assuming anything.
2. **Identify the actors.** Who initiates each action? Who consumes the result? A "system" is not an actor.
3. **Define entities and relationships.** What has identity and persists? What's a value object? Who owns which piece of state?
4. **Design the API surface.** What operations does this expose, and to whom? Idempotency and error semantics come before happy-path payloads.
5. **Assign responsibilities.** Break the domain into modules/classes and decide what's deliberately not coupled.
6. **Work through failure modes.** Retries, partial writes, downstream outages, concurrent mutation of the same entity — resolve each explicitly.
7. **State the tradeoffs.** For every non-obvious decision, write down what was rejected and why. A design without rejected alternatives probably wasn't examined closely enough.
8. **Plan for operations.** What would page someone if this broke, and what's the first lever you'd pull under load.

This order matters more than any individual section. Jumping to a schema before the entities are settled, or to code before the failure modes are enumerated, is the most common way a design ends up over-fit to the happy path.
