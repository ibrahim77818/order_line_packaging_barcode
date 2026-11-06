# -*- coding: utf-8 -*-
import logging
import time

from odoo import Command, fields
from odoo.tests import Form, TransactionCase, tagged

_logger = logging.getLogger(__name__)

BOX = 'OLPB-BOX-0006'        # Box of 6       (product packaging: sales + purchase)
CARTON = 'OLPB-CTN-0024'     # Carton of 24   (product packaging: sales + purchase)
PALLET = 'OLPB-PAL-0120'     # Pallet of 120  (vendor unit only: purchase)
UNIT = 'OLPB-UNIT-0001'      # product variant barcode


@tagged('post_install', '-at_install', 'olpb')
class TestOrderLinePackagingBarcode(TransactionCase):
    """Odoo 19: a packaging is a unit of measure (uom.uom) listed on the product
    (uom_ids); its barcode is a product.uom record. A packaging scan puts the
    line in that unit and adds 1; a product scan adds 1 product unit."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.company = cls.env.company
        cls.company.write({
            'sale_packaging_barcode_scan': True,
            'purchase_packaging_barcode_scan': True,
        })
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        Uom = cls.env['uom.uom']
        cls.uom_box = Uom.create({'name': 'OLPB Box of 6', 'relative_factor': 6.0, 'relative_uom_id': cls.uom_unit.id})
        cls.uom_carton = Uom.create({'name': 'OLPB Carton of 24', 'relative_factor': 24.0, 'relative_uom_id': cls.uom_unit.id})
        cls.uom_pallet = Uom.create({'name': 'OLPB Pallet of 120', 'relative_factor': 120.0, 'relative_uom_id': cls.uom_unit.id})

        cls.user = cls.env['res.users'].create({
            'name': 'OLPB Order Manager',
            'login': 'olpb_manager',
            'email': 'olpb_manager@example.com',
            'company_id': cls.company.id,
            'company_ids': [Command.set(cls.company.ids)],
            'group_ids': [Command.set([
                cls.env.ref('base.group_user').id,
                cls.env.ref('sales_team.group_sale_manager').id,
                cls.env.ref('purchase.group_purchase_manager').id,
                cls.env.ref('product.group_product_pricelist').id,
                cls.env.ref('uom.group_uom').id,
                cls.env.ref('sale.group_warning_sale').id,
            ])],
        })

        cls.customer = cls.env['res.partner'].create({'name': 'OLPB Customer'})
        cls.vendor = cls.env['res.partner'].create({'name': 'OLPB Vendor'})
        cls.other_vendor = cls.env['res.partner'].create({'name': 'OLPB Pallet Vendor'})

        cls.product = cls.env['product.product'].create({
            'name': 'OLPB Water Bottle',
            'type': 'consu',
            'barcode': UNIT,
            'list_price': 10.0,
            'standard_price': 5.0,
            'uom_id': cls.uom_unit.id,
            'uom_ids': [Command.set([cls.uom_box.id, cls.uom_carton.id])],  # packagings
            'sale_ok': True,
            'purchase_ok': True,
            'taxes_id': [Command.clear()],
            'supplier_taxes_id': [Command.clear()],
        })
        ProductUom = cls.env['product.uom']
        for uom, barcode in ((cls.uom_box, BOX), (cls.uom_carton, CARTON), (cls.uom_pallet, PALLET)):
            ProductUom.create({'product_id': cls.product.id, 'uom_id': uom.id, 'barcode': barcode})

        # Quantity break: 9.00 per unit from 24 units (list price is 10.00).
        cls.pricelist = cls.env['product.pricelist'].create({
            'name': 'OLPB Pricelist',
            'currency_id': cls.company.currency_id.id,
            'item_ids': [Command.create({
                'applied_on': '0_product_variant',
                'product_id': cls.product.id,
                'compute_price': 'fixed',
                'fixed_price': 9.0,
                'min_quantity': 24.0,
            })],
        })
        # Vendor price: 4.00 per unit from 12 units; below that Odoo uses the
        # cost (5.00). Its min quantity is also what Odoo's product onchange
        # would force on a PO line (12 Units).
        Seller = cls.env['product.supplierinfo']
        Seller.create({
            'partner_id': cls.vendor.id,
            'product_tmpl_id': cls.product.product_tmpl_id.id,
            'product_uom_id': cls.uom_unit.id,
            'price': 4.0,
            'min_qty': 12.0,
            'currency_id': cls.company.currency_id.id,
        })
        # Another vendor sells by the pallet: makes the pallet a purchase unit.
        Seller.create({
            'partner_id': cls.other_vendor.id,
            'product_tmpl_id': cls.product.product_tmpl_id.id,
            'product_uom_id': cls.uom_pallet.id,
            'price': 420.0,
            'min_qty': 1.0,
            'currency_id': cls.company.currency_id.id,
        })

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _new_sale_order(self, **vals):
        values = {
            'partner_id': self.customer.id,
            'company_id': self.company.id,
            'pricelist_id': self.pricelist.id,
            'state': 'draft',
            'date_order': fields.Datetime.now(),
        }
        values.update(vals)
        return self.env['sale.order'].new(values)

    def _new_purchase_order(self, **vals):
        values = {
            'partner_id': self.vendor.id,
            'company_id': self.company.id,
            'currency_id': self.company.currency_id.id,
            'state': 'draft',
            'date_order': fields.Datetime.now(),
        }
        values.update(vals)
        return self.env['purchase.order'].new(values)

    def _sale_form(self):
        so_form = Form(self.env['sale.order'].with_user(self.user))
        so_form.partner_id = self.customer
        so_form.pricelist_id = self.pricelist
        return so_form

    def _purchase_form(self):
        po_form = Form(self.env['purchase.order'].with_user(self.user))
        po_form.partner_id = self.vendor
        return po_form

    def _resolve(self, barcode, usage='sale', company=None):
        return self.env['product.uom']._olpb_resolve_barcode(
            barcode, company or self.company, usage)

    # ------------------------------------------------------------------
    # 1. Settings
    # ------------------------------------------------------------------
    def test_01_settings_default_off_and_independent(self):
        company = self.env['res.company'].create({'name': 'OLPB Fresh Company'})
        self.assertFalse(company.sale_packaging_barcode_scan)
        self.assertFalse(company.purchase_packaging_barcode_scan)

        settings = self.env['res.config.settings'].with_company(company).create({
            'sale_packaging_barcode_scan': True,
        })
        self.assertEqual(settings.company_id, company)
        self.assertTrue(company.sale_packaging_barcode_scan)
        self.assertFalse(company.purchase_packaging_barcode_scan,
                         "Sales and Purchase switches must be independent")

    def test_02_disabled_feature_does_nothing(self):
        self.company.sale_packaging_barcode_scan = False
        order = self._new_sale_order()
        self.assertFalse(order.packaging_barcode_enabled)
        res = order._olpb_scan(BOX)
        self.assertIn('warning', res)
        self.assertFalse(order.order_line)

        # Purchase is still enabled.
        po = self._new_purchase_order()
        self.assertTrue(po.packaging_barcode_enabled)
        po._olpb_scan(BOX)
        self.assertEqual(len(po.order_line), 1)

    # ------------------------------------------------------------------
    # 2. Resolution engine
    # ------------------------------------------------------------------
    def test_10_resolution_priority(self):
        res = self._resolve(BOX)
        self.assertFalse(res['error'])
        self.assertEqual(res['product'], self.product)
        self.assertEqual(res['uom'], self.uom_box)

        res = self._resolve('  %s\r\n' % UNIT)  # scanner suffixes are ignored
        self.assertFalse(res['error'])
        self.assertEqual(res['product'], self.product)
        self.assertEqual(res['uom'], self.uom_unit)

    def test_11_resolution_errors(self):
        self.assertTrue(self._resolve('OLPB-DOES-NOT-EXIST')['error'])
        self.assertTrue(self._resolve('')['error'])

        # Pallet is a vendor unit only: refused in Sales, accepted in Purchase.
        self.assertTrue(self._resolve(PALLET, 'sale')['error'])
        res = self._resolve(PALLET, 'purchase')
        self.assertFalse(res['error'])
        self.assertEqual(res['uom'], self.uom_pallet)

        # Product that cannot be sold.
        not_sold = self.env['product.product'].create({
            'name': 'OLPB Not Sold', 'barcode': 'OLPB-NOSALE-01', 'sale_ok': False,
        })
        self.assertTrue(self._resolve('OLPB-NOSALE-01', 'sale')['error'])
        self.assertFalse(self._resolve('OLPB-NOSALE-01', 'purchase')['error'])

        # Archived product.
        archived = self.env['product.product'].create({
            'name': 'OLPB Archived', 'barcode': 'OLPB-ARCH-01',
        })
        archived.active = False
        self.assertTrue(self._resolve('OLPB-ARCH-01')['error'])
        self.assertTrue(not_sold)

    def test_12_resolution_multi_company(self):
        other = self.env['res.company'].create({'name': 'OLPB Other Company'})
        self.env['product.uom'].create({
            'product_id': self.product.id, 'uom_id': self.uom_carton.id,
            'barcode': 'OLPB-OTHER-CTN', 'company_id': other.id,
        })
        self.assertTrue(self._resolve('OLPB-OTHER-CTN', company=self.company)['error'])
        self.assertFalse(self._resolve('OLPB-OTHER-CTN', company=other)['error'])

        # Odoo 19 product barcodes are unique per company: another company's
        # product with a barcode is not found from this company.
        self.env['product.product'].create({
            'name': 'OLPB Other Co Product', 'barcode': 'OLPB-OTHERCO-01', 'company_id': other.id,
        })
        self.assertTrue(self._resolve('OLPB-OTHERCO-01', company=self.company)['error'])
        self.assertFalse(self._resolve('OLPB-OTHERCO-01', company=other)['error'])

    def test_13_product_warning_message(self):
        warned = self.env['product.product'].create({
            'name': 'OLPB Warned', 'barcode': 'OLPB-WARN-01', 'list_price': 1.0,
            'sale_line_warn_msg': 'Fragile',
        })
        # With the Sales Warnings group: line added and message shown.
        order = self.env['sale.order'].with_user(self.user).new({
            'partner_id': self.customer.id, 'company_id': self.company.id,
            'state': 'draft', 'date_order': fields.Datetime.now(),
        })
        res = order._olpb_scan('OLPB-WARN-01')
        self.assertEqual(res['warning']['message'], 'Fragile')
        self.assertEqual(res['warning']['type'], 'notification')
        self.assertEqual(order.order_line.product_id, warned)

        # Without the group: no message, as in standard Odoo.
        self.user.group_ids -= self.env.ref('sale.group_warning_sale')
        order = self.env['sale.order'].with_user(self.user).new({
            'partner_id': self.customer.id, 'company_id': self.company.id,
            'state': 'draft', 'date_order': fields.Datetime.now(),
        })
        self.assertFalse(order._olpb_scan('OLPB-WARN-01'))
        self.assertEqual(order.order_line.product_id, warned)

    # ------------------------------------------------------------------
    # 3. Sales: packaging units and pricing
    # ------------------------------------------------------------------
    def test_20_sale_header_scan_uses_packaging_unit_and_reprices(self):
        so_form = self._sale_form()
        so_form.packaging_barcode_input = BOX
        self.assertFalse(so_form.packaging_barcode_input, "The scan box must be cleared")
        self.assertEqual(len(so_form.order_line), 1)
        with so_form.order_line.edit(0) as line:
            self.assertEqual(line.product_id, self.product)
            self.assertEqual(line.product_uom_qty, 1.0)
            self.assertEqual(line.product_uom_id, self.uom_box)
            self.assertEqual(line.price_unit, 60.0)  # 6 x 10.00

        for _i in range(3):
            so_form.packaging_barcode_input = BOX
        so_form.packaging_barcode_input = CARTON
        so_form.packaging_barcode_input = UNIT
        so_form.packaging_barcode_input = UNIT
        order = so_form.save()

        box_line = order.order_line.filtered(lambda l: l.product_uom_id == self.uom_box)
        carton_line = order.order_line.filtered(lambda l: l.product_uom_id == self.uom_carton)
        unit_line = order.order_line.filtered(lambda l: l.product_uom_id == self.uom_unit)
        self.assertEqual(len(order.order_line), 3)

        # 4 boxes = 24 units: the 24-unit price break applies (9.00 x 6 per box).
        self.assertRecordValues(box_line, [{
            'product_uom_qty': 4.0, 'price_unit': 54.0, 'price_subtotal': 216.0,
        }])
        self.assertRecordValues(carton_line, [{
            'product_uom_qty': 1.0, 'price_unit': 216.0, 'price_subtotal': 216.0,
        }])
        self.assertRecordValues(unit_line, [{
            'product_uom_qty': 2.0, 'price_unit': 10.0, 'price_subtotal': 20.0,
        }])
        self.assertAlmostEqual(order.amount_untaxed, 216.0 + 216.0 + 20.0)

    def test_21_sale_hardware_scanner_event(self):
        """The barcode_handler widget writes `_barcode_scanned`; same engine."""
        so_form = self._sale_form()
        so_form._barcode_scanned = CARTON
        so_form._barcode_scanned = CARTON
        order = so_form.save()
        self.assertRecordValues(order.order_line, [{
            'product_uom_qty': 2.0, 'product_uom_id': self.uom_carton.id, 'price_unit': 216.0,
        }])

    def test_22_sale_line_level_scan(self):
        so_form = self._sale_form()
        with so_form.order_line.new() as line:
            line.packaging_barcode_input = CARTON
            self.assertEqual(line.product_id, self.product)
            self.assertEqual(line.product_uom_qty, 1.0)
            self.assertEqual(line.product_uom_id, self.uom_carton)
            line.packaging_barcode_input = CARTON
            self.assertEqual(line.product_uom_qty, 2.0)
            self.assertFalse(line.packaging_barcode_input)
        order = so_form.save()
        self.assertRecordValues(order.order_line, [{
            'product_uom_qty': 2.0, 'product_uom_id': self.uom_carton.id, 'price_unit': 216.0,
        }])

    def test_23_sale_confirmed_order_increment(self):
        so_form = self._sale_form()
        so_form.packaging_barcode_input = BOX
        order = so_form.save()
        order.action_confirm()
        self.assertEqual(order.state, 'sale')

        so_form = Form(order.with_user(self.user))
        so_form.packaging_barcode_input = BOX
        so_form.save()
        self.assertRecordValues(order.order_line, [{
            'product_uom_qty': 2.0, 'product_uom_id': self.uom_box.id,
        }])

    def test_24_sale_other_unit_line_is_not_touched(self):
        """A unit scan never increases a box line (no conversion rounding)."""
        order = self._new_sale_order()
        order._olpb_scan(BOX)
        order._olpb_scan(UNIT)
        self.assertEqual(len(order.order_line), 2)
        box_line = order.order_line.filtered(lambda l: l.product_uom_id == self.uom_box)
        self.assertEqual(box_line.product_uom_qty, 1.0)

    def test_25_sale_locked_order_is_protected(self):
        """Confirmed orders are locked with the `locked` flag (no 'done' state)."""
        so_form = self._sale_form()
        so_form.packaging_barcode_input = BOX
        order = so_form.save()
        order.action_confirm()
        order.action_lock()
        self.assertTrue(order.locked)
        res = order._olpb_scan(BOX)
        self.assertIn('warning', res)
        self.assertEqual(order.order_line.product_uom_qty, 1.0)

    # ------------------------------------------------------------------
    # 4. Purchase: packaging units, vendor prices, onchange cascade
    # ------------------------------------------------------------------
    def test_30_purchase_header_scan_vendor_price_break(self):
        po_form = self._purchase_form()
        po_form.packaging_barcode_input = BOX
        with po_form.order_line.edit(0) as line:
            self.assertEqual(line.product_qty, 1.0)
            self.assertEqual(line.product_uom_id, self.uom_box)
            self.assertEqual(line.price_unit, 30.0, "6 units, below the vendor min qty: cost 5.00 x 6")
        po_form.packaging_barcode_input = BOX
        po_form.packaging_barcode_input = UNIT
        po_form.packaging_barcode_input = PALLET
        order = po_form.save()

        box_line = order.order_line.filtered(lambda l: l.product_uom_id == self.uom_box)
        unit_line = order.order_line.filtered(lambda l: l.product_uom_id == self.uom_unit)
        pallet_line = order.order_line.filtered(lambda l: l.product_uom_id == self.uom_pallet)
        self.assertRecordValues(box_line, [{'product_qty': 2.0, 'price_unit': 24.0}])     # 12 units x 4.00
        self.assertRecordValues(unit_line, [{'product_qty': 1.0, 'price_unit': 5.0}])
        self.assertRecordValues(pallet_line, [{'product_qty': 1.0, 'price_unit': 480.0}])  # 120 x 4.00
        self.assertTrue(box_line.name, "Description filled like a manual entry")

    def test_31_purchase_line_level_scan_survives_product_onchange(self):
        """Odoo's PO product onchange resets qty/unit to the vendor minimum
        (12 Units here). The scanned quantity and unit must survive it."""
        po_form = self._purchase_form()
        with po_form.order_line.new() as line:
            line.packaging_barcode_input = BOX
            self.assertEqual(line.product_id, self.product)
            self.assertEqual(line.product_qty, 1.0)
            self.assertEqual(line.product_uom_id, self.uom_box)
            line.packaging_barcode_input = BOX
            self.assertEqual(line.product_qty, 2.0)
        order = po_form.save()
        self.assertRecordValues(order.order_line, [{
            'product_qty': 2.0, 'product_uom_id': self.uom_box.id, 'price_unit': 24.0,
        }])

    def test_32_purchase_confirmed_order_is_protected(self):
        po_form = self._purchase_form()
        po_form.packaging_barcode_input = BOX
        order = po_form.save()
        order.button_confirm()
        self.assertEqual(order.state, 'purchase')
        res = order._olpb_scan(BOX)
        self.assertIn('warning', res)
        self.assertEqual(order.order_line.product_qty, 1.0)

    def test_33_partner_required(self):
        order = self._new_purchase_order(partner_id=False)
        res = order._olpb_scan(BOX)
        self.assertIn('warning', res)
        self.assertFalse(order.order_line)

    # ------------------------------------------------------------------
    # 5. Performance under high-speed scanning
    # ------------------------------------------------------------------
    def _count_queries(self, func):
        self.env.flush_all()
        self.env.invalidate_all()
        start = self.cr.sql_log_count
        func()
        return self.cr.sql_log_count - start

    def test_40_resolution_cost_independent_of_catalogue_size(self):
        """Each lookup is an indexed point query: the number of SQL queries
        must not change when the catalogue grows."""
        budget = {}
        for barcode in (BOX, UNIT):
            budget[barcode] = self._count_queries(lambda b=barcode: self._resolve(b))
            self.assertLessEqual(budget[barcode], 14, "Cold-cache resolution of %s" % barcode)

        # Grow the catalogue: 400 products, each with a packaging barcode.
        templates = self.env['product.template'].create([{
            'name': 'OLPB Bulk %04d' % i,
            'barcode': 'OLPB-BULK-%04d' % i,
            'uom_ids': [Command.set([self.uom_box.id])],
        } for i in range(400)])
        self.env['product.uom'].create([{
            'product_id': tmpl.product_variant_id.id,
            'uom_id': self.uom_box.id,
            'barcode': 'OLPB-BULKPK-%04d' % i,
        } for i, tmpl in enumerate(templates)])

        for barcode in (BOX, UNIT):
            count = self._count_queries(lambda b=barcode: self._resolve(b))
            self.assertEqual(count, budget[barcode],
                             "Query count for %s grew with the catalogue size" % barcode)

    def test_41_indexes_back_the_lookups(self):
        for table in ('product_uom', 'product_product'):
            self.cr.execute("SELECT indexdef FROM pg_indexes WHERE tablename = %s", [table])
            defs = [row[0] for row in self.cr.fetchall()]
            self.assertTrue(any('(barcode)' in d for d in defs),
                            "No index on %s.barcode: %s" % (table, defs))

    def test_42_high_speed_scanning_burst(self):
        """300 scans in a burst on one order: exact totals, bounded and
        constant SQL per scan, correct final pricing."""
        order = self._new_sale_order()
        cycle = [BOX, CARTON, UNIT]
        for barcode in cycle:  # warm-up: creates the 3 lines
            order._olpb_scan(barcode)

        def burst(n):
            start_q, start_t = self.cr.sql_log_count, time.perf_counter()
            for i in range(n):
                res = order._olpb_scan(cycle[i % 3])
                self.assertFalse(res)
            return self.cr.sql_log_count - start_q, time.perf_counter() - start_t

        early_q, early_t = burst(150)
        late_q, late_t = burst(150)
        scans = 300
        _logger.info(
            "OLPB burst: %d scans, %.2f queries/scan, %.2f ms/scan",
            scans, (early_q + late_q) / scans, (early_t + late_t) * 1000 / scans)

        self.assertLessEqual((early_q + late_q) / scans, 4.0, "Too many queries per scan")
        self.assertLessEqual(late_q, early_q + 3, "Per-scan cost grows during the burst")
        self.assertLess((early_t + late_t) / scans, 0.25, "Scan latency is pathological")

        self.assertEqual(len(order.order_line), 3)
        per_barcode = float(1 + scans // 3)
        box = order.order_line.filtered(lambda l: l.product_uom_id == self.uom_box)
        carton = order.order_line.filtered(lambda l: l.product_uom_id == self.uom_carton)
        unit = order.order_line.filtered(lambda l: l.product_uom_id == self.uom_unit)
        self.assertEqual(box.product_uom_qty, per_barcode)
        self.assertEqual(carton.product_uom_qty, per_barcode)
        self.assertEqual(unit.product_uom_qty, per_barcode)
        self.assertEqual(box.price_unit, 54.0)   # 101 boxes = 606 units >= 24
        self.assertEqual(unit.price_unit, 9.0)   # 101 units >= 24: price break

    # ------------------------------------------------------------------
    # 6. Arabic
    # ------------------------------------------------------------------
    def test_50_arabic_translation(self):
        self.env['res.lang']._activate_lang('ar_001')
        self.env['ir.module.module']._load_module_terms(
            ['order_line_packaging_barcode'], ['ar_001'], overwrite=True)
        lang = self.env['res.lang'].with_context(active_test=False).search([('code', '=', 'ar_001')])
        self.assertEqual(lang.direction, 'rtl')

        field = self.env['ir.model.fields']._get('sale.order', 'packaging_barcode_input')
        self.assertEqual(field.with_context(lang='ar_001').field_description, 'مسح الباركود')

        order = self._new_sale_order().with_context(lang='ar_001')
        res = order._olpb_scan('OLPB-DOES-NOT-EXIST')
        self.assertIn('OLPB-DOES-NOT-EXIST', res['warning']['message'])
        self.assertIn('لم يتم العثور', res['warning']['message'])
