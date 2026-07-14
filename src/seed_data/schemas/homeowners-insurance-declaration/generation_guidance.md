# Homeowners Insurance Declaration — Generation Guidance

## What This Document Is
The declarations page ("dec page") of a homeowners insurance policy, summarizing
coverage types, limits, deductibles, and premium. Mortgage lenders require this
to confirm the property is adequately insured before closing.

## Visual Style
- Insurance company letterhead at top
- Policy summary in a clean two-column layout
- Coverage table listing each coverage type and limit
- Premium summary at the bottom
- Mortgagee clause prominently displayed

## Data Realism Guidelines

### Coverage Amounts
- CoverageA (Dwelling): should be close to the AppraisedValue from shared context
- CoverageB (Other Structures): exactly 10% of CoverageA
- CoverageC (Personal Property): exactly 50% of CoverageA
- CoverageD (Loss of Use): exactly 20% of CoverageA
- LiabilityCoverage: $100,000 or $300,000
- MedicalPayments: $1,000 or $5,000

### Premium
- AnnualPremium: 0.5-1.0% of CoverageA typical for Pacific Northwest
- Deductible: $1,000, $2,500, or $5,000

### Policy Period
- PolicyPeriodEnd = exactly 1 year after PolicyPeriodStart
- PolicyPeriodStart should be on or before the closing date

### Mortgagee Clause
- Must include the lender name with "ISAOA ATIMA" suffix
- e.g. "First National Bank ISAOA ATIMA, 123 Main St, Seattle WA 98101"

### Math Rules (CRITICAL)
- CoverageB = CoverageA × 0.10
- CoverageC = CoverageA × 0.50
- CoverageD = CoverageA × 0.20

### Insurance Companies
Use realistic names: State Farm, Allstate, Farmers, USAA, Liberty Mutual, Travelers, Nationwide

## Common Issues to Avoid
- CoverageB/C/D not matching the standard percentages of CoverageA
- Missing mortgagee clause (lenders require this)
- PolicyPeriodEnd not exactly 1 year after start
- Premium unrealistically high or low
- PropertyAddress not matching shared context property_address

## Layout Variations

Optional narrative fields — include when context supports them, omit otherwise. Inclusion frequency ~70% each, independently:
- `CoverageNarrative` — coverage selections and why they were chosen
- `PropertyDescriptionNarrative` — insured property's characteristics relevant to coverage
- `PremiumNarrative` — premium calculation and applied discounts
- `MortgageeNarrative` — mortgagee clause and lender requirements

Table presentation variations. Either format is valid for a realistic declaration page; ~50/50 mix:
- Coverage amounts — coverage types A-D plus liability as summary table, or labeled fields
- Discounts — table with type and amount columns, or simple list
- Policy details — key-value table, or labeled fields
