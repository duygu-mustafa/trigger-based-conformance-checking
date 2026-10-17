# experimental/

Code kept for reference that the pipeline does **not** use. Results reported in the
thesis are produced by `conformance/checker.py` only.

| File | What it is |
|---|---|
| `automata.py` | Alternative streaming evaluation engine: one finite-state automaton per MP-Declare constraint, covering the response, precedence, responded-existence, co-existence, succession and unary families. |
| `test_automata_target_selection.py` | Runs the target-selection cases of `tests/test_target_selection.py` on `automata.py`, as a cross-check of the checker's semantics. |
| `test_checker_regression.py` | Compares the current checker with the checker at git ref `midterm/frontend` on all 24 templates. Needs that ref locally. |

Run from the repository root:

```bash
python -m pytest experimental/
```
