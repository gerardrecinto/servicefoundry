# ADR 0001: One file per case study instead of one file per section

## Status
Accepted

## Context
The template set in `templates/` breaks a design into 11 sections (problem, requirements, domain model, API, classes, data model, sequence flows, edge cases, tradeoffs, tests, operations). Splitting every case into 11 files would produce over 100 files for 10 cases, most of them short.

## Decision
Each case is a single `README.md` following the same section order as the templates, rather than 11 separate files per case.

## Consequences
- Easier to read a case end-to-end without following links.
- Harder to diff a single section's history in isolation.
- The `templates/` folder still ships the 11-file breakdown for anyone who prefers splitting a new case out that way.
