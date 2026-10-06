# Methodology: From SOFR Futures Prices to an Implied FOMC Rate Path

## 1. Objective

Recover a meeting-by-meeting path of expected Federal Reserve policy-rate changes from observed daily settlement prices of CME 1-Month SOFR (SR1) and 3-Month SOFR (SR3) futures.

For an observation date $t$, let the upcoming FOMC meetings be $m_1, m_2, \ldots, m_K$, with **known** calendar dates. Let $T_j$ be the date on which the rate decision of meeting $m_j$ takes effect (typically the business day after the announcement). Let

$$
\Delta r_j, \quad j = 1, \ldots, K
$$

be the expected policy-rate change at meeting $m_j$. We choose $\Delta \mathbf r = (\Delta r_1, \ldots, \Delta r_K)$ so that model-implied SR1 and SR3 prices fit the observed prices as closely as possible.

**What the estimate means.** Futures prices embed both expectations and possible risk premia, and each $\Delta r_j$ is a probability-weighted *expected* move, not a single outcome. For example, an estimate of $-12.5$ bp is consistent with a 50% chance of a 25 bp cut, even though the Fed only moves in discrete steps. We therefore call the result the *market-implied* path, not a pure forecast.

**Scope of $K$.** $K$ must include every meeting that can affect any contract used in the fit, up to the end of the reference period of the furthest contract. Omitting a relevant meeting misattributes its effect to the others.

---

## 2. Step 1: Represent the Future Rate Path

Let $L_t$ be the observed policy-rate level on date $t$ (for example, the effective federal funds rate, EFFR, or the target range). It is **data, not a parameter**.

The candidate daily SOFR path is a step function plus a basis term:

$$
SOFR(d) = L_t + b + \sum_{j=1}^{K} \Delta r_j \, \mathbf{1}(T_j \le d),
$$

where $d$ is a calendar date and $b$ is the SOFR-minus-policy-rate basis.

**Identification note.** $L_t$ and $b$ enter only through their sum, so they cannot both be estimated. The baseline therefore:

1. fixes $L_t$ to the observed policy level, and
2. fixes $b$ to a recent realized spread, for example the trailing average of SOFR minus EFFR over a stated window.

Estimating $b$ jointly (with regularization) and allowing a time-varying $b(d)$ (for example month-end effects) are treated as robustness checks.

---

## 3. Step 2: Price an SR1 Contract

SR1 is linked to the arithmetic average of daily SOFR over a **calendar month**.

Let contract $i$ cover $D_i$ calendar days. If SOFR fixing $k$ applies for $d_k$ calendar days (weekends and holidays carry the prior fixing),

$$
R^{model}_{i,\text{SR1}} = \frac{\sum_k d_k \, r_k}{D_i}.
$$

If the month has already started on date $t$, realized SOFR is used for elapsed days and the model path only for the remaining days:

$$
R^{model}_{i,\text{SR1}} = \frac{\sum_{d \in \mathcal R_i} SOFR^{actual}_d + \sum_{d \in \mathcal F_i} SOFR^{model}_d}{D_i},
$$

where $\mathcal R_i$ is the realized portion and $\mathcal F_i$ the remaining future portion. The model price is

$$
P^{model}_{i,\text{SR1}} = 100 - R^{model}_{i,\text{SR1}}.
$$

Implementation note: apply the settlement conventions in the CME contract specification (including any rounding rules), which should be checked against the official spec rather than assumed.

---

## 4. Step 3: Price an SR3 Contract

SR3 is linked to **compounded** SOFR over its reference period. Unlike SR1, this period is **not** a calendar quarter: it runs from one IMM date (third Wednesday of a quarterly month) to the next. Reference periods of SR3 and SR1 contracts therefore do not line up.

Let $r_k$ be the SOFR fixing for accrual interval $k$ and $d_k$ the number of calendar days it applies. The accumulation factor is

$$
A_i = \prod_k \left( 1 + \frac{d_k}{360} \cdot \frac{r_k}{100} \right),
$$

with total days $D_i = \sum_k d_k$. The annualized compounded rate and price are

$$
R^{model}_{i,\text{SR3}} = (A_i - 1) \cdot \frac{360}{D_i} \cdot 100, \qquad
P^{model}_{i,\text{SR3}} = 100 - R^{model}_{i,\text{SR3}}.
$$

If the reference period has already started, split the product into realized and future intervals:

$$
A_i = \prod_{k \in \mathcal R_i} \left( 1 + \frac{d_k}{360} \cdot \frac{SOFR^{actual}_k}{100} \right)
\prod_{k \in \mathcal F_i} \left( 1 + \frac{d_k}{360} \cdot \frac{SOFR^{model}_k}{100} \right).
$$

---

## 5. Step 4: Fit the Whole Futures Strip

Suppose $N$ usable SR1 and SR3 contracts are observed on date $t$. Each contract constrains the same latent path. Estimate

$$
\widehat{\Delta \mathbf r}
= \arg\min_{\Delta \mathbf r}
\sum_{i=1}^{N} w_i \left[ P^{market}_i - P^{model}_i(\Delta \mathbf r) \right]^2
+ \lambda \, \mathcal{R}(\Delta \mathbf r),
$$

where $w_i$ are contract weights and $\mathcal{R}$ is an optional regularization term (for example $\mathcal{R} = \sum_j \Delta r_j^2$, which shrinks poorly identified moves toward zero, or bounds such as $|\Delta r_j| \le 75$ bp).

**Regularization.** Without it, the problem can be ill-posed when $N$ is not much larger than $K$ or when some meetings are nearly unidentified (Section 11). The baseline uses a small $\lambda$ and reports results for $\lambda = 0$ as a check. Note that $\lambda > 0$ introduces a deliberate bias toward "no change", which should be reported.

**Weights.** The data are daily settlement prices, so bid-ask spreads are not available. Baseline: equal weights. Alternatives: weights balancing SR1 and SR3 contracts, or liquidity weights if volume or open-interest data are retrieved.

---

## 6. Why SR1 and SR3 Provide Different Information

The meeting dates are known inputs. What the contracts provide is information about the **size** of each move:

- **SR1** has monthly resolution. If a meeting takes effect with 10 of 30 days of the month remaining, its contribution to that month's average is $\tfrac{10}{30} \Delta r_j$, so SR1 helps separate nearby meetings from each other.
- **SR3** averages (by compounding) over a longer reference period and covers longer horizons, so it mainly constrains the cumulative path across several meetings.

Joint fitting uses both, but because reference periods overlap, the two families are **not** independent sources of information. Whether the combined system identifies every meeting is checked in Section 11.

---

# Evaluation

## 7. Benchmark: A Generic Futures-Curve Method

A transparent benchmark ignores FOMC timing. Convert each price into a contract rate,

$$
R^{market}_i = 100 - P^{market}_i,
$$

and place it at a node $\tau_i$ (for example the midpoint of the contract's reference period). A daily curve $\tilde r(d)$ is then obtained by interpolating $\{(\tau_i, R^{market}_i)\}$. The benchmark should also be replaced by the course's simplified curve method when that is implemented, so the comparison reflects the course material and not only this ad hoc version.

## 8. Fit Comparison (Interpretation Requires Care)

To compare fit on equal terms, **re-price every contract from each model's daily path using the same SR1 and SR3 pricing functions**, then compute residuals

$$
e_i = P^{market}_i - P^{model}_i,
$$

$$
RMSE = \sqrt{\frac{1}{N} \sum_i e_i^2}, \qquad
MAE = \frac{1}{N} \sum_i |e_i|, \qquad
MaxError = \max_i |e_i|.
$$

Two cautions:

1. If the benchmark is evaluated in *rate* space at its own nodes, its residuals are zero by construction. Re-pricing through the contract engines is required for a meaningful comparison.
2. The benchmark has about $N$ free values while the FOMC-aware model has only $K < N$ parameters. Better in-sample fit for the benchmark is therefore expected and is **not** evidence that it is a better model. In-sample fit is a diagnostic. The primary comparison is the realized-outcome evaluation in Section 9.

## 9. Evaluation Against Realized Policy Outcomes

Compare changes in the policy level instead of SOFR levels, so the SOFR-policy basis cancels out.

For observation date $t$ and horizon $h$ (with $h = 1$ the next meeting), define the **expected cumulative policy change** through the $h$-th upcoming meeting:

$$
\hat C_{t,h} = \sum_{j=1}^{h} \widehat{\Delta r}_j .
$$

The realized counterpart is

$$
C^{actual}_{t,h} = L_{\text{after } m_h} - L_t,
$$

where $L$ is the realized policy level (EFFR or the target range bound, used consistently). The forecast error is

$$
FE_{t,h} = \hat C_{t,h} - C^{actual}_{t,h}.
$$

For each horizon:

$$
MAE_h = \frac{1}{N_h} \sum_t |FE_{t,h}|, \quad
RMSE_h = \sqrt{\frac{1}{N_h} \sum_t FE_{t,h}^2}, \quad
Bias_h = \frac{1}{N_h} \sum_t FE_{t,h}.
$$

A per-meeting version, $\widehat{\Delta r}_h$ versus the realized change at that meeting, can be reported alongside.

For the benchmark, read the cumulative change off its daily curve, $\tilde r(\text{date after } m_h) - \tilde r(t)$, and compute the same statistics, so both methods are scored on the same targets.

**Statistical caveats.**

- There are only about 38 meetings. Observation dates before the same meeting share the same realized outcome, so errors are strongly correlated. Treat the number of independent observations as closer to the number of meetings than to the number of days, and avoid overstating significance.
- A nonzero $Bias_h$ may reflect risk premia, not only forecast error.

## 10. Check Against Realized SOFR Settlements

For contract $i$, compare the contract rate implied earlier, $R^{implied}_i = 100 - P^{market}_{i,t}$, with the eventual realized settlement rate $R^{realized}_i$:

$$
SettlementError_i = R^{implied}_i - R^{realized}_i.
$$

This measures **how well the futures market predicted SOFR**. It does not test the translation model, because $R^{implied}_i$ is just the market price restated as a rate. The model's translation is validated by (i) the price residuals in Section 8 and (ii) the synthetic recovery tests in Section 12.

---

## 11. Identification Diagnostics

Not every meeting is always separately identifiable. In a local linear approximation,

$$
\mathbf y \approx X \Delta \mathbf r + \boldsymbol{\epsilon},
$$

where $X_{ij} = \partial P_i / \partial \Delta r_j$ is the sensitivity of contract $i$ to meeting $j$. Poor identification appears when columns of $X$ are nearly collinear or too few independent contracts constrain the meetings.

Diagnostics:

- rank and singular values of $X$,
- condition number,
- approximate parameter standard errors from the local linearization,
- sensitivity of the estimate to small price perturbations, and
- comparison of solutions under different regularization strengths $\lambda$.

The analysis should separate a well-identified individual move from a cumulative change that is identified only across several meetings.

## 12. Validation Using Synthetic Data

Generate prices from a known path with the same pricing functions, then recover the path. In the noiseless case this recovers the true moves almost exactly. This is a **unit test of the code**, not evidence that the model fits real data, since the data are generated by the model itself ("inverse crime"). Recommended tests:

- single meeting, noiseless;
- several meetings, noiseless;
- small price noise, checking stability of the fit and the cumulative path;
- deliberately poorly identified setup, checking that the diagnostics in Section 11 flag it.

---

## 13. Known Limitations

- **Risk premia:** futures-implied paths are not purely expectations.
- **Basis:** SOFR differs from the policy rate and has calendar effects (for example month-end), which matter most for SR1.
- **Discrete decisions:** estimates are expectations, not realized 25 bp multiples.
- **Convexity:** pricing off a single expected path ignores the small convexity effect of averaging over rate scenarios, which is likely negligible at these horizons.
- **Data:** daily settlement prices for far-dated or illiquid contracts may be stale.

---

# Summary of the Pipeline

```
Observed SR1/SR3 settlement prices
        |
        v
Candidate meeting moves  (anchor L_t and basis b fixed)
        |
        v
Daily SOFR path
        |
        v
SR1 / SR3 settlement aggregation (realized + future days)
        |
        v
Model prices  P_i^model
        |
        v
Regularized least-squares fit to P_i^market
        |
        v
Market-implied FOMC path
        |
        v
Compared with (1) a generic curve benchmark, re-priced with the same engines,
(2) realized cumulative policy changes, and (3) realized SOFR settlements
```

The central research question is whether combining FOMC timing with contract-specific SR1/SR3 mechanics yields a more accurate and interpretable meeting-by-meeting policy path than a generic futures curve, judged mainly by out-of-sample accuracy against realized policy outcomes.
