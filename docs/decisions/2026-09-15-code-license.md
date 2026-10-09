# Code license: Apache-2.0

Status: superseded on October 9, 2026 by Jethro's explicit MIT selection;
see [ADR 0020](0020-mit-code-license.md). The original decision below is historical.

Decision: use the unmodified Apache-2.0 license for original project code.
Its explicit contributor patent grant favors reuse of robotics infrastructure;
MIT's shorter text was the alternative. This does not license third-party
weights, datasets, media or dependencies, nor guarantee freedom from patents.

Implementation: Terra added root LICENSE, README scope statement and
`license = {file = "LICENSE"}` package metadata. The coordinator reviewed the
changes. No invented copyright owner or project NOTICE was needed for this
change. Audit any future incorporated third-party code for attribution duties.

Source: [Apache's official license](https://www.apache.org/licenses/LICENSE-2.0.txt).
