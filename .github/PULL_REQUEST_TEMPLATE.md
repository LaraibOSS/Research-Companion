<!-- Thanks for contributing to Research Companion! -->

## Summary

<!-- What does this PR do, in one or two sentences? -->

## Motivation

<!-- Why is this change needed? Link any related issue (Fixes #123). -->

## Test evidence

Paste the results of the three gates run locally:

```
python -m pytest -q
node --test tests/js/*.test.mjs
ruff check research_companion tests examples
```

## Checklist

- [ ] Tests added or updated (TDD)
- [ ] All three gates pass locally
- [ ] Docs updated if the change is user-facing
- [ ] No secrets or private data in the diff
