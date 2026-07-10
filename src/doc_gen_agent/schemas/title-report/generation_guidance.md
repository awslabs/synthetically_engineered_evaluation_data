# Title Report — Generation Guidance

## What This Document Is
A preliminary title report (also called a title commitment) issued by a title
company showing the current ownership, legal description, and any liens or
encumbrances on a property. Required by lenders before closing a mortgage.

## Visual Style
- Formal legal document on title company letterhead
- Numbered schedule sections (Schedule A, Schedule B-I, Schedule B-II)
- Schedule A: property and ownership details
- Schedule B-I: requirements to clear title
- Schedule B-II: exceptions and encumbrances
- Dense legal language throughout

## Data Realism Guidelines

### Property
- PropertyAddress must match shared context property_address exactly
- LegalDescription: use realistic format e.g. "Lot 14, Block 3, Maple Ridge Subdivision, King County, Washington"
- ParcelNumber: format varies by county e.g. "123456-7890"

### Ownership
- CurrentOwner: the seller's name (different from the borrower)
- VestingType: "Community Property" or "Joint Tenancy" most common

### Encumbrances
- Most clean titles have 1-2 encumbrances: existing mortgage + property taxes
- Existing mortgage holder: a bank or mortgage company
- Amount: realistic remaining balance on seller's mortgage
- Property taxes: should be "Paid" for a clean title

### Easements
- 1-2 utility easements is realistic for most residential properties
- e.g. "10-foot utility easement along the northern boundary"

### Property Taxes
- Annual amount: 0.8-1.2% of property value
- Status should be "Paid" for a clean transaction

## Common Issues to Avoid
- PropertyAddress not matching shared context
- Unpaid tax liens (makes the title unclean — avoid unless intentional)
- Missing legal description
- Overly complex encumbrances that would block a sale

## Layout Variations

Optional narrative fields — include when context supports them, omit otherwise. Inclusion frequency ~70% each, independently:
- `TitleHistoryNarrative` — ownership history and chain of title
- `EncumbranceNarrative` — existing encumbrances and their impact on the transaction
- `EasementNarrative` — easements and their practical effect on the property
- `TitleExceptionNarrative` — title exceptions or requirements to clear title

Table presentation variations. Either format is valid for a realistic title report; ~50/50 mix:
- Encumbrances — table with type/holder/amount/date columns, or individual blocks
- Easements — table, or numbered list
- Property taxes — summary table, or labeled fields
- Title details — key-value table, or labeled fields
