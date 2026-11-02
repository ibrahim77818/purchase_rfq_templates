# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class PurchaseOrderTemplate(models.Model):
    _name = 'purchase.order.template'
    _description = 'RFQ / Purchase Template'
    _order = 'sequence, name, id'
    _check_company_auto = True
    # v17 branches: a template of a parent company can be used by its branches
    _check_company_domain = models.check_company_domain_parent_of

    name = fields.Char(string='Template Name', required=True, translate=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(
        'res.company', string='Company', index=True,
        default=lambda self: self.env.company,
        help="Leave empty to share this template between all companies.")
    line_ids = fields.One2many(
        'purchase.order.template.line', 'template_id',
        string='Template Lines', copy=True)
    line_count = fields.Integer(compute='_compute_line_count', string='Products')

    # Vendor mapping
    partner_id = fields.Many2one(
        'res.partner', string='Default Vendor', check_company=True,
        domain="['|', ('company_id', '=', False), ('company_id', 'parent_of', company_id)]",
        help="Vendor set on the RFQ when the template is loaded on an RFQ "
             "that has no vendor yet.")
    partner_ids = fields.Many2many(
        'res.partner', 'purchase_order_template_partner_rel', 'template_id', 'partner_id',
        string='Allowed Vendors',
        help="Restrict the template to these vendors (and their contacts). "
             "Leave empty to allow any vendor.")

    # Header defaults (only filled when empty on the RFQ)
    payment_term_id = fields.Many2one(
        'account.payment.term', string='Payment Terms', check_company=True,
        domain="['|', ('company_id', '=', False), ('company_id', 'parent_of', company_id)]",
        help="Used only when the RFQ has no payment terms yet.")
    note = fields.Html(
        string='Terms and Conditions', translate=True,
        help="Copied to the RFQ terms when they are empty.")
    description = fields.Text(string='Internal Notes')

    @api.depends('line_ids.product_id')
    def _compute_line_count(self):
        for template in self:
            template.line_count = len(template.line_ids.filtered(lambda l: not l.display_type))

    @api.constrains('partner_id', 'partner_ids')
    def _check_default_vendor_allowed(self):
        for template in self:
            if template.partner_id and not template._is_vendor_allowed(template.partner_id):
                raise ValidationError(_(
                    "The default vendor of template '%s' must be one of its allowed vendors.",
                    template.name))

    def _is_vendor_allowed(self, partner):
        """True when ``partner`` (or its commercial entity) may use this template."""
        self.ensure_one()
        if not self.partner_ids or not partner:
            return True
        commercial = partner.commercial_partner_id
        allowed = self.partner_ids | self.partner_ids.commercial_partner_id
        return partner in allowed or commercial in allowed

    def copy(self, default=None):
        default = dict(default or {})
        if 'name' not in default:
            default['name'] = _("%s (copy)", self.name)
        return super().copy(default)

    def action_create_rfq(self):
        """Open a new RFQ pre-loaded with this template."""
        self.ensure_one()
        context = {
            'default_purchase_template_id': self.id,
            'default_company_id': (self.company_id or self.env.company).id,
        }
        if self.partner_id:
            context['default_partner_id'] = self.partner_id.id
        return {
            'type': 'ir.actions.act_window',
            'name': _('Request for Quotation'),
            'res_model': 'purchase.order',
            'view_mode': 'form',
            'target': 'current',
            'context': context,
        }

    def action_view_rfqs(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('purchase.purchase_rfq')
        action['domain'] = [('purchase_template_id', '=', self.id)]
        action['context'] = {'default_purchase_template_id': self.id}
        return action
