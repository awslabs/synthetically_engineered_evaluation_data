# Employment Verification Letter — Generation Guidance

## What This Document Is
A formal letter on company letterhead issued by an employer's HR department
confirming an employee's job title, employment status, start date, and salary.
Requested by mortgage lenders to verify stable employment.

## Visual Style
- Company letterhead at top with logo placeholder, company name, address
- Formal business letter format with date, recipient address, salutation
- 2-3 paragraph body confirming employment details
- Signature block at bottom with HR contact name and title

## Data Realism Guidelines

### Content
- AnnualSalary must match shared context AnnualIncome exactly
- EmployerName must match shared context employer_name exactly
- EmployeeName must match shared context borrower_name exactly
- Letter should be addressed to the lender (RecipientName)
- LetterDate should be recent (within last 30 days)

### Tone
- Professional, formal business language
- Confirms employee is in good standing
- States employment is expected to continue

## Common Issues to Avoid
- AnnualSalary not matching shared context AnnualIncome
- Informal or casual language
- Missing signature block
- LetterDate older than 60 days (lenders require recent letters)

## Layout Variations

Optional narrative fields — include when context supports them, omit otherwise. Inclusion frequency ~70% each, independently:
- `EmploymentHistoryNarrative` — the employee's tenure and employment history
- `RoleDescriptionNarrative` — the employee's role and responsibilities
- `PerformanceNarrative` — that the employee is in good standing and employment is expected to continue
- `SalaryContextNarrative` — context about the salary structure or recent changes

Table presentation variations. Either format is valid for a realistic verification letter; ~50/50 mix:
- Employment details — key-value table, or prose in letter body
- Compensation details — table, or inline in letter body
