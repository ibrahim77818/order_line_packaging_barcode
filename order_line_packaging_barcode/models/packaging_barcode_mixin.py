# -*- coding: utf-8 -*-
import json

from odoo import Command, _, api, fields, models
from odoo.tools import float_round


class PackagingBarcodeOrderMixin(models.AbstractModel):
    """Order-level ("header") scanning shared by sale.order and purchase.order.

    Concrete models must define:
      * ``_olpb_usage``            'sale' | 'purchase'
      * ``_olpb_company_flag``     res.company boolean enabling the feature
      * ``_olpb_scannable_states`` order states where scanning is allowed
      * field ``packaging_barcode_enabled`` (computed from the order company)
    """
    _name = 'packaging.barcode.order.mixin'
    # Inherit the barcode mixin here (not in the concrete models) so that our
    # on_barcode_scanned() overrides its NotImplementedError stub in the MRO.
    _inherit = 'barcodes.barcode_events_mixin'
    _description = 'Packaging Barcode Scanning on Orders'

    _olpb_usage = False
    _olpb_company_flag = False
    _olpb_scannable_states = ()
    _olpb_line_field = 'order_line'

    packaging_barcode_input = fields.Char(
        string="Scan Barcode", store=False,
        help="Scan or type a packaging or product barcode and press Enter. "
             "Scanning the same barcode again increases the matching line.")

    # ------------------------------------------------------------------
    # Entry points
    # ------------------------------------------------------------------
    @api.onchange('packaging_barcode_input')
    def _onchange_packaging_barcode_input(self):
        barcode = self.packaging_barcode_input
        if barcode:
            self.packaging_barcode_input = False
            return self._olpb_scan(barcode)

    def on_barcode_scanned(self, barcode):
        """Hook of barcodes.barcode_events_mixin (hardware scanner anywhere on the form)."""
        return self._olpb_scan(barcode)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _olpb_company(self):
        return self.company_id or self.env.company

    def _olpb_is_enabled(self):
        self.ensure_one()
        return bool(self._olpb_company()[self._olpb_company_flag])

    @api.model
    def _olpb_warning(self, message):
        return {'warning': {
            'title': _("Barcode Scanning"),
            'message': message,
            'type': 'notification',
        }}

    def _olpb_is_locked(self):
        return False

    def _olpb_partner_missing_message(self):
        return _("Please select a partner before scanning.")

    def _olpb_scan_blocker(self):
        """Return a message explaining why scanning is not possible, else False."""
        self.ensure_one()
        if not self._olpb_is_enabled():
            return _("Packaging barcode scanning is disabled for this company. "
                     "Enable it in the settings.")
        if self.state not in self._olpb_scannable_states or self._olpb_is_locked():
            return _("Products cannot be scanned on an order in this state.")
        if not self.partner_id:
            return self._olpb_partner_missing_message()
        return False

    # ------------------------------------------------------------------
    # Core
    # ------------------------------------------------------------------
    def _olpb_scan(self, barcode):
        """Add or increase an order line from one scanned barcode.

        Designed to run inside an onchange on a (new) order record: all changes
        stay in the cache and are only saved with the order.
        """
        self.ensure_one()
        barcode = (barcode or '').strip()
        if not barcode:
            return {}
        blocker = self._olpb_scan_blocker()
        if blocker:
            return self._olpb_warning(blocker)

        Packaging = self.env['product.packaging']
        resolution = Packaging._olpb_resolve_barcode(barcode, self._olpb_company(), self._olpb_usage)
        if resolution['error']:
            return self._olpb_warning(resolution['error'])

        blocking, warn_message = Packaging._olpb_product_warning(resolution['product'], self._olpb_usage)
        if blocking:
            return self._olpb_warning(warn_message or _("This product is blocked for this operation."))

        lines = self[self._olpb_line_field]
        line = lines._olpb_find_matching_line(resolution)
        if line:
            line._olpb_apply_resolution(resolution, increment=True)
        else:
            self._olpb_create_line(resolution)

        if warn_message:
            return self._olpb_warning(warn_message)
        return {}

    def _olpb_create_line(self, resolution):
        """Append a new line (same mechanism as Odoo's product matrix)."""
        line_field = self._olpb_line_field
        Line = self.env[self._fields[line_field].comodel_name]
        existing = self[line_field]
        vals = Line.default_get(list(Line._fields))
        product = resolution['product']
        packaging = resolution['packaging']
        vals.update({
            'display_type': False,
            'product_id': product.id,
            'product_uom': product.uom_id.id,
            'product_packaging_id': packaging.id or False,
            Line._olpb_qty_field: packaging.qty if packaging else 1.0,
            'sequence': max(existing.mapped('sequence') or [9]) + 1,
        })
        self.update({line_field: [Command.create(vals)]})
        new_line = self[line_field] - existing
        new_line._olpb_prepare_new_line()
        new_line._olpb_apply_resolution(resolution, increment=False)
        return new_line


class PackagingBarcodeLineMixin(models.AbstractModel):
    """Line-level scanning and quantity logic shared by SO and PO lines.

    Concrete models must define:
      * ``_olpb_usage``      'sale' | 'purchase'
      * ``_olpb_qty_field``  quantity field in the line UoM
    """
    _name = 'packaging.barcode.line.mixin'
    _description = 'Packaging Barcode Scanning on Order Lines'

    _olpb_usage = False
    _olpb_qty_field = False

    packaging_barcode_input = fields.Char(
        string="Barcode", store=False,
        help="Scan or type a packaging or product barcode to fill this line. "
             "Scanning the line's own barcode again adds one more unit or package.")

    # ------------------------------------------------------------------
    # Line-level entry point (barcode typed into the line)
    # ------------------------------------------------------------------
    @api.onchange('packaging_barcode_input')
    def _onchange_packaging_barcode_input(self):
        barcode = (self.packaging_barcode_input or '').strip()
        if not barcode:
            return
        self.packaging_barcode_input = False
        order = self.order_id
        blocker = order._olpb_scan_blocker()
        if blocker:
            return order._olpb_warning(blocker)

        Packaging = self.env['product.packaging']
        resolution = Packaging._olpb_resolve_barcode(barcode, order._olpb_company(), self._olpb_usage)
        if resolution['error']:
            return order._olpb_warning(resolution['error'])
        product = resolution['product']

        blocking, warn_message = Packaging._olpb_product_warning(product, self._olpb_usage)
        if blocking:
            return order._olpb_warning(warn_message or _("This product is blocked for this operation."))

        if self.product_id and self.product_id != product and not self._olpb_product_changeable():
            return order._olpb_warning(_("The product of this line can no longer be changed."))

        product_changed = self.product_id != product
        if product_changed:
            self.product_id = product
            self._olpb_prepare_new_line()
        # A line that just received its product starts from zero (its default
        # quantity of 1 must not be counted); otherwise the scan increments.
        self._olpb_apply_resolution(resolution, increment=not product_changed)
        if product_changed:
            # Odoo re-runs the product_id onchanges after this method; protect
            # the scanned quantity / UoM / packaging from being reset.
            self._olpb_protect_scan()
        # Non-blocking product warnings are shown by Odoo's own product
        # onchange when the product changes; show it here for increments.
        if warn_message and not product_changed:
            return order._olpb_warning(warn_message)

    # ------------------------------------------------------------------
    # Hooks
    # ------------------------------------------------------------------
    def _olpb_product_changeable(self):
        return True

    def _olpb_prepare_new_line(self):
        """Hook run after the product of a scanned line is set (e.g. PO name/taxes)."""
        return True

    def _olpb_protect_scan(self):
        return True

    # ------------------------------------------------------------------
    # Quantity engine
    # ------------------------------------------------------------------
    def _olpb_matches(self, resolution):
        """A line matches a scan when product, packaging and UoM are identical.

        Unit scans accumulate on lines without packaging, packaging scans on
        lines of that packaging. Lines in another UoM are never touched, which
        rules out any UoM conversion rounding on increments.
        """
        self.ensure_one()
        product = resolution['product']
        return (
            not self.display_type
            and self.product_id == product
            and self.product_packaging_id == resolution['packaging']
            and self.product_uom == product.uom_id
        )

    def _olpb_find_matching_line(self, resolution):
        for line in self:
            if line._olpb_matches(resolution) and line._olpb_can_increment():
                return line
        return self.browse()

    def _olpb_can_increment(self):
        return True

    def _olpb_apply_resolution(self, resolution, increment=True):
        """Set product, UoM, quantity and packaging coherently.

        Every value Odoo derives from the others (packaging, packaging
        quantity, quantity) is assigned explicitly, so when the framework
        recomputes them it gets exactly the same values: no quantity drift
        from packaging-quantity rounding and no onchange ping-pong. Price,
        taxes and descriptions are left to Odoo's own computes, which run on
        the final quantity and UoM (pricelist / vendor price quantity breaks).
        """
        self.ensure_one()
        product = resolution['product']
        packaging = resolution['packaging']
        uom = product.uom_id  # == packaging.product_uom_id in Odoo 17
        step = packaging.qty if packaging else 1.0
        current = self[self._olpb_qty_field] if increment and self._olpb_matches(resolution) else 0.0
        qty = float_round(current + step, precision_rounding=uom.rounding)

        if self.product_id != product:
            self.product_id = product
        self.product_uom = uom
        self[self._olpb_qty_field] = qty
        self.product_packaging_id = packaging
        self.product_packaging_qty = (qty / packaging.qty) if packaging else 0.0
        return qty

    def _olpb_scan_snapshot(self):
        self.ensure_one()
        return json.dumps({
            'product': self.product_id.id,
            'uom': self.product_uom.id,
            'qty': self[self._olpb_qty_field],
            'packaging': self.product_packaging_id.id,
            'packaging_qty': self.product_packaging_qty,
        })
