# Loan Application (Form 1003) — Generation Guidance

## What This Document Is
A Uniform Residential Loan Application (URLA / Fannie Mae Form 1003) submitted by a borrower
to a lender when applying for a mortgage. It captures borrower identity, employment, income,
assets, liabilities, and property details.

## Visual Style
- Multi-section form layout with clearly labeled sections (I through X)
- Dense tabular layout with labeled fields and boxes
- Lender logo and name at the top
- Section headers in bold or shaded rows
- Signature lines at the bottom

## Data Realism Guidelines

### Loan Amounts
- Purchase loans: $200,000 - $900,000 typical for Pacific Northwest
- Down payment: 5-20% of purchase price
- LTV (Loan-to-Value): 80-95%

### Income & Employment
- Annual income: $60,000 - $180,000
- MonthlyIncome = AnnualIncome / 12 (must be exact)
- Employment years: 1-15 years typical

### Math Rules (CRITICAL)
- MonthlyIncome = AnnualIncome / 12 (rounded to 2 decimal places)
- DTIRatio = MonthlyDebt / MonthlyIncome * 100 (rounded to 1 decimal place)
- DTIRatio should be between 20-45% for a realistic application

### Assets
- 2-4 asset entries typical
- Include at least one checking/savings account
- Total assets should be at least 3x the down payment

### Interest Rates
- 30-year fixed: 6.5% - 7.5% (current market range)
- 15-year fixed: 6.0% - 7.0%

## Common Issues to Avoid
- MonthlyIncome not matching AnnualIncome / 12
- DTI ratio outside realistic range (keep under 45%)
- SSN shown in full — always mask as XXX-XX-XXXX
- Unrealistic loan amounts for the property type

## Layout Variations

Optional narrative fields — include when context supports them, omit otherwise. Inclusion frequency ~70% each, independently:
- `PropertyDescription` — the subject property (type, location, condition, notable features)
- `BorrowerBackground` — the borrower's financial profile and reason for the loan
- `EmploymentNarrative` — employment history and stability
- `LoanPurposeNarrative` — the loan purpose and intended use of funds
- `AssetSummaryNarrative` — overall asset position

Table presentation variations. Either format is valid for a realistic loan application; ~50/50 mix:
- Assets — formatted table, or simple list
- Loan terms — summary table, or inline fields
- Borrower info — two-column key-value table, or labeled fields
