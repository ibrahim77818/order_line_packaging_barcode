# -*- coding: utf-8 -*-
from odoo import _, api, models

# Per-flow configuration of the resolution engine (Odoo 19).
#   product_flag : Boolean on the product ("Sales" / "Purchase")
#   warn_msg     : product warning message shown on order lines
#   warn_group   : group required for that message to apply
OLPB_USAGES = {
    'sale': {
        'product_flag': 'sale_ok',
        'warn_msg': 'sale_line_warn_msg',
        'warn_group': 'sale.group_warning_sale',
    },
    'purchase': {
        'product_flag': 'purchase_ok',
        'warn_msg': 'purchase_line_warn_msg',
        'warn_group': 'purchase.group_warning_purchase',
    },
}


class ProductUom(models.Model):
    """Odoo 19 replaced product.packaging by units of measure: a packaging is a
    uom.uom (e.g. "Box of 6" = 6 Units) listed on the product (``uom_ids``), and
    its barcode is a ``product.uom`` record (product + unit + barcode)."""
    _inherit = 'product.uom'

    # Performance note: product.uom.barcode has index='btree_not_null' plus the
    # unique `_barcode_uniq` constraint, and product.product.barcode has
    # index='btree_not_null' in Odoo 19, so each lookup below is a single index
    # scan. order='id' avoids the joins of the default orderings.

    @api.model
    def _olpb_resolve_barcode(self, barcode, company, usage):
        """Resolve a scanned barcode for a sales or purchase order line.

        Resolution order:
          1. ``product.uom`` barcode (packaging barcode, globally unique)
          2. ``product.product`` variant barcode (unique per company in Odoo 19)

        :param str barcode: raw scanner input (surrounding whitespace ignored)
        :param company: res.company of the order
        :param str usage: ``'sale'`` or ``'purchase'``
        :return: dict with keys ``product``, ``uom`` (unit to put on the line)
            and ``error`` (translated message or False)
        """
        Product = self.env['product.product']
        result = {'product': Product, 'uom': self.env['uom.uom'], 'error': False}

        barcode = (barcode or '').strip()
        if not barcode:
            result['error'] = _("The scanned barcode is empty.")
            return result

        # 1. Packaging barcode: one index scan, at most one row.
        product_uom = self.env['product.uom'].search([('barcode', '=', barcode)], limit=1, order='id')
        if product_uom:
            error = product_uom._olpb_check_usable(company, usage)
            if error:
                result['error'] = error
                return result
            result.update(product=product_uom.product_id, uom=product_uom.uom_id)
            return result

        # 2. Product variant barcode (archived variants are excluded by active_test).
        product = Product.search(
            [('barcode', '=', barcode), ('company_id', 'in', [False, company.id])],
            limit=1, order='id')
        if not product:
            result['error'] = _("No product or packaging found for barcode \"%s\".", barcode)
            return result
        error = self._olpb_check_product_usable(product, company, usage)
        if error:
            result['error'] = error
            return result
        result.update(product=product, uom=product.uom_id)
        return result

    @api.model
    def _olpb_allowed_uoms(self, product, usage):
        """Units Odoo 19 itself allows on an order line for this product
        (mirrors sale/purchase ``_compute_allowed_uom_ids``)."""
        uoms = product.uom_id | product.uom_ids
        if usage == 'purchase':
            uoms |= product.seller_ids.filtered(
                lambda s: s.product_id.id in {False, product.id}).product_uom_id
        return uoms

    def _olpb_check_usable(self, company, usage):
        """Return an error message if this packaging barcode cannot be scanned, else False."""
        self.ensure_one()
        uom = self.uom_id
        product = self.product_id
        if self.company_id and self.company_id != company:
            return _("Packaging \"%(packaging)s\" belongs to company %(company)s.",
                     packaging=uom.display_name, company=self.company_id.display_name)
        if not product.active:
            return _("The product of packaging \"%s\" is archived.", uom.display_name)
        if not uom.active:
            return _("Packaging \"%s\" is archived.", uom.display_name)
        if uom not in self._olpb_allowed_uoms(product, usage):
            if usage == 'sale':
                return _("Packaging \"%s\" is not available for sales.", uom.display_name)
            return _("Packaging \"%s\" is not available for purchases.", uom.display_name)
        return self._olpb_check_product_usable(product, company, usage)

    @api.model
    def _olpb_check_product_usable(self, product, company, usage):
        conf = OLPB_USAGES[usage]
        if not product[conf['product_flag']]:
            if usage == 'sale':
                return _("Product \"%s\" cannot be sold.", product.display_name)
            return _("Product \"%s\" cannot be purchased.", product.display_name)
        if product.company_id and product.company_id != company:
            return _("Product \"%(product)s\" belongs to company %(company)s.",
                     product=product.display_name, company=product.company_id.display_name)
        return False

    @api.model
    def _olpb_product_warning(self, product, usage):
        """Odoo 19 product warnings are a plain message (no blocking mode),
        applied when the user has the Warnings group.

        :return: message or False
        """
        conf = OLPB_USAGES[usage]
        if not self.env.user.has_group(conf['warn_group']):
            return False
        return product[conf['warn_msg']] or False
