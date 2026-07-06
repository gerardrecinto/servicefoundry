# Design Rubric

Use this to grade a case write-up (yours or someone else's) before calling it done.

| Dimension | Weak | Strong |
|---|---|---|
| Requirements | Assumes numbers not given | States assumptions explicitly, flags what's out of scope |
| Entities | Entities mirror database tables | Entities mirror the domain; persistence is a separate decision |
| API | CRUD with no idempotency story | Idempotency, error semantics, and versioning addressed |
| Boundaries | Everything imports everything | Explicit statement of what's NOT coupled |
| Failure modes | Only happy path covered | Retries, partial failure, concurrent writes all addressed |
| Tradeoffs | Only the chosen approach shown | Rejected approaches listed with the specific reason |
| Operations | No mention of production behavior | Names the metric/log that would catch this failing |

A write-up that scores "weak" on tradeoffs is the most common failure — it usually means only one design was ever considered.
