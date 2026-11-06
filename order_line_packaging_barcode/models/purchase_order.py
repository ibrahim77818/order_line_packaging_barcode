# -*- coding: utf-8 -*-
import json

from odoo import _, api, fields, models


class PurchaseOrder(models.Model):
    _name = 'purchase.order'
    _inherit = ['purchase.order', 'packaging.barcode.order.mixin']

    _olpb_usage = 'purchase'
    _olpb_company_flag = 'purchase_packaging_barcode_scan'
    # In Odoo 19 the product of a PO line is read-only once the order is
    # confirmed, so scanning is limited to RFQs.
    _olpb_scannable_states = ('draft', 'sent')

    packaging_barcode_enabled = fields.Boolean(
        string="Packaging Barcode Scanning Enabled",
        compute='_compute_packaging_barcode_enabled')

    @api.depends('company_id')
    @api.depends_context('company')
    def _compute_packaging_barcode_enabled(self):
        for order in self:
            order.packaging_barcode_enabled = order._olpb_is_enabled()

    def _olpb_partner_missing_message(self):
        return _("Please select a vendor before scanning.")


class PurchaseOrderLine(models.Model):
    _name = 'purchase.order.line'
    _inherit = ['purchase.order.line', 'packaging.barcode.line.mixin']

    _olpb_usage = 'purchase'
    _olpb_qty_field = 'product_qty'

    packaging_barcode_pending = fields.Char(
        string="Pending Barcode Scan", store=False,
        help="Technical field: quantity and unit of a barcode scan, "
             "kept while Odoo re-runs the product onchange.")

    def _olpb_prepare_new_line(self):
        # Description, unit and taxes, as the product onchange does
        # (the unit is then replaced by the scanned one).
        for line in self:
            line._product_id_change()
        return True

    def _olpb_protect_scan(self):
        self.packaging_barcode_pending = self._olpb_scan_snapshot()
        return True

    @api.onchange('product_id')
    def onchange_product_id(self):
        """Odoo resets the quantity / unit here (``_suggest_quantity``). When the
        product was just set by a barcode scan, put the scanned values back."""
        pending = self.packaging_barcode_pending
        res = super().onchange_product_id()
        if pending:
            self._olpb_restore_scan(pending)
        return res

    def _olpb_restore_scan(self, pending):
        self.ensure_one()
        self.packaging_barcode_pending = False
        try:
            data = json.loads(pending)
        except (TypeError, ValueError):
            return
        if data.get('product') != self.product_id.id:
            return
        self.product_uom_id = self.env['uom.uom'].browse(data['uom'])
        self.product_qty = data['qty']
