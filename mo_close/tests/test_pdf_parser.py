from decimal import Decimal
from pathlib import Path

from django.test import SimpleTestCase

from mo_close.pdf_parser import PackingListParseError, parse_packing_list

SAMPLE = Path(__file__).parent / "fixtures" / "packing_list_S04743.pdf"


class PackingListParserTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with SAMPLE.open("rb") as fh:
            cls.result = parse_packing_list(fh)

    def test_header_information(self):
        h = self.result.header
        self.assertEqual(h["sold_to"], "Wellzijn BV\nValkenswaardseweg 29A\nLeende 5595 XB\nNetherlands")
        self.assertEqual(h["tel"], "+31 40 206 2955")
        self.assertEqual(h["fax"], "")
        self.assertEqual(h["attn"], "")
        self.assertEqual(h["date"], "15-Oct-2026")
        self.assertEqual(h["invoice_no"], "S04743")
        self.assertEqual(h["container_no"], "PACK0000856")
        self.assertEqual(h["seal_no"], "S04743")
        self.assertEqual(h["destination"], "NL")

    def test_all_rows(self):
        lines = self.result.lines
        self.assertEqual(len(lines), 23)
        first = lines[0]
        self.assertEqual(first["external_code"], "NRNS-60NS-BL-Z-C")
        self.assertEqual(first["description"], "Nordex S Black 3H.E 6,0kW NS Trendline 3P-1P")
        self.assertEqual(first["um"], "Piece")
        self.assertEqual(first["gross_weight"], Decimal("141.28"))
        self.assertEqual(first["cbm"], Decimal("0.960"))
        self.assertEqual(first["qty"], Decimal("10"))
        self.assertEqual(sum(1 for l in lines if l["external_code"] == "NRNS-90NS-BL-Z-C"), 10)
        self.assertEqual(lines[-1]["external_code"], "NRNF-150NS-BL-Z")
        self.assertEqual([l["line_no"] for l in lines], list(range(1, 24)))

    def test_grand_total_and_no_warnings(self):
        t = self.result.totals
        self.assertEqual(t["qty"], Decimal("45"))
        self.assertEqual(t["packages"], Decimal("23"))
        self.assertEqual(t["gross_weight"], Decimal("815.38"))
        self.assertEqual(self.result.warnings, [])

    def test_not_a_pdf(self):
        import io

        with self.assertRaises(PackingListParseError):
            parse_packing_list(io.BytesIO(b"hello"))
