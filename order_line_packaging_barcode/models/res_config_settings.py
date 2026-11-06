# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    sale_packaging_barcode_scan = fields.Boolean(
        related='company_id.sale_packaging_barcode_scan', readonly=False)
    purchase_packaging_barcode_scan = fields.Boolean(
        related='company_id.purchase_packaging_barcode_scan', readonly=False)
