# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class SaleOrder(models.Model):
    _name = 'sale.order'
    _inherit = ['sale.order', 'packaging.barcode.order.mixin']

    _olpb_usage = 'sale'
    _olpb_company_flag = 'sale_packaging_barcode_scan'
    # Odoo 17 lets users add lines to quotations and confirmed orders; locking is
    # a separate `locked` flag (there is no 'done' state any more).
    _olpb_scannable_states = ('draft', 'sent', 'sale')

    packaging_barcode_enabled = fields.Boolean(
        string="Packaging Barcode Scanning Enabled",
        compute='_compute_packaging_barcode_enabled')

    @api.depends('company_id')
    @api.depends_context('company')
    def _compute_packaging_barcode_enabled(self):
        for order in self:
            order.packaging_barcode_enabled = order._olpb_is_enabled()

    def _olpb_is_locked(self):
        return self.locked

    def _olpb_partner_missing_message(self):
        return _("Please select a customer before scanning.")


class SaleOrderLine(models.Model):
    _name = 'sale.order.line'
    _inherit = ['sale.order.line', 'packaging.barcode.line.mixin']

    _olpb_usage = 'sale'
    _olpb_qty_field = 'product_uom_qty'

    def _olpb_product_changeable(self):
        return self.product_updatable

    def _olpb_can_increment(self):
        return not self.is_downpayment
