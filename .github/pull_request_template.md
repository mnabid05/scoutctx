## What changed

<!-- Describe the user-visible outcome. -->

## Why

<!-- Link an issue or explain the problem. -->

## Verification

- [ ] `python -m unittest discover -s tests -v` passes
- [ ] New behavior has test coverage
- [ ] Documentation and changelog are updated when needed
- [ ] Output stays deterministic and contains no absolute paths
- [ ] The core makes no outbound model/network calls and default redaction is preserved
- [ ] Context/session contracts remain model-neutral and transport roots remain confined
