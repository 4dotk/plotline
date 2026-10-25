# Headline results (Mode B, AI mode: sentence queries read by the live Planner, Validator widen/stop live)

| MR | Family | Seeds | Bases | Evaluated | Skipped (by reason) | Violation rate, 95 % CI | Per-pair rate (Mode B) | Unconditioned |
|---|---|---|---|---|---|---|---|---|
| MR3a | invariance | 0, 101, 202 | 30 | 20 | 10 (ALL n_in_bucket in {3,4}: 4; ALL n_in_bucket in {3,4} + L2_attempts > 0: 6) | 0/20 = 0.0 % [0.0 %, 16.8 %] Clopper-Pearson | 0/60 = 0.0 % [0.0 %, 6.0 %] Clopper-Pearson | 9/30 = 30.0 % [16.7 %, 47.9 %] Wilson |
| MR3b | invariance | 0, 101, 202 | 30 | 20 | 10 (ALL n_in_bucket in {3,4}: 4; ALL n_in_bucket in {3,4} + L2_attempts > 0: 6) | 0/20 = 0.0 % [0.0 %, 16.8 %] Clopper-Pearson | 0/60 = 0.0 % [0.0 %, 6.0 %] Clopper-Pearson | 9/30 = 30.0 % [16.7 %, 47.9 %] Wilson |

A skip is not a pass. A reason joined with `+` means every one of those applied to the base. Wilson score interval, or Clopper-Pearson when the violation count is 0 or n (contracts/Testing.md 8).
