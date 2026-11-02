# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class PurchaseOrderTemplateLine(models.Model):
    _name = 'purchase.order.template.line'
    _inherit = 'analytic.mixin'
    _description = 'RFQ / Purchase Template Line'
    _order = 'template_id, sequence, id'
    _check_company_auto = True

    template_id = fields.Many2one(
        'purchase.order.template', string='Template',
        required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='template_id.company_id', store=True, index=True)
    sequence = fields.Integer(default=10)
    display_type = fields.Selection(
        [('line_section', 'Section'), ('line_note', 'Note')],
        default=False, help="Technical field for UX purpose.")

    product_id = fields.Many2one(
        'product.product', string='Product', check_company=True,
        domain="[('purchase_ok', '=', True), '|', ('company_id', '=', False), ('company_id', 'parent_of', company_id)]")
    name = fields.Text(
        string='Description', translate=True,
        help="Optional. Leave empty to use the vendor's product description, "
             "computed when the RFQ line is created.")
    product_qty = fields.Float(
        string='Quantity', digits='Product Unit of Measure', default=1.0)
    product_uom_category_id = fields.Many2one(related='product_id.uom_id.category_id')
    product_uom_id = fields.Many2one(
        'uom.uom', string='Unit of Measure',
        compute='_compute_product_uom_id', store=True, readonly=False, precompute=True,
        domain="[('category_id', '=', product_uom_category_id)]")
    partner_id = fields.Many2one(
        'res.partner', string='Only for Vendor',
        help="Vendor-specific line: it is loaded only when the RFQ vendor "
             "(or its company) is this vendor. Leave empty to load it for every vendor.")

    _sql_constraints = [
        ('accountable_product_required',
         "CHECK(display_type IS NOT NULL OR product_id IS NOT NULL)",
         "A template line must have a product (only sections and notes may not)."),
        ('non_accountable_null_fields',
         "CHECK(display_type IS NULL OR (product_id IS NULL AND product_uom_id IS NULL))",
         "Sections and notes cannot have a product or unit of measure."),
    ]

    @api.depends('product_id')
    def _compute_product_uom_id(self):
        for line in self:
            if line.display_type or not line.product_id:
                line.product_uom_id = False
            elif not line.product_uom_id or line.product_uom_id.category_id != line.product_id.uom_id.category_id:
                line.product_uom_id = line.product_id.uom_po_id or line.product_id.uom_id

    @api.constrains('product_id', 'product_uom_id')
    def _check_uom_category(self):
        for line in self:
            if line.product_id and line.product_uom_id \
                    and line.product_uom_id.category_id != line.product_id.uom_id.category_id:
                raise ValidationError(_(
                    "The unit of measure '%(uom)s' of line '%(product)s' is not in the same "
                    "category as the product's unit of measure.",
                    uom=line.product_uom_id.name, product=line.product_id.display_name))

    @api.constrains('product_qty', 'display_type')
    def _check_quantity(self):
        for line in self:
            if not line.display_type and line.product_qty < 0:
                raise ValidationError(_("Template quantities cannot be negative."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('display_type'):
                vals.update(product_id=False, product_uom_id=False, product_qty=0.0)
        return super().create(vals_list)

    def write(self, vals):
        if 'display_type' in vals and self.filtered(lambda l: l.display_type != vals['display_type']):
            raise ValidationError(_(
                "You cannot change the type of a template line. Delete it and add a new line instead."))
        return super().write(vals)

    def _is_applicable_to(self, order):
        """Whether this line must be loaded on ``order`` (vendor mapping, archive, company)."""
        self.ensure_one()
        if self.partner_id:
            vendor = order.partner_id.commercial_partner_id
            if not vendor or self.partner_id.commercial_partner_id != vendor:
                return False
        if self.display_type:
            return True
        product = self.product_id
        if not product.active or not product.purchase_ok:
            return False
        if product.purchase_line_warn == 'block':  # "Blocking Message" on purchase
            return False
        # v17 branches: products of the order company or of one of its parents
        if product.company_id and product.company_id not in order.company_id.parent_ids:
            return False
        return True
