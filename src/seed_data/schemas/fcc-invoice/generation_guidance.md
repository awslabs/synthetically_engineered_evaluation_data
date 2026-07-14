# FCC Broadcast Invoice — Generation Guidance

## What This Document Is
An invoice from a local TV or radio station to an advertising agency, billing for
commercial airtime that was purchased on behalf of an advertiser. These are standard
business documents used in the broadcast media industry to reconcile advertising buys.

The station (e.g., KNSD San Diego, KSTP Minneapolis) runs the ads and sends the invoice
to the agency (e.g., Horizon Media Group, Carat Portland), who placed the buy on behalf
of the advertiser (e.g., a local car dealership, a national CPG brand, a political campaign).

## Visual Style
- Dense, utilitarian, tabular layout — these are business-to-business accounting documents
- Layouts vary widely between stations and billing systems — there is no single standard format
- Some have the station logo and remit address top-left, others have a simple text header
- The title is typically just "INVOICE" — not "FCC Invoice" or "Broadcast Invoice"
- Header metadata varies: some show invoice #, date, period, order #, station call letters,
  account executive, billing type. Others show just agency/advertiser and payment terms.
- The line items table is the core — columns vary but typically include description, days,
  dates, and rate. Some include channel, air time, ad-ID, reconciliation codes.
- Totals section at bottom: Gross Total, Agency Commission (usually 15%), Net Amount Due
- Many include legal/certification boilerplate at the bottom of each page
- Can be single-page (small campaigns) or multi-page (month-long buys with 20+ spots)

## Data Realism Guidelines

### Agencies
Use realistic advertising agency names (e.g., "Horizon Media Group", "Carat Portland",
"McCann Erickson", "Publicis Sapient", "Blue Sky Marketing").

### Advertisers
Use realistic brand/company names appropriate for local TV/radio advertising — local
businesses, regional chains, national brands doing local buys, political campaigns.

### Line Items
- Descriptions should reference specific programs or dayparts
  (e.g., "30-sec spot during Morning News 6-7 AM", "Evening Sports 7-8 PM")
- Keep descriptions short enough to fit in table cells without truncation
- Days: use abbreviations like "Mon-Fri", "Sat-Sun", "Mon-Thu"
- Dates: use YYYY-MM-DD format
- Rates: $50-$2,000 per spot typical for local TV
- 5-15 line items typical (vary the count — some invoices cover a single week, others a full month)

### Math Rules (CRITICAL)
- Each LineItemRate represents the TOTAL cost for that line item (not a per-spot rate)
- GrossTotal MUST equal the exact sum of all LineItemRate values
- AgencyCommission is typically 15% of GrossTotal
- NetAmountDue = GrossTotal - AgencyCommission
- ALL arithmetic must be verifiably correct to 2 decimal places

### Payment Terms
Common: "Net 30", "Net 15", "Due on receipt"

## Common Issues to Avoid
- Truncated descriptions in table cells — keep text short or wrap
- Overlapping text in dense table layouts
- Arithmetic errors in totals
- Unrealistic rates (too high or too low for local broadcast)
- Missing agency commission calculation
- All line items having the same rate — vary the amounts
- Duplicate line items — each should be distinct
