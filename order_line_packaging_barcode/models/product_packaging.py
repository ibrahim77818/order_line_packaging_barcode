# -*- coding: utf-8 -*-
from odoo import _, api, models
from odoo.tools import float_compare

# Per-flow configuration of the resolution engine.
#   packaging_flag : Boolean on product.packaging ("Sales" / "Purchase")
#   product_flag   : Boolean on the product ("Can be Sold" / "Can be Purchased")
#   warn_field     : product warning selection (no-message / warning / block)
#   warn_group     : group required for warnings to apply (None = always)
OLPB_USAGES = {
    'sale': {
        'packaging_flag': 'sales',
        'product_flag': 'sale_ok',
        'warn_field': 'sale_line_warn',
        'warn_msg_field': 'sale_line_warn_msg',
        'warn_group': None,
    },
    'purchase': {
        'packaging_flag': 'purchase',
        'product_flag': 'purchase_ok',
        'warn_field': 'purchase_line_warn',
        'warn_msg_field': 'purchase_line_warn_msg',
        'warn_group': 'purchase.group_warning_purchase',
    },
}


class ProductPackaging(models.Model):
    _inherit = 'product.packaging'

    # Performance note: product.packaging.barcode is backed by the UNIQUE index
    # of the `barcode_uniq` SQL constraint and product.product.barcode carries
    # index='btree_not_null' in Odoo 17, so each lookup below is a single
    # index scan. No extra index is created on purpose (it would only add
    # write overhead).

    @api.model
    def _olpb_resolve_barcode(self, barcode, company, usage):
        """Resolve a scanned barcode for a sales or purchase order line.

        Resolution order:
          1. ``product.packaging`` barcode (unique by SQL constraint)
          2. ``product.product`` variant barcode

        Odoo 17 also enforces that a barcode is never shared between a
        product and a packaging, so the first match is authoritative.

        :param str barcode: raw scanner input (surrounding whitespace ignored)
        :param company: res.company of the order
        :param str usage: ``'sale'`` or ``'purchase'``
        :return: dict with keys ``product``, ``packaging`` (possibly empty
            recordsets) and ``error`` (translated message or False)
        """
        Product = self.env['product.product']
        Packaging = self.env['product.packaging']
        result = {'product': Product, 'packaging': Packaging, 'error': False}

        barcode = (barcode or '').strip()
        if not barcode:
            result['error'] = _("The scanned barcode is empty.")
            return result

        # 1. Packaging barcode: one index scan, at most one row. order='id'
        #    avoids the joins of the default ordering (product, template).
        packaging = Packaging.search([('barcode', '=', barcode)], limit=1, order='id')
        if packaging:
            error = packaging._olpb_check_usable(company, usage)
            if error:
                result['error'] = error
                return result
            result.update(product=packaging.product_id, packaging=packaging)
            return result

        # 2. Product variant barcode (archived variants are excluded by active_test).
        product = Product.search([('barcode', '=', barcode)], limit=1, order='id')
        if not product:
            result['error'] = _("No product or packaging found for barcode \"%s\".", barcode)
            return result
        error = self._olpb_check_product_usable(product, company, usage)
        if error:
            result['error'] = error
            return result
        result['product'] = product
        return result

    def _olpb_check_usable(self, company, usage):
        """Return an error message if this packaging cannot be scanned, else False."""
        self.ensure_one()
        conf = OLPB_USAGES[usage]
        if not self[conf['packaging_flag']]:
            if usage == 'sale':
                return _("Packaging \"%s\" is not available for sales.", self.display_name)
            return _("Packaging \"%s\" is not available for purchases.", self.display_name)
        if self.company_id and self.company_id != company:
            return _("Packaging \"%(packaging)s\" belongs to company %(company)s.",
                     packaging=self.display_name, company=self.company_id.display_name)
        if float_compare(self.qty, 0.0, precision_rounding=self.product_uom_id.rounding or 0.01) <= 0:
            return _("Packaging \"%s\" has no contained quantity.", self.display_name)
        if not self.product_id.active:
            return _("The product of packaging \"%s\" is archived.", self.display_name)
        return self._olpb_check_product_usable(self.product_id, company, usage)

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
        """Apply the product's order-line warning settings.

        :return: tuple (is_blocking, message or False)
        """
        conf = OLPB_USAGES[usage]
        if conf['warn_group'] and not self.env.user.has_group(conf['warn_group']):
            return False, False
        mode = product[conf['warn_field']]
        if not mode or mode == 'no-message':
            return False, False
        return mode == 'block', product[conf['warn_msg_field']] or False
