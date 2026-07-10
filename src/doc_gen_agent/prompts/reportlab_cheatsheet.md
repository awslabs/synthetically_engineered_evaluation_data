# ReportLab Python Cheat Sheet
### *Desert Island Edition — Everything You Need to Generate PDFs*

***

## Installation & Core Imports

```bash
pip install reportlab
```

```python
# ── Core modules ──────────────────────────────────────────
from reportlab.pdfgen import canvas                  # Low-level drawing API
from reportlab.platypus import (                     # High-level "story" API
    SimpleDocTemplate, BaseDocTemplate,
    PageTemplate, Frame,
    Paragraph, Spacer, Table, TableStyle,
    Image, HRFlowable, PageBreak, KeepTogether,
    ListFlowable, ListItem,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4, LETTER, landscape, portrait
from reportlab.lib.units import inch, mm, cm, pica
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
```

***

## The Two APIs at a Glance

| API | Class | Use When |
|-----|-------|----------|
| **Canvas (pdfgen)** | `canvas.Canvas` | Precise pixel-perfect layout, custom drawing, fixed-position elements |
| **Platypus (platypus)** | `SimpleDocTemplate` | Long documents, flowing text, auto page breaks, tables/paragraphs |

Both are installed with `reportlab` — you can mix them on the same page.[^1][^2]

***

## Page Sizes & Units

ReportLab works in **points** (1 pt = 1/72 inch). All coordinates are measured from the **bottom-left** corner.[^3]

### Common Page Sizes[^4]

```python
from reportlab.lib.pagesizes import (
    A0, A1, A2, A3, A4, A5, A6,     # ISO 216
    B0, B1, B2, B3, B4, B5, B6,     # ISO 216 B-series
    C4, C5, C6,                      # Envelope sizes
    LETTER, LEGAL, ELEVENSEVENTEEN,  # US sizes
    TABLOID, LEDGER,                 # Large US
)
# A4 = (595.27..., 841.88...)  — width, height in points
width, height = A4

# Orientation helpers
from reportlab.lib.pagesizes import landscape, portrait
landscape(A4)   # (841.88..., 595.27...)
portrait(A4)    # (595.27..., 841.88...)
```

### Unit Conversions[^3]

```python
from reportlab.lib.units import inch, mm, cm, pica
1*inch   # 72.0 pt
1*mm     # 2.834... pt
1*cm     # 28.34... pt
1*pica   # 12.0 pt
```

***

## Colors

```python
from reportlab.lib import colors

# Named colors (HTML names work)
colors.red
colors.blue
colors.white
colors.black
colors.lightgrey
colors.HexColor("#3498db")         # Hex string
colors.Color(0.2, 0.6, 1.0)       # RGB 0–1 floats
colors.Color(0.2, 0.6, 1.0, 0.5)  # RGBA (alpha=0.5)
colors.CMYKColor(0, 0.4, 1, 0)    # CMYK 0–1 floats
colors.toColor("red")              # Name → Color object
```

> **Tip:** `setFillColorRGB(r, g, b)` expects floats 0–1. Divide HTML 0–255 values by 256.[^5]

***

## Built-in Fonts[^6][^7]

No external files needed for these 14 Type 1 (PostScript) fonts:

```
Courier               Courier-Bold          Courier-Oblique       Courier-BoldOblique
Helvetica             Helvetica-Bold        Helvetica-Oblique     Helvetica-BoldOblique
Times-Roman           Times-Bold            Times-Italic          Times-BoldItalic
Symbol                ZapfDingbats
```

### Registering a Custom TTF Font[^6]

```python
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

pdfmetrics.registerFont(TTFont('MyFont', '/path/to/font.ttf'))
# Now use 'MyFont' anywhere a fontName is expected
```

***

## Canvas API (Low-Level)

The canvas gives you full control — draw shapes, text, images at absolute coordinates.

### Canvas Lifecycle[^1][^5]

```python
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

c = canvas.Canvas("output.pdf", pagesize=A4)
width, height = A4

# ... draw stuff ...

c.showPage()   # Finish current page, start a new one
c.save()       # Write the PDF to disk — REQUIRED
```

### Text Drawing[^5][^1]

```python
c.setFont("Helvetica-Bold", 14)
c.setFillColor(colors.black)            # or setFillColorRGB(0, 0, 0)
c.drawString(x, y, "Hello World")       # Left-aligned at (x, y)
c.drawCentredString(x, y, "Centered")  # Center at x
c.drawRightString(x, y, "Right")       # Right edge at x

# Multi-line text object (more control)
text = c.beginText(x, y)
text.setFont("Helvetica", 12)
text.setLeading(14)                     # Line spacing
text.textLine("Line one")
text.textLine("Line two")
text.textLines("Block\nof\ntext")
c.drawText(text)
```

### Shapes[^1][^5]

```python
# Lines
c.setStrokeColor(colors.red)
c.setLineWidth(2)
c.line(x1, y1, x2, y2)
c.lines([(x1,y1,x2,y2), (x3,y3,x4,y4)])

# Rectangles: rect(x, y, width, height, stroke=1, fill=0)
c.setFillColor(colors.lightyellow)
c.rect(50, 100, 200, 80, fill=1, stroke=1)

# Circles / Ellipses: circle(cx, cy, r), ellipse(x1,y1,x2,y2)
c.circle(300, 400, 50, fill=1)
c.ellipse(200, 300, 400, 450, fill=0)

# Rounded rectangle
c.roundRect(x, y, width, height, radius, fill=1, stroke=1)

# Bezier curve
c.bezier(x1,y1, cx1,cy1, cx2,cy2, x2,y2)
```

### Paths (Advanced Shapes)[^8]

```python
p = c.beginPath()
p.moveTo(100, 100)
p.lineTo(200, 200)
p.lineTo(100, 200)
p.close()
c.drawPath(p, fill=1, stroke=1)
```

### Images on Canvas[^9]

```python
# drawImage(path, x, y, width=None, height=None, mask=None, preserveAspectRatio=False)
c.drawImage("photo.png", 50, 500, width=100, height=80)
c.drawImage("photo.png", 50, 400, width=150, preserveAspectRatio=True)
c.drawImage("photo.png", 50, 300, mask='auto')  # transparent PNG

# From a URL or file-like object
from reportlab.lib.utils import ImageReader
img = ImageReader("https://example.com/logo.png")
c.drawImage(img, 50, 600, width=100, height=50)
```

### Canvas State (Save/Restore)[^1]

```python
c.saveState()          # Push current transform, colors, font onto stack
c.translate(100, 200)  # Move origin
c.rotate(45)           # Rotate 45° counter-clockwise
c.scale(1.5, 1.5)      # Scale
c.restoreState()       # Pop stack — undo all transformations
```

### Canvas Metadata & Bookmarks[^8]

```python
c.setTitle("My Report")
c.setAuthor("Jane Smith")
c.setSubject("Annual Report")
c.setKeywords("reportlab pdf python")

# PDF bookmarks (for navigation panel)
c.bookmarkPage("chapter1")
c.addOutlineEntry("Chapter 1", "chapter1", level=0)

# Internal hyperlinks
c.linkRect("chapter1", (x1, y1, x2, y2))
c.linkURL("https://example.com", (x1, y1, x2, y2))
```

### Page Numbers on Canvas[^1]

```python
page_num = c.getPageNumber()
c.drawRightString(width - 20*mm, 10*mm, f"Page {page_num}")
```

***

## Platypus API (High-Level — Flowing Documents)

Platypus = **Page Layout and Typography Using Scripts**. Content is assembled as a **story** (list of `Flowable` objects) and the engine handles pagination automatically.[^10]

### Layer Stack (top-down)[^10]

```
DocTemplate  →  PageTemplates  →  Frames  →  Flowables
```

### SimpleDocTemplate — Quickest Start[^1]

```python
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm

doc = SimpleDocTemplate(
    "report.pdf",
    pagesize=A4,
    leftMargin=20*mm,
    rightMargin=20*mm,
    topMargin=20*mm,
    bottomMargin=20*mm,
)
styles = getSampleStyleSheet()
story = []

story.append(Paragraph("My Report Title", styles["Title"]))
story.append(Spacer(1, 12))
story.append(Paragraph("Body text goes here.", styles["Normal"]))

doc.build(story)
```

### Headers & Footers with SimpleDocTemplate[^1]

```python
from reportlab.pdfgen.canvas import Canvas

def header_footer(canvas: Canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 9)
    canvas.drawString(20*mm, A4[^1] - 10*mm, "My Company")          # header
    canvas.drawRightString(A4 - 20*mm, 10*mm,
                           f"Page {canvas.getPageNumber()}")        # footer
    canvas.restoreState()

doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
```

### BaseDocTemplate + PageTemplate (Full Control)[^1]

```python
from reportlab.platypus import BaseDocTemplate, PageTemplate, Frame

def my_header(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawString(20*mm, A4[^1] - 15*mm, "Title")
    canvas.restoreState()

doc = BaseDocTemplate("report.pdf", pagesize=A4)
frame = Frame(20*mm, 20*mm, 170*mm, 257*mm, id='main')
template = PageTemplate(id='main', frames=[frame], onPage=my_header)
doc.addPageTemplates([template])
doc.build(story)
```

***

## Paragraph Styles

### Built-in Style Names[^11]

```python
styles = getSampleStyleSheet()
# Available keys:
# 'Normal', 'BodyText', 'Italic', 'Heading1'–'Heading6',
# 'Title', 'Bullet', 'Definition', 'Code', 'OrderedList', 'UnorderedList'
```

### ParagraphStyle — All Key Attributes[^12][^11]

```python
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY

style = ParagraphStyle(
    name='MyStyle',
    parent=styles['Normal'],   # inherit from another style
    fontName='Helvetica',
    fontSize=11,
    leading=14,                # line spacing (≈ 1.2× fontSize is good)
    leftIndent=0,
    rightIndent=0,
    firstLineIndent=0,
    alignment=TA_JUSTIFY,      # TA_LEFT | TA_CENTER | TA_RIGHT | TA_JUSTIFY
    spaceBefore=6,             # space before paragraph (ignored at top of frame)
    spaceAfter=6,              # space after paragraph (ignored at bottom of frame)
    textColor=colors.black,
    backColor=None,
    borderWidth=0,
    borderPadding=4,           # int or (top,right,bottom,left)
    borderColor=None,
    borderRadius=None,
    bulletFontName='Helvetica',
    bulletFontSize=10,
    bulletIndent=0,
    wordWrap=None,             # 'CJK' for Asian text
    allowWidows=1,
    allowOrphans=0,
    textTransform=None,        # 'uppercase' | 'lowercase' | 'capitalize'
    splitLongWords=1,
)
```

### Inline Paragraph XML Markup[^11]

```python
# Basic formatting tags inside Paragraph text:
Paragraph("<b>Bold</b> and <i>italic</i> text", style)
Paragraph("<u>Underline</u> and <strike>strikethrough</strike>", style)
Paragraph("Line one<br/>Line two", style)
Paragraph("<font face='Times-Roman' size=14 color='red'>Custom</font>", style)
Paragraph("H<sub>2</sub>O and E=mc<sup>2</sup>", style)
Paragraph("<greek>alpha</greek> <greek>beta</greek>", style)

# Hyperlinks
Paragraph('<a href="https://example.com" color="blue">Click here</a>', style)
Paragraph('>Jump to section</link>', style)

# Inline image within paragraph
Paragraph('<img src="icon.png" width="16" height="16" valign="middle"/>', style)

# Bullet
Paragraph('<bullet>•</bullet>List item text here.', style)
```

***

## Tables

### Basic Table Creation[^13]

```python
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors

data = [
    ["Name",   "Age", "City"],           # row 0 (header)
    ["Alice",  30,    "Austin"],
    ["Bob",    25,    "Boston"],
    ["Carol",  35,    "Chicago"],
]

t = Table(
    data,
    colWidths=[80, 40, 80],  # None = auto-calculate
    rowHeights=None,          # None = auto-calculate
    repeatRows=1,             # repeat header row on page splits
    spaceBefore=6,
    spaceAfter=6,
)
```

### TableStyle Commands — Complete Reference[^13]

**Cell coordinates:** `(col, row)`, top-left = `(0, 0)`, bottom-right = `(-1, -1)`

```python
t.setStyle(TableStyle([
    # ── Text formatting ───────────────────────────────────
    ('FONT',          (0,0), (-1,0), 'Helvetica-Bold', 10),  # fontname, [size, [leading]]
    ('FONTNAME',      (0,1), (-1,-1), 'Helvetica'),
    ('FONTSIZE',      (0,0), (-1,-1), 10),
    ('LEADING',       (0,0), (-1,-1), 12),
    ('TEXTCOLOR',     (0,0), (-1,0),  colors.white),

    # ── Alignment ─────────────────────────────────────────
    ('ALIGN',         (0,0), (-1,-1), 'CENTER'),   # LEFT | RIGHT | CENTER | DECIMAL
    ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),   # TOP | MIDDLE | BOTTOM

    # ── Padding ───────────────────────────────────────────
    ('LEFTPADDING',   (0,0), (-1,-1), 6),
    ('RIGHTPADDING',  (0,0), (-1,-1), 6),
    ('TOPPADDING',    (0,0), (-1,-1), 3),
    ('BOTTOMPADDING', (0,0), (-1,-1), 3),

    # ── Background ────────────────────────────────────────
    ('BACKGROUND',    (0,0), (-1,0),  colors.HexColor('#2c3e50')),
    ('ROWBACKGROUNDS',(0,1), (-1,-1), [colors.white, colors.HexColor('#f2f2f2')]),
    ('COLBACKGROUNDS',(0,0), (-1,-1), [colors.lightblue, colors.white]),

    # ── Lines/Borders ─────────────────────────────────────
    # Syntax: (CMD, start, end, thickness, color)
    ('BOX',           (0,0), (-1,-1), 1.5, colors.black),   # outer border
    ('INNERGRID',     (0,0), (-1,-1), 0.25, colors.grey),   # all inner lines
    ('GRID',          (0,0), (-1,-1), 0.5, colors.black),   # BOX + INNERGRID
    ('LINEABOVE',     (0,1), (-1,1),  1,   colors.black),
    ('LINEBELOW',     (0,-1),(-1,-1), 2,   colors.green),
    ('LINEBEFORE',    (1,0), (1,-1),  0.5, colors.blue),
    ('LINEAFTER',     (2,0), (2,-1),  0.5, colors.red),

    # ── Spanning ──────────────────────────────────────────
    ('SPAN',          (0,0), (2,0)),   # merge cells (0,0) through (2,0)
    # Note: merged cells must have empty strings in non-lead positions

    # ── Misc ──────────────────────────────────────────────
    ('NOSPLIT',       (0,0), (-1,0)),              # prevent splitting this range
    ('ROUNDEDCORNERS',[5, 5, 5, 5]),               # corner radii [TL, TR, BL, BR]
]))
```

### Table Tips[^14][^13]

```python
# Cells can contain Flowables (Paragraphs, Images, even nested Tables)
data = [
    [Paragraph("<b>Header</b>", styles['Normal']), "Value"],
]

# Long tables: use LongTable for speed (greedy column width algorithm)
from reportlab.platypus import LongTable
t = LongTable(data, repeatRows=1)

# Access/override column width after creation
t._argW[^2] = 1.5*inch
```

***

## Common Flowables

```python
from reportlab.platypus import (
    Spacer, HRFlowable, PageBreak, KeepTogether,
    Image, ListFlowable, ListItem
)

# ── Spacer ─────────────────────────────────────────────────
Spacer(1, 12)                    # width ignored; height=12 pt vertical gap

# ── Horizontal Rule ────────────────────────────────────────
HRFlowable(
    width="100%",                # or absolute points
    thickness=1,
    color=colors.grey,
    spaceAfter=6,
    spaceBefore=6,
    dash=None,                   # e.g. (3, 3) for dashed
)

# ── Page Break ─────────────────────────────────────────────
PageBreak()                      # force new page in story

# ── Keep Together ──────────────────────────────────────────
# Prevent a group of flowables from being split across pages
KeepTogether([
    Paragraph("Header", styles['Heading2']),
    Paragraph("Content that should stay with header.", styles['Normal']),
])

# ── Image ──────────────────────────────────────────────────
img = Image("logo.png", width=2*inch, height=1*inch)
img.hAlign = 'CENTER'            # 'LEFT' | 'CENTER' | 'RIGHT'

# ── Ordered / Bulleted Lists ───────────────────────────────
story.append(ListFlowable([
    ListItem(Paragraph("First item", styles['Normal']), bulletColor=colors.blue),
    ListItem(Paragraph("Second item", styles['Normal'])),
    ListItem(Paragraph("Third item", styles['Normal'])),
], bulletType='bullet',          # 'bullet' | '1' | 'a' | 'A' | 'i' | 'I'
   bulletFontName='Helvetica',
   bulletFontSize=10,
   leftIndent=20,
))
```

***

## Custom Flowables[^15]

Subclass `Flowable` and implement `wrap()` + `draw()` to create reusable custom elements:

```python
from reportlab.platypus.flowables import Flowable

class ColorBox(Flowable):
    """A filled color box with centered label."""
    def __init__(self, width, height, color, label=""):
        self.box_width = width
        self.box_height = height
        self.color = color
        self.label = label

    def wrap(self, available_width, available_height):
        return (self.box_width, self.box_height)   # reported size

    def draw(self):
        self.canv.setFillColor(self.color)
        self.canv.rect(0, 0, self.box_width, self.box_height, fill=1)
        self.canv.setFillColor(colors.white)
        self.canv.setFont("Helvetica-Bold", 10)
        self.canv.drawCentredString(
            self.box_width / 2, self.box_height / 2 - 5, self.label
        )
```

***

## ReportLab Graphics (Charts)

ReportLab includes a full charting library — charts are `Flowable` objects you can drop directly into a story.[^16]

```python
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics import renderPDF

# ── Bar Chart ──────────────────────────────────────────────
d = Drawing(400, 200)
chart = VerticalBarChart()
chart.x = 50
chart.y = 50
chart.width = 300
chart.height = 125
chart.data = [[10, 20, 30, 40], [15, 25, 35, 45]]
chart.categoryAxis.categoryNames = ['Q1', 'Q2', 'Q3', 'Q4']
chart.bars.fillColor = colors.HexColor('#3498db')
chart.bars[^1].fillColor = colors.HexColor('#e74c3c')
d.add(chart)
story.append(d)   # Drop into Platypus story

# ── Pie Chart ──────────────────────────────────────────────
d2 = Drawing(200, 200)
pie = Pie()
pie.x = 50
pie.y = 50
pie.width = 100
pie.height = 100
pie.data = [30, 25, 20, 15, 10]
pie.labels = ['A', 'B', 'C', 'D', 'E']
pie.slices.fillColor = colors.HexColor('#2ecc71')
d2.add(pie)

# Render Drawing directly onto canvas (not story)
renderPDF.draw(d, canvas_obj, x=50, y=100)
```

***

## Barcodes[^17]

```python
from reportlab.graphics.barcode import code128, qr

# Code 128 barcode
barcode = code128.Code128(
    "ABC123",
    barHeight=20*mm,
    barWidth=1.5,
    humanReadable=True,
    fontSize=8,
)
barcode.drawOn(c, x=30*mm, y=100*mm)   # Canvas drawing
# or add to story directly: story.append(barcode)

# QR code
qr_code = qr.QrCodeWidget("https://example.com")
bounds = qr_code.getBounds()
d = Drawing(bounds[^2]-bounds, bounds[^3]-bounds[^1])
d.add(qr_code)
story.append(d)
```

***

## Multi-Column Layout[^1]

```python
from reportlab.platypus import BaseDocTemplate, PageTemplate, Frame
from reportlab.lib.units import mm

doc = BaseDocTemplate("twocol.pdf", pagesize=A4)
page_w, page_h = A4
margin = 15*mm
col_gap = 8*mm
col_w = (page_w - 2*margin - col_gap) / 2
col_h = page_h - 2*margin

left_frame  = Frame(margin,          margin, col_w, col_h, id='left')
right_frame = Frame(margin+col_w+col_gap, margin, col_w, col_h, id='right')

template = PageTemplate(id='TwoCol', frames=[left_frame, right_frame])
doc.addPageTemplates([template])
doc.build(story)
```

***

## Drawing on Canvas Inside Platypus

Sometimes you need to draw fixed elements (watermarks, logos) while also using flowing content. Use `onPage`/`onLaterPages` callbacks on `SimpleDocTemplate`, or manually render flowables onto a canvas.[^18]

```python
# Render a Platypus Flowable manually onto a Canvas
paragraph = Paragraph("Fixed text", styles['Normal'])
paragraph.wrapOn(c, available_width, available_height)
paragraph.drawOn(c, x, y)

table = Table(data)
table.wrapOn(c, page_width, page_height)
table.drawOn(c, x, y)

# Watermark pattern (draw behind content)
def add_watermark(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica-Bold", 60)
    canvas.setFillColor(colors.Color(0.85, 0.85, 0.85, alpha=0.4))
    canvas.translate(A4/2, A4[^1]/2)
    canvas.rotate(45)
    canvas.drawCentredString(0, 0, "DRAFT")
    canvas.restoreState()

doc.build(story, onFirstPage=add_watermark, onLaterPages=add_watermark)
```

***

## Output to Non-File Targets

```python
import io

# In-memory buffer (e.g., for web frameworks like Flask/Django)
buffer = io.BytesIO()
c = canvas.Canvas(buffer, pagesize=A4)
# ... draw ...
c.save()
pdf_bytes = buffer.getvalue()

# Flask response
from flask import make_response
response = make_response(pdf_bytes)
response.headers['Content-Type'] = 'application/pdf'
response.headers['Content-Disposition'] = 'attachment; filename="report.pdf"'
return response

# Django response
from django.http import HttpResponse
response = HttpResponse(content_type='application/pdf')
response['Content-Disposition'] = 'attachment; filename="report.pdf"'
doc = SimpleDocTemplate(response, pagesize=A4)
doc.build(story)
return response
```

***

## Complete Working Example

A minimal but production-quality PDF with title, styled paragraphs, table, image, header, and footer — all in one file.[^2][^1]

```python
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER

W, H = A4

def header_footer(c, doc):
    c.saveState()
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.grey)
    c.drawString(20*mm, H - 12*mm, "Acme Corp — Confidential")
    c.drawRightString(W - 20*mm, 10*mm, f"Page {c.getPageNumber()}")
    c.restoreState()

def build_pdf(path="complete_example.pdf"):
    doc = SimpleDocTemplate(path, pagesize=A4,
                            topMargin=25*mm, bottomMargin=20*mm,
                            leftMargin=20*mm, rightMargin=20*mm)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle('CenteredTitle',
                              parent=styles['Title'],
                              alignment=TA_CENTER,
                              textColor=colors.HexColor('#2c3e50')))

    story = []

    # Title
    story.append(Paragraph("Q4 Performance Report", styles['CenteredTitle']))
    story.append(Spacer(1, 6*mm))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#2c3e50')))
    story.append(Spacer(1, 4*mm))

    # Body text
    story.append(Paragraph("Executive Summary", styles['Heading1']))
    story.append(Paragraph(
        "Revenue exceeded targets by <b>12%</b> this quarter, driven by strong performance "
        "in the <i>cloud services</i> division. Customer retention reached an all-time high.",
        styles['BodyText']
    ))
    story.append(Spacer(1, 4*mm))

    # Table
    data = [
        ["Division",    "Target ($M)", "Actual ($M)", "Variance"],
        ["Cloud",       "45.0",        "52.3",        "+16.2%"],
        ["On-Premise",  "30.0",        "28.7",        "-4.3%"],
        ["Services",    "20.0",        "21.5",        "+7.5%"],
        ["Total",       "95.0",        "102.5",       "+7.9%"],
    ]
    t = Table(data, colWidths=[60*mm, 35*mm, 35*mm, 30*mm])
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,0),  colors.HexColor('#2c3e50')),
        ('TEXTCOLOR',     (0,0), (-1,0),  colors.white),
        ('FONT',          (0,0), (-1,0),  'Helvetica-Bold', 10),
        ('FONT',          (0,1), (-1,-1), 'Helvetica', 9),
        ('ROWBACKGROUNDS',(0,1), (-1,-2), [colors.white, colors.HexColor('#ecf0f1')]),
        ('BACKGROUND',    (0,-1),(-1,-1), colors.HexColor('#bdc3c7')),
        ('FONT',          (0,-1),(-1,-1), 'Helvetica-Bold', 9),
        ('ALIGN',         (1,0), (-1,-1), 'RIGHT'),
        ('ALIGN',         (0,0), (0,-1),  'LEFT'),
        ('GRID',          (0,0), (-1,-1), 0.5, colors.HexColor('#95a5a6')),
        ('TOPPADDING',    (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(t)

    doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)

if __name__ == "__main__":
    build_pdf()
```

***

## Quick Troubleshooting

| Problem | Likely Cause | Fix |
|---------|-------------|-----|
| `LayoutError: Flowable too large` | Content wider/taller than frame | Reduce font size, margins, or set `splitByRow=1` on tables |
| Text cut off / missing | Y-coordinate off-screen (remember: origin is **bottom-left**) | Check coordinates; `y = height - offset` for top-down |
| Images blurry in PDF | Low source resolution | Use high-res images; ReportLab embeds at native resolution |
| Custom font shows as Helvetica | Font not registered before use | Call `pdfmetrics.registerFont()` before building story |
| Table cell content overflows | Fixed row height too small | Set `rowHeights=None` to auto-size, or increase padding |
| PDF not saved | `c.save()` missing | Always call `canvas.save()` as the last step |
| Multi-page doc stops at 1 page | `showPage()` not called between pages in Canvas API | Add `c.showPage()` before starting new content |

***

## Key Coordinate Reminders

```
┌──────────────────────────────────────────────┐
│  (0, height)              (width, height)    │
│  top-left                 top-right          │
│                                              │
│       PDF Page                               │
│                                              │
│  (0, 0)                   (width, 0)         │
│  bottom-left ← ORIGIN     bottom-right      │
└──────────────────────────────────────────────┘

For A4: width=595pt, height=842pt
"Draw at top" → y = height - top_margin
"Draw at bottom" → y = bottom_margin
```

---

## References

1. [How to Generate PDF Using ReportLab in Python ...](https://pdfnoodle.com/blog/how-to-generate-pdf-from-html-using-reportlab-in-python) - Learn how to generate PDFs from HTML using ReportLab in Python. Step-by-step example covering setup,...

2. [Create PDF Documents in Python With ReportLab](https://pythonassets.com/posts/create-pdf-documents-in-python-with-reportlab/) - How to write PDF documents (text, images, graphics, grids, and more) from Python using the ReportLab...

3. [Producing PDFs in landscape orientation with ReportLab](https://stackoverflow.com/questions/15490710/producing-pdfs-in-landscape-orientation-with-reportlab) - I am working on a Python script that produces a PDF report using ReportLab. I need to produce the pa...

4. [src/reportlab/lib/pagesizes.py](https://fossies.org/linux/reportlab/src/reportlab/lib/pagesizes.py)

5. [How to change text/font color in reportlab.pdfgen - Stack Overflow](https://stackoverflow.com/questions/9855445/how-to-change-text-font-color-in-reportlab-pdfgen) - Below is an example I prepared to show better how to style a text, draw a line, and draw a rectangle...

6. [ReportLab UTF-8 characters with registered fonts - Stack Overflow](https://stackoverflow.com/questions/25403999/reportlab-utf-8-characters-with-registered-fonts) - I'm using ReportLab for pdf generation and I'm having some problem with representing the utf-8 chara...

7. [Reportlab and fonts - Help - NixOS Discourse](https://discourse.nixos.org/t/reportlab-and-fonts/8700) - Reportlab's canvas.getAvailableFonts() seems to be aware of ['Courier', 'Courier-Bold', 'Courier-Bol...

8. [[PDF] ReportLab API Reference](https://www.reportlab.com/docs/reportlab-reference.pdf) - This is the API reference for the ReportLab library. All public classes, functions and methods are d...

9. [Add image to existing PDF file in Python using reportlab](https://python.code-maven.com/add-image-to-existing-pdf-file-in-python) - Create PDF file in Python using the open source Python library from Reportlab. Add several pages to ...

10. [Chapter 5: Platypus - ReportLab Docs](https://docs.reportlab.com/reportlab/userguide/ch5_platypus/) - A Platypus story consists of a sequence of basic elements called Flowables and these elements drive ...

11. [Chapter 6: Paragraphs - ReportLab Docs](https://docs.reportlab.com/reportlab/userguide/ch6_paragraphs/) - The < font > tag can be used to change the font name, size and text color for any substring within t...

12. [add paragraph style reportlab](https://stackoverflow.com/questions/38557119/add-paragraph-style-reportlab) - I'm trying to set a paragraph style to report lab, I defined a style here: def stylesheet(): styles=...

13. [Chapter 7: Tables](https://docs.reportlab.com/reportlab/userguide/ch7_tables/)

14. [Reportlab Tables - Creating Tables in PDFs with Python](https://www.blog.pythonlibrary.org/2010/09/21/reportlab-tables-creating-tables-in-pdfs-with-python/) - Back in March of this year, I wrote a simple tutorial on Reportlab, a handy 3rd party Python package...

15. [Chapter 10: Writing Your Own flowables - ReportLab Docs](https://docs.reportlab.com/reportlab/userguide/ch10_writing_own_flowables/) - Flowables are intended to be an open standard for creating reusable report content, and you can easi...

16. [Chapter 11: Graphics - ReportLab Docs](https://docs.reportlab.com/reportlab/userguide/ch11_graphics/) - A fully integrated part of the ReportLab toolkit that allows you to use its powerful charting and gr...

17. [Python: Code example for setting page size to A4 in Reportlab](https://copyprogramming.com/howto/reportlab-page-size-a4-code-example) - Page size issue PDF creation of barcodes using reportlab, ReportLab: LayoutError when content of cel...

18. [Reportlab: Mixing Fixed Content and Flowables - DZone](https://dzone.com/articles/reportlab-mixing-fixed-content) - First off we create a Canvas object that we can use without our LetterMaker class. We also create a ...

