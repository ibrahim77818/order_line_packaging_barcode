# -*- coding: utf-8 -*-
{
    'name': 'Order Line Packaging Barcode Scanning',
    'summary': 'Scan packaging and product barcodes on Sales and Purchase order lines, '
               'with packaging quantity multipliers and safe price recalculation',
    'description': """
Order Line Packaging Barcode Scanning
=====================================
* Independent switches in Sales and Purchase settings (off by default, per company).
* Scan from anywhere on the order form (USB / Bluetooth keyboard-wedge scanners) or
  type into the "Scan Barcode" box; or type a barcode into a specific order line.
* Prioritised resolution: product packaging barcode first, then product variant barcode,
  both served by database indexes (one indexed lookup per scan).
* Packaging scans add the packaging's contained quantity in the product's unit of
  measure, set the packaging and packaging quantity, and let Odoo recompute pricelist
  prices, vendor prices and taxes, with no quantity drift and no onchange loops.
* Repeated scans of the same barcode increment the same line.
* Respects product warnings (blocking messages stop the scan), company rules,
  "Sales" / "Purchase" flags on packagings and Can be Sold / Can be Purchased.
* Arabic (ar_001) translation, RTL-ready layout.
    """,
    'version': '17.0.1.0.0',
    'category': 'Sales/Sales',
    'author': 'Ibrahim Yahia',
    'website': 'https://www.linkedin.com/in/ibrahim-yahia',
    'license': 'LGPL-3',
    'images': ['static/description/banner.png'],
    'depends': ['sale', 'purchase', 'barcodes'],
    'data': [
        'views/res_config_settings_views.xml',
        'views/sale_order_views.xml',
        'views/purchase_order_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'order_line_packaging_barcode/static/src/scss/packaging_barcode.scss',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
