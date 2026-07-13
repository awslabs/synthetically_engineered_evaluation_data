# Police Incident Report — Generation Guidance

## Document Type
Law enforcement incident/offense report. 2-5 pages. Heavy narrative with structured header. This is one of the most text-dense document types.

## Visual Style
- Department header with badge/seal placeholder, department name, city, state
- Case information block: case number, date/time, location, offense type, reporting officer
- Involved parties section: victim(s), suspect(s), witness(es) each with name, DOB, address, phone
- Narrative section: officer's detailed account of the incident (the bulk of the document)
- Witness statements: 1-2 separate narrative blocks attributed to witnesses
- Evidence/property section: list of items collected or involved
- Officer signature block with badge number and date
- Use 9pt monospaced or serif font for the narrative (looks like a typed report)
- Dense, utilitarian layout — no decorative elements

## Data Realism
- Case numbers: format YY-NNNNN (e.g., 24-08291)
- Dates/times: specific to the hour and minute (e.g., "2024-03-15 at approximately 2247 hours")
- Locations: realistic street addresses with city, state
- Offense types: realistic categories (Burglary, Assault, Theft, Vandalism, DUI, Domestic Disturbance)
- Officer narrative should be 4-8 paragraphs in first person, past tense, formal police writing style
  - "This officer responded to a call for service at..."
  - "Upon arrival, this officer observed..."
  - "The victim stated that..."
- Witness statements: 1-3 paragraphs each, in third person ("The witness stated...")
- Evidence: 2-5 items with description and disposition

## Key Extraction Fields
CaseNumber, ReportDate, ReportTime, Location, OffenseType, ReportingOfficer, BadgeNumber, Victims (list), Suspects (list), Witnesses (list), NarrativeSummary, EvidenceItems (list)

## Common Issues to Avoid
- Narrative too short — real police reports are detailed and verbose
- Inconsistent times or locations within the narrative
- Unrealistic offense descriptions
- Missing officer identification
