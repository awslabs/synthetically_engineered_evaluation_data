# Invoice Document — Generation Guidance

## Document Type
Commercial invoice for goods or services. Single page preferred, multi-page acceptable for 10+ line items.

## Visual Style
- Professional business document with clear visual hierarchy
- Company header at top with name prominently displayed (18-22pt)
- Invoice metadata (number, date, due date) in a right-aligned block or two-column layout
- Bill-to section clearly labeled
- Line items in a well-formatted table with alternating row shading
- Totals right-aligned below the table, with the final total emphasized (bold, larger font)
- Footer with payment terms in smaller text

## Data Realism Guidelines

### Companies
Use realistic-sounding business names. Mix industries: auto parts, electronics, consulting, manufacturing, food service, construction supplies.

### Addresses
Use real US city/state combinations. Include ZIP codes. Multi-line format preferred.

### Invoice Numbers
Format: INV-NNNN-XX (e.g., INV-2024-AB, INV-8391-KZ). Sequential-looking but randomized.

### Dates
- Invoice date: within the last 90 days
- Due date: 15-45 days after invoice date
- Use format: "Month DD, YYYY" on the rendered PDF

### Line Items
- 2-8 items typical, up to 20 for large orders
- Descriptions should be specific product/service names, not generic placeholders
- Quantities: 1-100 range, integers
- Unit prices: $10-$5,000 range, two decimal places
- Amount MUST equal quantity × unit_price exactly (no rounding errors)

### Totals
- Subtotal = exact sum of all line item amounts
- Tax rate: use a realistic US rate (6%-10.25%)
- Tax = subtotal × tax_rate, rounded to 2 decimal places
- Total = subtotal + tax
- ALL arithmetic must be verifiably correct

### Payment Terms
Common options: "Net 30", "Net 15", "Due on receipt", "2/10 Net 30"

## Common Issues to Avoid
- Overlapping or superimposed text
- Text too large or too small for its context
- Mismatched customer name and email
- Geographically impossible addresses (e.g., "Tokyo, CA")
- Arithmetic errors in any calculated field
- Missing or empty sections
- Inconsistent fonts or alignment
