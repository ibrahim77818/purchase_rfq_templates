# -*- coding: utf-8 -*-
from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import is_html_empty
from markupsafe import Markup


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    purchase_template_id = fields.Many2one(
        'purchase.order.template', string='RFQ Template',
        check_company=True, copy=False, tracking=True,
        domain="['|', ('company_id', '=', False), ('company_id', 'parent_of', company_id)]",
        help="Loading a template adds its lines to the RFQ. Lines previously loaded "
             "from a template are replaced; lines you added manually are kept.")

    @api.constrains('purchase_template_id', 'company_id')
    def _check_purchase_template_company(self):
        # purchase.order does not set _check_company_auto: enforce check_company here
        self._check_company(['purchase_template_id'])

    @api.onchange('partner_id', 'company_id')
    def onchange_partner_id(self):
        res = super().onchange_partner_id()
        # The vendor has no purchase payment terms: keep the template's ones.
        # (The ORM re-runs this onchange after a template sets the vendor.)
        template = self.purchase_template_id
        if not self.payment_term_id and template.payment_term_id:
            self.payment_term_id = template.payment_term_id
        return res

    # ------------------------------------------------------------------
    # ORM: orders created by code/import with a template and no lines
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        if self.env.context.get('skip_purchase_template_apply'):
            return orders
        for order, vals in zip(orders, vals_list):
            if order.purchase_template_id and not vals.get('order_line'):
                order._purchase_template_apply(order.purchase_template_id.with_company(order.company_id))
        return orders

    # ------------------------------------------------------------------
    # Onchange (instant loading in the form)
    # ------------------------------------------------------------------
    @api.onchange('purchase_template_id')
    def _onchange_purchase_template_id(self):
        if not self.purchase_template_id:
            return
        template = self.purchase_template_id.with_company(self.company_id)
        skipped = self._purchase_template_apply(template)
        if skipped:
            return {'warning': {
                'title': _('Some template lines were not loaded'),
                'message': self._purchase_template_skipped_message(skipped),
            }}

    # ------------------------------------------------------------------
    # Button (re-apply on a saved draft)
    # ------------------------------------------------------------------
    def action_apply_purchase_template(self):
        for order in self:
            if not order.purchase_template_id:
                raise UserError(_("Select an RFQ template on %s first.", order.name))
            template = order.purchase_template_id.with_company(order.company_id)
            skipped = order._purchase_template_apply(template)
            body = Markup('<p>%s</p>') % _("RFQ template %s applied.", template.name)
            if skipped:
                body += Markup('<p>%s</p>') % order._purchase_template_skipped_message(skipped)
            order.message_post(body=body)
        return True

    # ------------------------------------------------------------------
    # Core
    # ------------------------------------------------------------------
    def _purchase_template_check(self, template):
        self.ensure_one()
        if self.state not in ('draft', 'sent'):
            raise UserError(_("Templates can only be applied on draft or sent RFQs."))
        if not template.active:
            raise UserError(_("The RFQ template '%s' is archived.", template.name))
        if template.company_id and template.company_id not in self.company_id.parent_ids:
            raise UserError(_(
                "The RFQ template '%(template)s' belongs to %(company)s and cannot be used "
                "on an order of %(order_company)s.",
                template=template.name, company=template.company_id.name,
                order_company=self.company_id.name))

    def _purchase_template_apply(self, template):
        """Apply ``template`` on the order (works on saved and new records).

        Header values are only filled when empty. Lines previously generated
        from a template are removed, manual lines are kept, and new lines are
        priced/taxed by the standard purchase engine.

        :return: template lines that were skipped (vendor mapping, archived, company)
        """
        self.ensure_one()
        self._purchase_template_check(template)

        # Header: never overwrite what the user already set.
        header = {}
        if not self.partner_id and template.partner_id:
            header['partner_id'] = template.partner_id.id
        if not self.payment_term_id and template.payment_term_id:
            header['payment_term_id'] = template.payment_term_id.id
        if is_html_empty(self.notes) and not is_html_empty(template.note):
            header['notes'] = template.note
        if header:
            self.update(header)
            if 'partner_id' in header:
                # same cascade as the form: fiscal position, payment terms, currency
                # (our onchange_partner_id override keeps the template payment terms)
                self.onchange_partner_id()

        if self.partner_id and not template._is_vendor_allowed(self.partner_id):
            raise UserError(_(
                "The RFQ template '%(template)s' is not allowed for vendor %(vendor)s.",
                template=template.name, vendor=self.partner_id.display_name))

        applicable = template.line_ids.filtered(lambda l: l._is_applicable_to(self))
        skipped = template.line_ids - applicable

        # Must be read BEFORE the line simulation below: Line.new(order_id=<NewId>)
        # temporarily adds the simulated lines to the cached order_line.
        old_lines = self.order_line.filtered('from_purchase_template')
        kept_lines = self.order_line - old_lines
        base_sequence = max(kept_lines.mapped('sequence') or [0])
        vals_list = []
        for index, tline in enumerate(applicable.sorted('sequence'), start=1):
            vals = self._purchase_template_prepare_line_vals(tline)
            vals['sequence'] = base_sequence + index
            vals_list.append(vals)

        if isinstance(self.id, models.NewId):
            # Form/onchange: replace the cached recordset (this also drops the
            # simulated pricing lines added to the cache by Line.new()).
            Line = self.env['purchase.order.line']
            new_lines = Line.browse()
            for vals in vals_list:
                new_lines |= Line.new(vals)
            self.order_line = kept_lines | new_lines
        else:
            self.write({'order_line': [Command.delete(line.id) for line in old_lines]
                        + [Command.create(vals) for vals in vals_list]})
        return skipped

    def _purchase_template_prepare_line_vals(self, tline):
        """Values for a purchase.order.line built from template line ``tline``.

        The line is simulated exactly like the form does (product onchange, then
        UoM and quantity) so vendor price lists with quantity tiers, UoM/currency
        conversion, fiscal positions and taxes come from the standard engine.
        """
        self.ensure_one()
        vals = {
            'display_type': tline.display_type or False,
            'from_purchase_template': True,
        }
        if tline.display_type:
            vals.update(name=tline.name or '', product_qty=0.0)
            return vals

        Line = self.env['purchase.order.line'].with_company(self.company_id)
        line = Line.new({'order_id': self.id, 'product_id': tline.product_id.id})
        line.onchange_product_id()  # UoM, description, taxes (fiscal position)
        line.product_uom = tline.product_uom_id or line.product_uom
        line.product_qty = tline.product_qty
        line._compute_price_unit_and_date_planned_and_name()  # vendor price for qty/UoM

        vals.update({
            'product_id': tline.product_id.id,
            'product_qty': tline.product_qty,
            'product_uom': line.product_uom.id,
            'price_unit': line.price_unit,
            'discount': line.discount,  # v17: vendor price list discount
            'taxes_id': [Command.set(line.taxes_id.ids)],
            'date_planned': line.date_planned,
            'name': tline.name or line.name,
        })
        if tline.analytic_distribution:
            vals['analytic_distribution'] = tline.analytic_distribution
        return vals

    def _purchase_template_skipped_message(self, skipped):
        names = [l.product_id.display_name or l.name or '' for l in skipped]
        return _(
            "Not loaded (vendor-specific, archived, not purchasable or other company): %s",
            ', '.join(n for n in names if n))
