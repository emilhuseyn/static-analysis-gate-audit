# What is a static analysis gate worth?

Code and derived results for the paper *What Is a Static Analysis Gate Worth? Cost Units, Commit Size,
and the Evidence for Gating on SonarQube Rules*.

Teams gate their pipelines on static analysis, and the literature reports how well SonarQube rules
predict fault-inducing commits in AUC. A gate does not spend AUC. It spends review effort. This
repository measures what the gate is worth in that currency, on the 60,489 commits, in the 28 projects
of the Technical Debt Dataset carrying any SZZ label, that a SonarQube analysis links to. The base rate
of fault-inducing commits in that population is 16.14 percent.

## What the audit found

- **A coverage ceiling no threshold can lift.** Only 4,485 of the 9,765 fault-inducing commits
  introduce any violation, so at this dataset's coverage no policy reading the violation flag can
  recall more than 45.9 percent of them.
- **Flagging any violation** gives 29.84 percent precision at 248 alerts per thousand commits, a lift
  of 1.85 over the base rate.
- **Severity orders fault-proneness, and the top of it does not deploy.** BLOCKER reaches 48.71 percent
  precision at a lift of 3.02, the best policy in the study, but it fires 7.0 times per thousand
  commits, which is about once per project per year.
- **Most of the signal is change size.** Standardised within quintiles of commit size, the pooled lift
  of 1.85 attenuates to 1.19, with a project-clustered 95 percent interval of 1.05 to 1.31 that
  excludes 1. Commit size accounts for 77 to 80 percent of the crude lift, stable across 5, 10, 20 and
  50 strata.
- **Adding violations to a size-aware ranking buys almost nothing out of sample.** Under
  leave-one-project-out logistic fitting the gain over a churn-only ranking runs from -0.3 to +1.3
  points of recall across review budgets.
- **The winner depends on the cost unit.** Costed per commit reviewed, ranking by violations beats
  ranking by lines changed below 100 alerts per thousand and loses above it, 64.0 percent recall
  against 77.0 at a budget of 500. Costed per changed line, reviewing the smallest commits first beats
  every violation-based policy at every budget tested. Those two policies are the ManualDown and
  ManualUp baselines already known in defect prediction; neither reads a rule.
- **Pooled figures describe no project.** Across the 28 projects, precision and lift vary by an order
  of magnitude, and no rule with volume separates from the rest of the screen: the highest point
  estimate, 54.41 percent, is the maximum of 116 estimates on an interval 25 points wide that contains
  every other rule in the table.

## A selection effect worth knowing before you read the numbers

Three projects (`commons-exec`, `commons-ognl`, `hive`) carry no positive SZZ label at all and are
excluded from the primary population, along with their 7,061 commits. Those three hold **50.9 percent
of all violations in the linked corpus.** Half the violation mass therefore sits in projects where no
gate can be scored. This is reported rather than assumed away, and it bounds how far these results
generalise.

## The correction trail

Scripts `01` to `14` are the first pass, run on all 31 linked projects. Two adversarial review rounds
found three errors in it, and `15` to `18` are the corrected analysis the paper reports:

- The apparent **severity inversion** (INFO above BLOCKER) was an artefact of the three zero-label
  projects. On the corrected population BLOCKER leads at 48.71 percent and the ordering reverses.
- The claim that **ranking by churn beats violations at every budget** is false below 100 alerts per
  thousand.
- A **tie-handling bug**: 45,458 of the 60,489 commits introduce no violation and therefore tie at
  zero, and resolving those ties by row order rather than by expectation inflated recall at a budget of
  500 from 52.7 to 64.0.

Both passes are shipped. `results/` holds the outputs of each, so the corrections can be checked rather
than taken on trust.

## Getting the data

The corpus is not redistributed here. Download the Technical Debt Dataset release `td_V2` from its
published source (doi:10.1145/3345629.3345630) and place `td_V2.db` in `data/`.
`scripts/01_killcheck.py` prints the table inventory of whatever you have, so you can confirm you hold
the same release: ours reports 31 projects, 153,994 commits and 1,024,614 SonarQube issues.

## Running

```
pip install numpy scipy matplotlib
python scripts/01_killcheck.py
python scripts/02_base_rate.py
python scripts/03_verify_labels.py
python scripts/04_published_table.py
python scripts/05_leak_probe.py
python scripts/06_trivial_gate.py
python scripts/07_rule_screen.py
python scripts/08_certification.py
python scripts/09_budget_curve.py
python scripts/results_gate.py
python scripts/15_corrected.py
python scripts/16_round2_check.py
python scripts/17_deployment.py
python scripts/18_combined.py
python scripts/10_figures.py
```

`scripts/15_corrected.py` is the primary analysis and, with `16` to `18`, the source of every number in
the paper. All randomness is seeded (20260808), so a rerun reproduces the published values exactly.

`scripts/04_published_table.py` needs no data: it checks the arithmetic of the audited paper's own
published Table 2 against the counts stated in its text and abstract.

## Licence

Code: MIT. Derived result files and figures: CC BY 4.0. The dataset remains under its own licence.
