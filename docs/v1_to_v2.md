# V1 to V2 notes

V1 evolved incrementally and proved the usefulness of the approach. It also exposed recurring failure modes:

- visual references can be encoded in multiple PBIR shapes
- whitespace/case mismatches can create false unused results
- direct report usage is not enough; model dependencies matter
- query dependencies matter
- scanning whole TMDL files for query names overmatches badly
- making the analyzer conservative by protecting everything is not useful

V2 therefore starts from these invariants:

- dependency graph first
- explicit evidence types
- parsing separated from classification
- uncertainty maps to manual review
- strong regression tests for each discovered failure mode

The old V1 script should be retained during migration as a comparison/reference implementation, but V2 should not depend on it at runtime.
