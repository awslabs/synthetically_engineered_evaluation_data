# Cable Bill — Generation Guidance

## Document Type
Monthly residential cable TV and phone service billing statement from a local cable provider.

## Visual Style

### Overall Layout
- Dense, professional single-page layout (aim to fit on one page)
- Two-column header: provider branding top-left, billing info box top-right
- Tight vertical spacing between sections (6–8pt) to maximize density
- Use horizontal rules or shaded bars to separate major sections

### Color Palette & Branding
- Primary accent color: orange (#FF6600) for service section headers and provider branding
- Secondary: dark gray (#333333) for account number header bars
- Light gray (#E8E8E8) for billing info box background and alternating table rows
- Red (#CC0000) for "TOTAL AMOUNT DUE" and the grand total footer
- White text on colored header bars

### Header Area
- Top-left: provider name in bold 16pt with "LOCAL CABLE" or similar tagline below, styled like a logo block with an orange accent bar or border
- Top-right: bordered billing info table (4 rows: Billing Number, Billing Date, Total Amount Due in red, Due Date) with light gray background

### Customer Section
- "CUSTOMER:" label in bold with gray background bar
- Customer name and address below in standard 10pt

### Service Sections
- Each service gets a full-width orange header bar with white bold text: "CABLE TV SERVICE", "PHONE SERVICE"
- Below the header: gray bar with account number and billing period
- Line items in a clean table with alternating row shading
- Service total row in bold, right-aligned
- Cable TV: include a "PACKAGE CONTENTS" sidebar or box with colored square bullets (orange) and channel counts
- Phone: include sub-details (Minutes Used, Number of Calls) indented under relevant line items

### Footer
- Full-width shaded bar with bold "TOTAL CHARGES:" left-aligned and dollar amount right-aligned in large red text (14–16pt)
- Clear visual weight — this should be the most prominent element on the page

## Data Realism Guidelines

### Provider Names
Use realistic but fictional local cable company names (e.g., "Summit Cable", "Valley Communications", "Coastal Broadband"). Include a short tagline or "LOCAL CABLE" branding.

### Customer Info
Use realistic names and addresses. Account numbers should follow patterns like "NNNNN-NNN".

### Billing Summary
- PreviousBalance: typically $80–$200
- PaymentSinceLastBill: negative value matching or close to PreviousBalance
- BalanceForward: usually $0.00 if paid in full
- CurrentCharges: sum of all service totals

### Cable TV Service
- Receiver Fee: $30–$60
- Local Video Facilities Fee: $20–$40
- Local Video Service Fee: $3–$8
- Cable Maintenance Fee: $3–$8
- Taxes and surcharges as separate line items
- Local benefit credits (negative amounts) are common
- ServiceTotal = sum of all line items including taxes and credits
- PackageContents: 4–7 packages (Basic, Local, Specialty, Movies, News, Sports) with channel counts totaling 50–120

### Phone Service
- Land Line Service: $10–$20
- Long Distance Charges: $15–$35
- Include "Minutes Used" and "Number of Calls" as Detail fields
- Domestic minutes: 100–400, calls: 20–60
- Long distance minutes: 20–80, calls: 5–20
- Taxes as a separate line item

### Math Rules (CRITICAL)
- Each service's ServiceTotal MUST equal the exact sum of its LineItems amounts plus Taxes
- TotalCharges MUST equal the exact sum of all ServiceTotal values
- BillingSummary.CurrentCharges MUST equal TotalCharges
- ALL arithmetic must be verifiably correct to 2 decimal places
- Negative amounts (credits/payments) must be clearly negative

### Dates
- BillingDate and DueDate should be ~17 days apart
- Service periods are typically ~28 days (one billing cycle)
- Use YYYY-MM-DD format

## Common Issues to Avoid
- Arithmetic errors between line items and service totals
- Mismatched TotalCharges vs sum of service sections
- Overlapping text in the package contents sidebar
- Missing negative sign on payment/credit amounts
- Unrealistic charge amounts for residential cable service
