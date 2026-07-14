# Credit Report — Generation Guidance

## What This Document Is
A tri-merge credit report combining data from Equifax, Experian, and TransUnion,
used by mortgage lenders during underwriting to assess borrower creditworthiness.

## Visual Style
- Dense, multi-section report with bureau headers
- Tradelines in a tabular format with columns for creditor, type, balance, payment, status
- Credit scores prominently displayed at the top
- Public records and inquiries sections at the bottom

## Data Realism Guidelines

### Credit Scores
- Good borrower: 720-780 across all three bureaus (scores vary by 10-30 points between bureaus)
- Average borrower: 660-720
- MiddleScore = the median of the three scores (not the average)

### Tradelines
- 4-8 tradelines typical for a mortgage applicant
- Mix of account types: 1-2 credit cards, 1 auto loan, possibly student loans
- Most should be "Current" status for a qualified borrower
- Balances and payments should be realistic for the account type
- Credit card balances: $500 - $8,000
- Auto loan balances: $8,000 - $35,000
- Student loan balances: $10,000 - $60,000

### Math Rules (CRITICAL)
- TotalMonthlyPayments = sum of all MonthlyPayment values across tradelines
- TotalBalances = sum of all Balance values across tradelines
- MiddleScore = median of Equifax, Experian, TransUnion scores

### Public Records
- Most qualified borrowers have no public records — use empty array
- If included, bankruptcies should be 4+ years old

### Inquiries
- 1-3 recent inquiries is normal
- Dates within the last 6-12 months

## Common Issues to Avoid
- Credit scores outside 300-850 range
- MiddleScore not being the actual median
- TotalMonthlyPayments not matching sum of tradeline payments
- All tradelines having identical balances

## Layout Variations

Optional narrative fields — include when context supports them, omit otherwise. Inclusion frequency ~70% each, independently:
- `CreditSummaryNarrative` — overall credit profile and history
- `DerogatorySummary` — derogatory marks, or note a clean record
- `InquiryExplanation` — context on recent hard inquiries
- `ScoreFactors` — key factors affecting the credit score

Table presentation variations. Either format is valid for a realistic credit report; ~50/50 mix:
- Tradelines — detailed table with all columns, or individual account blocks
- Credit scores — three bureau scores as comparison table, or labeled values
- Inquiries — table, or simple list
- Public records — table, or simple list / "None" if empty
