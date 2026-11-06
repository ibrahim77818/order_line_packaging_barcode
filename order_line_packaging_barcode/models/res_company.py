# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    sale_packaging_barcode_scan = fields.Boolean(
        string="Sales Packaging Barcode Scanning",
        default=False,
        help="Scan product and packaging barcodes directly on sales order lines. "
             "A packaging barcode adds the packaging's contained quantity.",
    )
    purchase_packaging_barcode_scan = fields.Boolean(
        string="Purchase Packaging Barcode Scanning",
        default=False,
        help="Scan product and packaging barcodes directly on purchase order lines. "
             "A packaging barcode adds the packaging's contained quantity.",
    )
