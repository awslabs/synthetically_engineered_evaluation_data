# Property Appraisal — Generation Guidance

## What This Document Is
A Uniform Residential Appraisal Report (URAR / Fannie Mae Form 1004) completed
by a licensed appraiser estimating the market value of a residential property.
Required by lenders before approving a mortgage.

## Visual Style
- Dense multi-section form layout
- Subject property details at top
- Neighborhood analysis section
- Comparable sales grid (3 comps side by side)
- Appraiser certification and signature at bottom

## Data Realism Guidelines

### Property Values (Pacific Northwest)
- Single family homes: $450,000 - $950,000
- Condos: $300,000 - $600,000
- AppraisedValue should be within 5% of the LoanAmount + down payment from shared context

### Property Characteristics
- GrossLivingArea: 1,200 - 3,500 sq ft typical
- YearBuilt: 1960 - 2020
- Bedrooms: 2-5
- Bathrooms: 1.5 - 3.5
- Condition: C3 or C4 most common (average to good)

### Comparable Sales
- Exactly 3 comps required
- Addresses should be in the same neighborhood as the subject property
- SaleDates within last 6 months
- SalePrices within 15% of AppraisedValue
- AdjustedValue = SalePrice + Adjustments (adjustments can be negative)
- Comps should vary slightly in size, age, and features

### Math Rules (CRITICAL)
- AdjustedValue = SalePrice + Adjustments for each comp
- Adjustments should be reasonable: ±$5,000 - ±$30,000

## Common Issues to Avoid
- AppraisedValue inconsistent with loan amount from shared context
- Comparable sale dates older than 12 months
- All 3 comps having identical characteristics
- AdjustedValue not matching SalePrice + Adjustments

## Layout Variations

Optional narrative fields — include when context supports them, omit otherwise. Inclusion frequency ~70% each, independently:
- `NeighborhoodNarrative` — neighborhood, market conditions, and location factors
- `PropertyConditionNarrative` — physical condition, updates, and notable features
- `MarketAnalysisNarrative` — local market trends supporting the appraised value
- `ApproachNarrative` — the appraisal approach used (sales comparison, cost, income)
- `ReconciliationNarrative` — reconciliation of comparable sales to final value

Table presentation variations. Either format is valid for a realistic appraisal; ~50/50 mix:
- Comparable sales — side-by-side comparison table, or individual comp blocks
- Property features — features table, or labeled fields
- Adjustment grid — detailed line-by-line adjustments, or net adjustment only
