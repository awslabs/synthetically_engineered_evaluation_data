# Medical Discharge Summary — Generation Guidance

## Document Type
Hospital discharge summary. Multi-page document (2-4 pages typical). Contains both structured header fields and lengthy narrative sections.

## Visual Style
- Hospital letterhead with facility name, address, phone at top
- Patient demographics in a structured header block
- Section headers in bold: "History of Present Illness", "Hospital Course", "Discharge Diagnoses", "Discharge Medications", "Follow-Up Instructions"
- Narrative sections in 9-10pt body text, single-spaced, justified
- Medications in a compact table format
- Physician signature block at bottom of last page
- Dense text — this is a clinical document, not a marketing piece

## Data Realism
- Use realistic but fictional patient names, MRNs, DOBs
- Admission/discharge dates within the last 6 months, discharge after admission
- Diagnoses should use realistic medical terminology (e.g., "Acute exacerbation of COPD", "Type 2 diabetes mellitus with peripheral neuropathy")
- Medications should be real drug names with realistic dosages (e.g., "Metformin 500mg BID", "Lisinopril 10mg daily")
- History of Present Illness should be 2-4 paragraphs of realistic clinical narrative
- Hospital Course should be 3-6 paragraphs describing treatment progression
- Attending physician name should be realistic (Dr. FirstName LastName, MD)

## Key Extraction Fields
The benchmark will extract: PatientName, MRN, DOB, AdmissionDate, DischargeDate, DischargeDiagnoses (list), Medications (list with name/dose/frequency), AttendingPhysician, FollowUpInstructions

## Common Issues to Avoid
- Unrealistic drug combinations or dosages
- Dates that don't make chronological sense
- Medical terminology that doesn't exist
- Narrative sections that are too short (should feel like a real clinical note)
- Missing signature block
