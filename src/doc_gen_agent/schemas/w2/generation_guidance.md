# W-2 Wage and Tax Statement — Generation Guidance

## What This Document Is
IRS Form W-2 issued annually by employers to employees, reporting wages earned
and taxes withheld for the calendar year. Mortgage lenders require 1-2 years
of W-2s to verify income history.

## Visual Style
- Structured IRS form layout with numbered boxes (1-20)
- Employer info top-left, employee info bottom-left
- Boxes arranged in a grid matching the official IRS W-2 layout
- Copy B (Employee's copy) label at top

## Data Realism Guidelines

### Tax Year
- Use recent years: 2022 or 2023
- If two W-2s are in the packet, use consecutive years

### Wages (Box 1)
- Must be consistent with the shared context AnnualIncome
- WagesAndTips may be slightly less than AnnualIncome due to pre-tax 401k contributions

### Math Rules (CRITICAL)
- SocialSecurityTaxWithheld = SocialSecurityWages × 0.062 (rounded to 2 decimal places)
- MedicareTaxWithheld = MedicareWages × 0.0145 (rounded to 2 decimal places)
- SocialSecurityWages ≈ MedicareWages ≈ WagesAndTips + pre-tax 401k contributions
- FederalIncomeTaxWithheld: ~15-22% of WagesAndTips
- StateIncomeTax: ~5-9% of StateWages (if state has income tax — WA has none)
- Box 12 Code D (401k): typically 3-8% of gross wages

### Employer EIN
- Format: XX-XXXXXXX (e.g. 47-2381956)

## Common Issues to Avoid
- SocialSecurityTaxWithheld not being exactly 6.2% of SocialSecurityWages
- MedicareTaxWithheld not being exactly 1.45% of MedicareWages
- WagesAndTips inconsistent with shared context AnnualIncome
- Washington state employees should have no state income tax (StateIncomeTax = 0 or null)

## Layout Variations

Optional narrative fields — include when context supports them, omit otherwise. Inclusion frequency ~70% each, independently:
- `WageSummaryNarrative` — total compensation for the tax year
- `TaxWithholdingNarrative` — federal and state tax withholding for the year
- `RetirementNarrative` — retirement plan contributions (Box 12)

Table presentation variations. Either format is valid for a realistic W-2; ~50/50 mix:
- Wage boxes — wage and tax boxes as IRS W-2 grid layout, or labeled fields
- Box 12 codes — table, or simple list
- State info — state wage/tax fields as a table, or labeled fields
