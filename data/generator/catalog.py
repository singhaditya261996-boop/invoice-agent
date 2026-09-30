"""Fictional supplier master and item catalogues for the synthetic dataset.

All names are invented. UK conventions: GBP, VAT at 20%, Net 30/60 terms.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    description: str
    price: tuple[float, float]  # unit price range, GBP
    qty: tuple[int, int]


@dataclass(frozen=True)
class Supplier:
    supplier_id: str
    name: str  # legal name as held on the PO
    abbr: str
    payment_terms: str
    invoice_format: str  # supplier's own numbering scheme; fields: abbr, n, yyyy, yy
    trading_name: str  # alternative trading name (E08 scenario)
    region: str  # used to build a subsidiary name (E08 scenario)
    goods: bool  # physical goods (eligible for partial delivery, E03)
    items: tuple[Item, ...]
    retainer: Item | None = None  # fixed monthly service, used for recurring-invoice edge cases

    @property
    def terms_days(self) -> int:
        return int(self.payment_terms.split()[1])


# Distinct invoice-number formats simulate real-world variation (PRD §2.3).
F_INV = "INV-{abbr}-{n:05d}"
F_SLASH = "{abbr}/{yyyy}/{n:04d}"
F_NUMERIC = "{n:06d}"
F_COMPACT = "{abbr}{yy}-{n:04d}"
F_SI = "SI-{n:07d}"

SUPPLIERS: tuple[Supplier, ...] = (
    Supplier("SUP-00342", "Meridian Office Supplies Ltd", "MOS", "Net 30", F_INV, "Meridian Workplace", "Northern", True, (
        Item("A4 copier paper 80gsm, box of 5 reams", (18, 32), (10, 200)),
        Item("Black ballpoint pens, box of 50", (6, 14), (5, 60)),
        Item("Laser toner cartridge, black, high yield", (45, 120), (2, 30)),
        Item("Lever arch files, pack of 10", (12, 25), (5, 50)),
        Item("Sticky notes 76x76mm, pack of 12", (5, 11), (10, 80)),
    )),
    Supplier("SUP-00417", "Harrowgate Stationery Co Ltd", "HSC", "Net 30", F_NUMERIC, "Harrowgate Paper Goods", "Yorkshire", True, (
        Item("Spiral notebooks A5, pack of 10", (9, 19), (5, 80)),
        Item("Envelopes C4 self-seal, box of 250", (22, 41), (2, 40)),
        Item("Whiteboard markers, assorted, pack of 12", (8, 16), (5, 50)),
        Item("Desk organiser set", (15, 40), (5, 40)),
    )),
    Supplier("SUP-01188", "Wychwood Furniture Ltd", "WFL", "Net 60", F_SLASH, "Wychwood Interiors", "Midlands", True, (
        Item("Ergonomic task chair", (140, 420), (2, 40)),
        Item("Height-adjustable desk 1600mm", (320, 780), (2, 30)),
        Item("Four-drawer steel filing cabinet", (180, 390), (1, 15)),
        Item("Meeting table, 8-seater", (650, 1500), (1, 4)),
        Item("Acoustic desk screen", (60, 160), (4, 40)),
    )),
    Supplier("SUP-00893", "Blackthorn IT Solutions Ltd", "BIT", "Net 30", F_INV, "Blackthorn Technology", "Scotland", True, (
        Item("14-inch business laptop, 16GB RAM", (720, 1450), (2, 30)),
        Item("27-inch QHD monitor", (190, 380), (2, 50)),
        Item("USB-C docking station", (110, 240), (2, 50)),
        Item("Wireless keyboard and mouse set", (28, 75), (5, 80)),
        Item("Rack-mount network switch, 48-port", (900, 2600), (1, 6)),
    )),
    Supplier("SUP-02051", "Redmere Software Ltd", "RSL", "Net 30", F_COMPACT, "Redmere Cloud", "Wales", False, (
        Item("Project management suite, annual licence per seat", (80, 240), (10, 150)),
        Item("Endpoint protection licence, per device, 12 months", (18, 45), (20, 400)),
        Item("Implementation support, per day", (650, 1100), (1, 15)),
        Item("Premium support tier, 12 months", (1500, 9000), (1, 1)),
    )),
    Supplier("SUP-00764", "Kestrel Digital Services Ltd", "KDS", "Net 30", F_SI, "Kestrel Managed IT", "Southern", False, (
        Item("On-site engineer, per day", (450, 850), (1, 20)),
        Item("Network cabling installation, per point", (85, 160), (10, 120)),
        Item("Laptop imaging and deployment, per device", (35, 70), (5, 80)),
    ), retainer=Item("Managed service desk, monthly", (2500, 9000), (1, 1))),
    Supplier("SUP-01322", "Tamarind Telecoms Ltd", "TTL", "Net 30", F_NUMERIC, "Tamarind Connect", "Northern", False, (
        Item("SIP trunk channels, monthly", (8, 20), (10, 100)),
        Item("Leased line installation", (900, 2400), (1, 2)),
        Item("Desk phone handset", (60, 140), (5, 60)),
    ), retainer=Item("Mobile airtime bundle, per user, monthly", (12, 35), (20, 200))),
    Supplier("SUP-00129", "Northvale Facilities Management plc", "NFM", "Net 60", F_SLASH, "Northvale Property Services", "Northern", False, (
        Item("Planned preventative maintenance visit", (280, 900), (1, 12)),
        Item("Reactive maintenance call-out", (120, 380), (1, 20)),
        Item("HVAC filter replacement, per unit", (35, 90), (4, 60)),
    )),
    Supplier("SUP-00655", "Cobbleford Cleaning Services Ltd", "CCS", "Net 30", F_COMPACT, "Cobbleford Hygiene", "Midlands", False, (
        Item("Washroom consumables restock", (120, 480), (1, 12)),
        Item("Window cleaning, external, per visit", (350, 1200), (1, 4)),
        Item("Carpet deep clean, per floor", (400, 1600), (1, 6)),
    ), retainer=Item("Office cleaning service, monthly", (1800, 7500), (1, 1))),
    Supplier("SUP-01874", "Calder Valley Guarding Ltd", "CVG", "Net 30", F_INV, "Calder Security", "Yorkshire", False, (
        Item("Security guarding, per hour", (18, 32), (40, 600)),
        Item("Keyholding and alarm response, per call-out", (65, 150), (1, 12)),
    ), retainer=Item("Mobile patrol contract, monthly", (900, 3200), (1, 1))),
    Supplier("SUP-00988", "Elmstead Waste Solutions Ltd", "EWS", "Net 30", F_NUMERIC, "Elmstead Recycling", "Southern", False, (
        Item("General waste collection, per lift", (35, 90), (10, 120)),
        Item("Confidential shredding, per console", (8, 18), (10, 80)),
        Item("WEEE disposal, per item", (6, 25), (10, 150)),
    ), retainer=Item("Mixed recycling contract, monthly", (400, 1400), (1, 1))),
    Supplier("SUP-02210", "Greystone Electrical Services Ltd", "GES", "Net 30", F_SI, "Greystone Power", "Wales", False, (
        Item("Emergency lighting test and certification", (250, 850), (1, 4)),
        Item("Fixed wire testing, per circuit", (6, 15), (50, 600)),
        Item("PAT testing, per appliance", (1.2, 3.5), (50, 800)),
    )),
    Supplier("SUP-00531", "Ashdown Catering Ltd", "ACL", "Net 30", F_INV, "Ashdown Kitchen", "Southern", False, (
        Item("Working lunch platter, per head", (8, 18), (20, 250)),
        Item("Hospitality catering, client event, per head", (28, 75), (20, 150)),
        Item("Hot beverage supplies", (180, 650), (1, 3)),
    )),
    Supplier("SUP-01467", "Pennine Fresh Foods Ltd", "PFF", "Net 30", F_COMPACT, "Pennine Produce", "Yorkshire", True, (
        Item("Fresh fruit box, weekly delivery", (25, 60), (4, 20)),
        Item("Bottled spring water, case of 24", (6, 12), (10, 120)),
        Item("Milk, 2 litre, crate of 12", (14, 24), (4, 40)),
    )),
    Supplier("SUP-00276", "Larkspur Creative Agency Ltd", "LCA", "Net 60", F_SLASH, "Larkspur Studio", "Southern", False, (
        Item("Brand campaign creative development", (3500, 18000), (1, 1)),
        Item("Photography, half-day shoot", (450, 1100), (1, 4)),
        Item("Copywriting, per day", (400, 750), (1, 10)),
    ), retainer=Item("Social media content package, monthly", (1200, 4800), (1, 1))),
    Supplier("SUP-01733", "Brightwater Print & Media Ltd", "BPM", "Net 30", F_NUMERIC, "Brightwater Print", "Scotland", True, (
        Item("Printed brochures, A4 16pp, per 100", (85, 240), (5, 50)),
        Item("Pull-up exhibition banner", (65, 180), (2, 15)),
        Item("Business cards, per 500", (18, 45), (5, 40)),
    )),
    Supplier("SUP-00815", "Thistledown Consulting LLP", "TDC", "Net 60", F_INV, "Thistledown Advisory", "Scotland", False, (
        Item("Senior consultant, per day", (950, 1650), (2, 25)),
        Item("Consultant, per day", (600, 950), (2, 40)),
        Item("Workshop facilitation", (1500, 4000), (1, 3)),
    )),
    Supplier("SUP-02396", "Oakridge Advisory Partners LLP", "OKA", "Net 60", F_SLASH, "Oakridge Partners", "Midlands", False, (
        Item("Process review engagement, fixed fee", (6000, 24000), (1, 1)),
        Item("Analyst, per day", (450, 700), (2, 30)),
    )),
    Supplier("SUP-01059", "Marlow & Finch Legal Services LLP", "MFL", "Net 30", F_COMPACT, "Marlow Finch Solicitors", "Southern", False, (
        Item("Commercial contracts advice, per hour", (180, 420), (5, 60)),
        Item("Contract review, fixed fee", (1200, 5000), (1, 2)),
    )),
    Supplier("SUP-00447", "Fenmoor Freight Ltd", "FMF", "Net 30", F_SI, "Fenmoor Logistics", "Eastern", False, (
        Item("Pallet delivery, next day, per pallet", (45, 120), (2, 60)),
        Item("Same-day courier, per consignment", (35, 140), (2, 40)),
    )),
    Supplier("SUP-01590", "Saltmarsh Logistics Ltd", "SML", "Net 30", F_INV, "Saltmarsh Distribution", "Eastern", False, (
        Item("Warehouse storage, per pallet per week", (3, 9), (20, 400)),
        Item("Pick and pack, per order line", (0.6, 1.8), (200, 3000)),
    )),
    Supplier("SUP-00702", "Brackenfield Packaging Ltd", "BPL", "Net 30", F_NUMERIC, "Brackenfield Boxes", "Midlands", True, (
        Item("Double-wall cardboard boxes, pack of 25", (18, 42), (10, 200)),
        Item("Stretch wrap film, 500mm roll", (9, 22), (10, 120)),
        Item("Void fill paper, per roll", (22, 48), (5, 60)),
    )),
    Supplier("SUP-01945", "Hollins Engineering Supplies Ltd", "HES", "Net 60", F_SLASH, "Hollins Industrial", "Northern", True, (
        Item("Nitrile safety gloves, box of 100", (6, 14), (10, 150)),
        Item("Hi-vis vest, class 2", (3, 9), (20, 200)),
        Item("Assorted fasteners kit", (25, 70), (2, 40)),
        Item("Cordless drill set 18V", (95, 260), (1, 10)),
    )),
    Supplier("SUP-00368", "Quayside Events Ltd", "QEL", "Net 30", F_COMPACT, "Quayside Venues", "Wales", False, (
        Item("Venue hire, per day", (1200, 6500), (1, 3)),
        Item("AV equipment package, per day", (650, 2800), (1, 3)),
        Item("Event staffing, per hour", (18, 35), (20, 200)),
    )),
    Supplier("SUP-02133", "Silverbirch Recruitment Ltd", "SRL", "Net 30", F_INV, "Silverbirch Talent", "Southern", False, (
        Item("Temporary AP clerk, per hour", (16, 28), (35, 400)),
        Item("Permanent placement fee", (4500, 14000), (1, 1)),
    )),
)

COST_CENTRES = (
    "CC-FIN-001", "CC-IT-002", "CC-OPS-003", "CC-MKTG-004",
    "CC-HR-005", "CC-FAC-006", "CC-SALES-007", "CC-LEGAL-008",
)
APPROVERS = ("J. Reynolds", "S. Okafor", "M. Clarke", "R. Hughes", "L. Nowak", "D. Fraser")
RECEIVERS = ("A. Patel", "K. Brennan", "T. Adeyemi", "H. Walsh", "C. Mistry", "P. Doyle", "E. Lindqvist", "G. Bamford")

BENIGN_GR_NOTES = (
    "", "", "", "", "Delivered in full", "Signed for at reception", "Received in good condition",
    "Delivered to loading bay 2", "Checked against delivery note", "Service completed as scheduled",
)
SHORTFALL_GR_NOTES = (
    "Partial delivery: {k} x {item} on backorder",
    "{k} units returned, damaged in transit",
    "Box {box} damaged, returned {k} units",
    "Short delivery, {k} missing from consignment. Supplier notified.",
)
# Shortfall described only in free text; structured quantities were not amended.
NOTES_ONLY_GR_NOTES = (
    "Returned {k} x {item} to supplier (damaged packaging)",
    "Box {box} damaged, {k} units sent back with driver",
    "{k} units rejected at goods-in, faulty. Collection arranged.",
)
