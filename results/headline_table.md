# Headline results (Mode A, LLM_MODE=off)

| MR | Family | Seeds | Bases | Evaluated | Skipped (by reason) | Violation rate, 95 % CI | Per-pair rate (Mode B) | Unconditioned |
|---|---|---|---|---|---|---|---|---|
| MR1 | invariance | 0 | 350 | 350 | 0 (none) | 0/350 = 0.0 % [0.0 %, 1.0 %] Clopper-Pearson | - | - |
| MR10 | monotonic | 0 | 350 | 154 | 196 (L2_attempts > 0: 52; L2_attempts > 0 + soft filter set (price_band): 122; soft filter set (price_band): 22) | 0/154 = 0.0 % [0.0 %, 2.4 %] Clopper-Pearson | - | 108/350 = 30.9 % [26.2 %, 35.9 %] Wilson |
| MR2 | invariance | 0 | 350 | 350 | 0 (none) | 0/350 = 0.0 % [0.0 %, 1.0 %] Clopper-Pearson | - | - |
| MR3a | invariance | 0 | 350 | 202 | 148 (ALL n_in_bucket in {3,4}: 66; ALL n_in_bucket in {3,4} + L2_attempts > 0: 78; L2_attempts > 0: 4) | 0/202 = 0.0 % [0.0 %, 1.8 %] Clopper-Pearson | - | 142/350 = 40.6 % [35.6 %, 45.8 %] Wilson |
| MR3b | invariance | 0 | 350 | 202 | 148 (ALL n_in_bucket in {3,4}: 66; ALL n_in_bucket in {3,4} + L2_attempts > 0: 78; L2_attempts > 0: 4) | 0/202 = 0.0 % [0.0 %, 1.8 %] Clopper-Pearson | - | 142/350 = 40.6 % [35.6 %, 45.8 %] Wilson |
| MR4 | monotonic | 0 | 350 | 173 | 177 (ALL n_in_bucket(m) < MIN_BUCKET_N: 33; price_band set: 144) | 0/173 = 0.0 % [0.0 %, 2.1 %] Clopper-Pearson | - | - |
| MR5 | monotonic | 0 | 350 | 114 | 236 (L2_attempts > 0: 82; precondition: price_band null: 154) | 0/114 = 0.0 % [0.0 %, 3.2 %] Clopper-Pearson | - | 13/196 = 6.6 % [3.9 %, 11.0 %] Wilson |
| MR6 | monotonic | 0 | 350 | 169 | 181 (L2_attempts > 0: 57; precondition: |L| < 2: 124) | 0/169 = 0.0 % [0.0 %, 2.2 %] Clopper-Pearson | - | 37/226 = 16.4 % [12.1 %, 21.8 %] Wilson |
| MR7 | directional | 0 | 350 | 266 | 84 (L2_attempts > 0: 82; precondition: window_end + 1 beyond the snapshot: 2) | 0/266 = 0.0 % [0.0 %, 1.4 %] Clopper-Pearson | - | 8/348 = 2.3 % [1.2 %, 4.5 %] Wilson |
| MR8 | directional | 0 | 350 | 350 | 0 (none) | 0/350 = 0.0 % [0.0 %, 1.0 %] Clopper-Pearson | - | - |
| MR9 | invariance | 0 | 350 | 0 | 350 (LLM_MODE = off: 350) | n/a (0 evaluated) | - | - |

A skip is not a pass. A reason joined with `+` means every one of those applied to the base. Wilson score interval, or Clopper-Pearson when the violation count is 0 or n (contracts/Testing.md 8).
