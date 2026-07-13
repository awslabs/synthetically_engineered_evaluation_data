# Bank Statement — Generation Guidance

## Document Type
Monthly personal or business bank account statement. 1-3 pages depending on transaction volume. Highly structured and math-intensive.

## Visual Style
- Bank logo/name in header with branch address
- Account holder info block: name, address, account number (partially masked: ****1234)
- Statement period prominently displayed
- Account summary box: opening balance, total deposits, total withdrawals, closing balance
- Transaction table: date, description, debit, credit, running balance
- Use alternating row shading in transaction table
- 8pt font for transactions (dense, compact)
- Footer with bank disclosures in 6-7pt text

## Data Realism
- Account numbers: format ****NNNN (last 4 digits only)
- Statement period: one calendar month
- 15-40 transactions typical for a monthly statement
- Transaction descriptions should be realistic:
  - Deposits: "Direct Deposit - [Employer]", "Mobile Deposit", "Transfer from Savings"
  - Debits: "POS Purchase - [Merchant]", "ACH Payment - [Utility]", "ATM Withdrawal", "Check #NNNN", "Wire Transfer"
  - Merchant names: realistic businesses (Safeway, Shell, Amazon, Comcast, State Farm)
- Amounts: $5-$5,000 range for most transactions, occasional larger items
- Running balance must be mathematically correct after every transaction

## Math Rules (CRITICAL)
- Opening balance is a realistic starting amount ($500-$50,000)
- Each transaction: new balance = previous balance + credit - debit
- Running balance must be correct for EVERY row
- Total deposits = sum of all credit column values
- Total withdrawals = sum of all debit column values
- Closing balance = opening balance + total deposits - total withdrawals
- ALL arithmetic must be verifiably correct

## Common Issues to Avoid
- Running balance errors (most common and most critical)
- Unrealistic transaction patterns (e.g., 10 ATM withdrawals in one day)
- Dates outside the statement period
- Negative balances (unless the account type supports overdraft)

## Layout Variations

Optional narrative fields — include when context supports them, omit otherwise. Inclusion frequency ~70% each, independently:
- `AccountSummaryNarrative` — summarizes account activity and balance trend for the period
- `DepositPatternNarrative` — describes the deposit pattern (regular payroll, transfers, etc.)
- `SpendingPatternNarrative` — describes notable spending categories or patterns
- `AccountNoticesNarrative` — account notices, fee waivers, or special conditions

Table presentation variations. Either format is valid for a realistic bank statement; ~50/50 mix:
- Transactions — full table with date/description/debit/credit/balance columns, or simplified list
- Account summary block — opening/deposits/withdrawals/closing as summary table, or labeled fields
- Account holder info — key-value table, or labeled fields
