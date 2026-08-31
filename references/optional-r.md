# Optional R execution

R is an optional method runtime for tasks where its implementation is materially useful, such as statistical inference, time series, survey analysis, causal designs, survival analysis, spatial statistics, and publication-quality statistical graphics.

## Rules

- Never install R or packages automatically.
- Run `python scripts/data_lens.py capabilities` before selecting an R implementation.
- The method manifest must declare R as an available implementation and name its package requirements.
- Use `scripts/r_method_runner.py` with a locked input and explicit output path.
- Run without user profiles or saved workspaces and enforce a timeout.
- The R result must satisfy the same method-result contract as Python.
- Where Python and R implementations overlap, compare them on a shared fixture and declared numerical tolerance.
- Missing R degrades to another eligible method or an explicit capability gap; it is not a reason to fabricate a result.

R methods must not read arbitrary directories, access the network, or overwrite source data.
