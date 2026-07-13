# Statement of Work (SOW) — Generation Guidance

## Document Type
A Statement of Work defining the scope, deliverables, timeline, milestones, and payment terms for a vendor engagement. 3-6 pages. Primarily free-form business prose with key extractable fields embedded throughout — similar in structure to a commercial lease but in a professional services context.

## Visual Style
- Title page or prominent header: "STATEMENT OF WORK" with SOW number
- Executive summary / scope narrative MUST appear near the top of the document, immediately after the parties block and before numbered sections
- Parties identified at top: Client and Vendor with full legal names and addresses
- Numbered sections (1. Scope of Work, 2. Deliverables, 3. Timeline, etc.)
- Professional business prose in 10pt sans-serif font, single-spaced
- Key terms (dates, amounts, milestones) embedded within paragraphs — not isolated in fields
- Milestone/payment schedule may appear as a table OR as prose paragraphs (vary per document)
- Signature block at end with authorized representatives from both parties
- Page numbers in footer
- Dense professional text — this should feel like a real consulting SOW

## Data Realism

### Vendors
Realistic consulting/services firm names. Mix of:
- Large firms: Deloitte, Accenture, Cognizant, Infosys, Wipro, Capgemini, KPMG
- Mid-market: Slalom, Thoughtworks, Booz Allen Hamilton, CGI, Unisys
- Boutique: realistic 2-3 word firm names (e.g., "Meridian Solutions Group", "Apex Digital Consulting", "Northbridge Analytics")

### Contract Values and Milestones
- TotalSOWCost: $50,000 - $5,000,000 depending on engagement type
- Small engagements ($50K-$200K): 2-3 milestones
- Medium engagements ($200K-$1M): 3-5 milestones
- Large engagements ($1M-$5M): 5-8 milestones
- Milestone amounts MUST sum exactly to TotalSOWCost
- Milestone dates must fall between SOWStartDate and SOWEndDate, in chronological order

### Engagement Duration
- Staff Augmentation: 3-12 months
- Software Development: 4-18 months
- Consulting: 1-6 months
- System Integration: 6-24 months
- Managed Services: 12-36 months

### Contract Types
- Fixed Price: specific deliverables, milestone-based payments
- Time and Materials: hourly/daily rates, monthly invoicing, not-to-exceed cap
- Cost Plus: cost reimbursement plus fixed fee or percentage

### Payment Terms
- Net 30 (most common)
- Net 45
- Net 60 (large enterprises)
- Due on Acceptance (milestone-based)

### Business Units
Realistic department names: "Digital Transformation Office", "Enterprise IT", "Product Engineering", "Data and Analytics", "Cloud Infrastructure", "Customer Experience", "Supply Chain Operations", "Finance Technology"

### Engagement Types
- Software Development
- Consulting
- Staff Augmentation
- System Integration
- Managed Services
- Data Migration
- Cloud Transformation
- Quality Assurance
- UX/UI Design Services

### Industry/Domain
- Healthcare IT
- Financial Services
- Retail and E-Commerce
- Manufacturing
- Energy and Utilities
- Telecommunications
- Government and Public Sector
- Insurance
- Logistics and Transportation

## Required Sections (each should be 1-4 paragraphs of business prose)
1. Scope of Work — high-level description of what the vendor will deliver
2. Deliverables — specific outputs, artifacts, or work products
3. Timeline and Milestones — project phases, key dates, dependencies
4. Payment Schedule — milestone amounts, invoicing process, payment terms
5. Assumptions and Dependencies — what must be true for success
6. Acceptance Criteria — how deliverables will be evaluated and accepted
7. Governance and Communication — reporting cadence, escalation, key contacts
8. Change Control — process for scope changes and their cost/timeline impact

## Optional Sections (include 2-4 of these per document for variety)
- Resource Requirements — team composition, roles, skill requirements
- Intellectual Property — ownership of work product, pre-existing IP
- Confidentiality — NDA terms, data handling requirements
- Termination — conditions for early termination, wind-down process
- Warranties — vendor warranties on deliverables
- Limitation of Liability — liability caps and exclusions
- Insurance Requirements — required vendor insurance coverage

## Math Rules (CRITICAL)
- Sum of all Milestone Amounts MUST equal TotalSOWCost exactly
- Milestone TargetDates must be in chronological order
- All TargetDates must fall within [SOWStartDate, SOWEndDate]
- For T&M contracts: if hourly rates are mentioned, hours x rate calculations must be correct

## Key Extraction Fields
VendorName, SOWStartDate, SOWEndDate, TotalSOWCost, ContractType, PaymentTerms, BusinessUnit, EngagementType, IndustryDomain, MilestoneName, MilestoneTargetDate, MilestoneAmount

## Common Issues to Avoid
- Milestone amounts not summing to TotalSOWCost
- Milestone dates outside the SOW date range
- Milestone dates not in chronological order
- Inconsistent contract type (e.g., mentioning hourly rates in a Fixed Price SOW)
- Sections too short — each should be substantive business prose, not one-liners
- Generic placeholder language — use specific, realistic project details
- Total document under 2 pages — real SOWs are detailed

## Layout Variations

Optional narrative fields — include when context supports them, omit otherwise:
- `ScopeNarrative` (80%) — executive summary of the engagement. MUST be placed at the top of the document, immediately after the header/parties block, before any numbered sections.
- `RateCardNarrative` (50%) — billing rate structure (mainly for T&M)
- `GovernanceNarrative` (60%) — project governance and reporting
- `ChangeControlNarrative` (50%) — change order process
- `ConfidentialityNarrative` (40%) — NDA or confidentiality reference

Table presentation variations. Either format is valid for a realistic SOW; ~50/50 mix:
- Milestone schedule — formatted table with columns, or described in prose paragraphs
- Payment terms — structured table, or embedded in payment schedule prose
- Resource/team composition — table of roles and rates, or narrative description
