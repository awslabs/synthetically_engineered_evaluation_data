# Pay Stub — Generation Guidance

## What This Document Is
An employee earnings statement issued by an employer for each pay period,
showing gross pay, itemized deductions, net pay, and year-to-date totals.
Used by mortgage lenders to verify income.

## Visual Style
- Two-column header: employee info on left, employer info on right
- Earnings table and deductions table side by side
- YTD totals column alongside current period column
- Clean, professional payroll system output (ADP, Paychex style)

## Data Realism Guidelines

### Pay Frequency & Gross Pay
- Bi-Weekly (most common): AnnualIncome / 26
- Semi-Monthly: AnnualIncome / 24
- Monthly: AnnualIncome / 12
- GrossPay must be consistent with the shared context AnnualIncome

### Deductions (typical set)
- Federal Income Tax: ~15-22% of gross
- State Income Tax: ~5-9% of gross (varies by state)
- Social Security: 6.2% of gross (up to annual limit)
- Medicare: 1.45% of gross
- 401k: 3-8% of gross (optional)
- Health Insurance: $100-$400 flat per period

### Math Rules (CRITICAL)
- TotalDeductions = sum of all Deduction amounts
- NetPay = GrossPay - TotalDeductions
- YTDGross = GrossPay × number of pay periods elapsed in the year
- YTDDeductions and YTDNet must be consistent with YTDGross

### Pay Period Dates
- PayPeriodEnd should be 1-2 weeks before PayDate
- Generate recent pay stubs (within last 3 months)
- Multiple pay stubs in the packet should have consecutive pay periods

## Common Issues to Avoid
- NetPay not equaling GrossPay - TotalDeductions
- YTDGross inconsistent with pay frequency and time of year
- Deduction percentages outside realistic ranges
- PayDate before PayPeriodEnd

## Layout Variations

Optional narrative fields — include when context supports them, omit otherwise. Inclusion frequency ~70% each, independently:
- `CompensationNarrative` — the employee's compensation structure (salary, hourly, overtime)
- `BenefitsNarrative` — benefits included in the pay period
- `YTDSummaryNarrative` — year-to-date earnings progress

Table presentation variations. Either format is valid for a realistic pay stub; ~50/50 mix:
- Deductions — table with current and YTD columns, or simple list
- Earnings breakdown — summary table, or labeled fields
- YTD summary — separate summary table, or inline with current period
