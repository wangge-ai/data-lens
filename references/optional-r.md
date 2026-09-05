# Optional R execution

R is an optional method runtime for tasks where its implementation is materially useful, such as statistical inference, time series, survey analysis, causal designs, survival analysis, spatial statistics, and publication-quality statistical graphics.

## Rules

- Never install R or packages automatically.
- Run `python scripts/data_lens.py capabilities` before selecting an R implementation. The report names the active Python interpreter and the exact Rscript path so results from different host runtimes are not conflated.
- Rscript discovery uses this precedence: explicit `--rscript`, `DATA_LENS_RSCRIPT`, current `PATH`, then the newest Windows `Program Files/R/R-*/bin/Rscript.exe`. `capabilities`, `r probe`, and `r run` share the same resolver.
- The method manifest must declare R as an available implementation and name its package requirements.
- Use `scripts/r_method_runner.py` with a locked input and explicit output path.
- Run without user profiles or saved workspaces and enforce a timeout.
- The R result must satisfy the same method-result contract as Python.
- Where Python and R implementations overlap, compare them on a shared fixture and declared numerical tolerance.
- Missing R degrades to another eligible method or an explicit capability gap; it is not a reason to fabricate a result.

R methods must not read arbitrary directories, access the network, or overwrite source data.

On Windows, the adapter removes inherited `C.UTF-8` locale variables because Windows R otherwise warns and falls back to the non-UTF-8 `C` locale. It does not replace a valid user locale. UTF-8 CSVs, Chinese paths, headers, content, missing values, and real zeros are regression-tested when local R is available.

`r_descriptive_summary` remains a compatibility smoke. For decision-relevant work, `r_time_trend_competition` compares a linear time explanation with a local `mgcv` smooth on an ordered forward holdout and reports paired loss uncertainty. It is a predictive shape refutation only: a better smooth model does not establish a turning-point mechanism or causal effect.
