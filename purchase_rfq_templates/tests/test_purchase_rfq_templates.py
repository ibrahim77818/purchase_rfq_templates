# -*- coding: utf-8 -*-
from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import Form, TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install', 'purchase_rfq_templates')
class TestPurchaseRfqTemplates(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.company = cls.env.company
        cls.company_b = cls.env['res.company'].create({'name': 'RFQ Templates Company B'})
        cls.env.user.company_ids |= cls.company_b

        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.uom_dozen = cls.env.ref('uom.product_uom_dozen')
        cls.uom_dozen.active = True  # v19: "Dozens" is archived by default
        cls.uom_kg = cls.env.ref('uom.product_uom_kgm')

        Tax = cls.env['account.tax']
        country = cls.company.account_fiscal_country_id or cls.env.ref('base.us')
        cls.tax_15 = Tax.create({
            'name': 'Purchase VAT 15%', 'amount': 15, 'type_tax_use': 'purchase',
            'company_id': cls.company.id, 'country_id': country.id})
        # v19: a fiscal position maps taxes through the destination tax
        # (fiscal_position_ids + original_tax_ids), no more tax_src_id/tax_dest_id lines
        cls.fpos_export = cls.env['account.fiscal.position'].create({
            'name': 'Foreign vendor', 'company_id': cls.company.id})
        cls.tax_0 = Tax.create({
            'name': 'Purchase Exempt 0%', 'amount': 0, 'type_tax_use': 'purchase',
            'company_id': cls.company.id, 'country_id': country.id,
            'fiscal_position_ids': [Command.set(cls.fpos_export.ids)],
            'original_tax_ids': [Command.set(cls.tax_15.ids)]})

        Partner = cls.env['res.partner']
        cls.vendor_a = Partner.create({'name': 'Vendor A', 'is_company': True})
        cls.vendor_a_contact = Partner.create({'name': 'A Buyer', 'parent_id': cls.vendor_a.id})
        cls.vendor_b = Partner.create({'name': 'Vendor B', 'is_company': True})
        cls.vendor_foreign = Partner.create({'name': 'Foreign Vendor', 'is_company': True})
        cls.vendor_foreign.with_company(cls.company).property_account_position_id = cls.fpos_export

        Product = cls.env['product.product']
        cls.product_paper = Product.create({
            'name': 'A4 Paper', 'type': 'consu', 'purchase_ok': True,
            'standard_price': 5.0, 'supplier_taxes_id': [Command.set(cls.tax_15.ids)],
            'seller_ids': [
                Command.create({'partner_id': cls.vendor_a.id, 'min_qty': 1, 'price': 10.0}),
                Command.create({'partner_id': cls.vendor_a.id, 'min_qty': 50, 'price': 8.0}),
                Command.create({'partner_id': cls.vendor_b.id, 'min_qty': 1, 'price': 11.0}),
            ],
        })
        cls.product_pen = Product.create({
            'name': 'Pen', 'type': 'consu', 'purchase_ok': True,
            'uom_ids': [Command.set(cls.uom_dozen.ids)],
            'standard_price': 1.0, 'supplier_taxes_id': [Command.set(cls.tax_15.ids)],
            'seller_ids': [Command.create({'partner_id': cls.vendor_a.id, 'min_qty': 1, 'price': 2.0})],
        })
        cls.product_toner = Product.create({
            'name': 'Toner', 'type': 'consu', 'purchase_ok': True, 'standard_price': 40.0,
        })

        plan_vals = {'name': 'RFQ Templates Plan'}
        if 'company_id' in cls.env['account.analytic.plan']._fields:
            plan_vals['company_id'] = False  # removed from analytic plans during the 17.0 series
        cls.analytic_plan = cls.env['account.analytic.plan'].create(plan_vals)
        cls.analytic_admin = cls.env['account.analytic.account'].create({
            'name': 'Administration', 'plan_id': cls.analytic_plan.id, 'company_id': False})
        cls.analytic_it = cls.env['account.analytic.account'].create({
            'name': 'IT', 'plan_id': cls.analytic_plan.id, 'company_id': False})

        cls.payment_term = cls.env['account.payment.term'].create({'name': '45 Days (template)'})

        cls.template = cls.env['purchase.order.template'].create({
            'name': 'Office Supplies',
            'payment_term_id': cls.payment_term.id,
            'note': '<p>Deliver to the main warehouse.</p>',
            'line_ids': [
                Command.create({'display_type': 'line_section', 'name': 'Stationery', 'sequence': 1}),
                Command.create({'product_id': cls.product_paper.id, 'product_qty': 60, 'sequence': 2,
                                'analytic_distribution': {str(cls.analytic_admin.id): 100}}),
                Command.create({'product_id': cls.product_pen.id, 'product_qty': 2,
                                'product_uom_id': cls.uom_dozen.id, 'sequence': 3}),
                Command.create({'display_type': 'line_note', 'name': 'Check expiry dates', 'sequence': 4}),
            ],
        })

    # ------------------------------------------------------------------ helpers
    def _new_po(self, partner=None, **vals):
        values = {'partner_id': (partner or self.vendor_a).id, 'company_id': self.company.id}
        values.update(vals)
        return self.env['purchase.order'].create(values)

    def _product_lines(self, po):
        return po.order_line.filtered(lambda l: not l.display_type)

    def _line(self, po, product):
        return po.order_line.filtered(lambda l: l.product_id == product)

    # ------------------------------------------------------------------ data model
    def test_template_model_basics(self):
        self.assertEqual(self.template.line_count, 2, "Sections/notes are not counted as products")
        pen_line = self.template.line_ids.filtered(lambda l: l.product_id == self.product_pen)
        self.assertEqual(pen_line.product_uom_id, self.uom_dozen)
        paper_line = self.template.line_ids.filtered(lambda l: l.product_id == self.product_paper)
        self.assertEqual(paper_line.product_uom_id, self.uom_unit, "UoM defaults to the purchase UoM")
        self.assertEqual(paper_line.company_id, self.company)

        copy = self.template.copy()
        self.assertIn('(copy)', copy.name)
        self.assertEqual(len(copy.line_ids), 4)

    def test_template_constraints(self):
        with self.assertRaises(ValidationError):
            self.env['purchase.order.template.line'].create({
                'template_id': self.template.id,
                'product_id': self.product_paper.id,
                'product_uom_id': self.uom_kg.id,
            })
        with self.assertRaises(ValidationError):
            self.env['purchase.order.template'].create({
                'name': 'Bad default vendor',
                'partner_id': self.vendor_b.id,
                'partner_ids': [Command.set(self.vendor_a.ids)],
            })
        product_b = self.env['product.product'].create({
            'name': 'Company B only', 'company_id': self.company_b.id})
        with self.assertRaises(UserError):  # check_company
            self.env['purchase.order.template'].create({
                'name': 'Mixed companies', 'company_id': self.company.id,
                'line_ids': [Command.create({'product_id': product_b.id})],
            })
        with self.assertRaises(UserError):  # shared templates only take shared products
            self.env['purchase.order.template'].create({
                'name': 'Shared with company product', 'company_id': False,
                'line_ids': [Command.create({'product_id': product_b.id})],
            })
        with self.assertRaises(ValidationError):
            self.env['purchase.order.template.line'].create({
                'template_id': self.template.id, 'product_id': self.product_pen.id, 'product_qty': -1})

    # ------------------------------------------------------------------ UI integration
    def test_form_onchange_loads_lines_and_keeps_header(self):
        po_form = Form(self.env['purchase.order'])
        po_form.partner_id = self.vendor_a
        po_form.partner_ref = 'VENDOR-REF-1'
        po_form.purchase_template_id = self.template
        po = po_form.save()

        self.assertEqual(po.partner_id, self.vendor_a)
        self.assertEqual(po.partner_ref, 'VENDOR-REF-1', "Header values must be preserved")
        self.assertEqual(po.payment_term_id, self.payment_term, "Empty payment terms are filled")
        self.assertIn('main warehouse', po.note or '')
        self.assertEqual(len(po.order_line), 4)
        self.assertEqual(po.order_line.mapped('display_type'), ['line_section', False, False, 'line_note'])
        self.assertTrue(all(po.order_line.mapped('from_purchase_template')))

    def test_form_onchange_switch_template_replaces_only_template_lines(self):
        other = self.env['purchase.order.template'].create({
            'name': 'Toner refill',
            'line_ids': [Command.create({'product_id': self.product_toner.id, 'product_qty': 3})],
        })
        po_form = Form(self.env['purchase.order'])
        po_form.partner_id = self.vendor_a
        with po_form.order_line.new() as manual:
            manual.product_id = self.product_toner
            manual.product_qty = 1
        po_form.purchase_template_id = self.template
        po_form.purchase_template_id = other
        po = po_form.save()

        self.assertEqual(len(po.order_line), 2, "Manual line + 1 line of the second template")
        manual_line = po.order_line.filtered(lambda l: not l.from_purchase_template)
        self.assertEqual(manual_line.product_qty, 1)
        tpl_line = po.order_line.filtered('from_purchase_template')
        self.assertEqual(tpl_line.product_qty, 3)

    def test_create_with_template_auto_applies(self):
        po = self._new_po(purchase_template_id=self.template.id)
        self.assertEqual(len(self._product_lines(po)), 2)

    def test_create_with_explicit_lines_does_not_apply(self):
        po = self._new_po(purchase_template_id=self.template.id, order_line=[
            Command.create({'product_id': self.product_toner.id, 'product_qty': 1})])
        self.assertEqual(po.order_line.product_id, self.product_toner)

    def test_action_create_rfq_uses_default_vendor(self):
        self.template.partner_id = self.vendor_a
        action = self.template.action_create_rfq()
        po_form = Form(self.env['purchase.order'].with_context(action['context']))
        self.assertEqual(po_form.partner_id, self.vendor_a)
        po = po_form.save()
        self.assertEqual(po.purchase_template_id, self.template)
        self.assertEqual(len(self._product_lines(po)), 2)
        self.assertEqual(self.template.action_view_rfqs()['domain'],
                         [('purchase_template_id', '=', self.template.id)])

    def test_default_vendor_filled_when_empty(self):
        self.template.partner_id = self.vendor_foreign
        po_form = Form(self.env['purchase.order'])
        po_form.purchase_template_id = self.template
        self.assertEqual(po_form.partner_id, self.vendor_foreign)
        self.assertEqual(po_form.fiscal_position_id, self.fpos_export,
                         "Vendor set by the template triggers the native partner cascade")
        self.assertEqual(po_form.payment_term_id, self.payment_term,
                         "Vendor without payment terms keeps the template's ones")
        po = po_form.save()
        self.assertEqual(po.payment_term_id, self.payment_term)
        self.assertEqual(self._line(po, self.product_paper).tax_ids, self.tax_0)

    def test_default_vendor_never_overwrites(self):
        self.template.partner_id = self.vendor_b
        po = self._new_po(partner=self.vendor_a, purchase_template_id=self.template.id)
        self.assertEqual(po.partner_id, self.vendor_a)
        self.assertEqual(self._line(po, self.product_paper).price_unit, 8.0)

    # ------------------------------------------------------------------ pricing & taxes
    def test_vendor_pricelist_quantity_tier_and_uom(self):
        po = self._new_po(purchase_template_id=self.template.id)
        paper = self._line(po, self.product_paper)
        self.assertEqual(paper.product_qty, 60)
        self.assertEqual(paper.price_unit, 8.0, "Quantity tier (min 50) of Vendor A")
        pen = self._line(po, self.product_pen)
        self.assertEqual(pen.product_uom_id, self.uom_dozen)
        self.assertEqual(pen.product_qty, 2)
        self.assertAlmostEqual(pen.price_unit, 24.0, msg="2.0/unit converted to dozen")
        self.assertAlmostEqual(po.amount_untaxed, 60 * 8.0 + 2 * 24.0)

    def test_vendor_discount(self):
        """v17: the vendor price list discount is computed natively and kept."""
        self.product_paper.seller_ids.filtered(lambda s: s.min_qty == 50).discount = 10.0
        po = self._new_po(purchase_template_id=self.template.id)
        paper = self._line(po, self.product_paper)
        self.assertEqual(paper.price_unit, 8.0)
        self.assertEqual(paper.discount, 10.0)
        self.assertAlmostEqual(paper.price_subtotal, 60 * 8.0 * 0.9)

    def test_vendor_specific_price(self):
        po = self._new_po(partner=self.vendor_b, purchase_template_id=self.template.id)
        self.assertEqual(self._line(po, self.product_paper).price_unit, 11.0)
        # no supplierinfo for Vendor B on pens: falls back to cost, converted to dozen
        self.assertAlmostEqual(self._line(po, self.product_pen).price_unit, 12.0)

    def test_taxes_and_fiscal_position(self):
        po = self._new_po(purchase_template_id=self.template.id)
        self.assertEqual(self._line(po, self.product_paper).tax_ids, self.tax_15)

        po_form = Form(self.env['purchase.order'])
        po_form.partner_id = self.vendor_foreign
        self.assertEqual(po_form.fiscal_position_id, self.fpos_export)
        po_form.purchase_template_id = self.template
        po = po_form.save()
        self.assertEqual(self._line(po, self.product_paper).tax_ids, self.tax_0,
                         "Fiscal position maps supplier taxes")
        self.assertAlmostEqual(po.amount_tax, 0.0)

    def test_analytic_distribution(self):
        self.env['account.analytic.distribution.model'].create({
            'product_id': self.product_pen.id,
            'analytic_distribution': {str(self.analytic_it.id): 100},
        })
        po = self._new_po(purchase_template_id=self.template.id)
        self.assertEqual(self._line(po, self.product_paper).analytic_distribution,
                         {str(self.analytic_admin.id): 100}, "Template analytic wins")
        self.assertEqual(self._line(po, self.product_pen).analytic_distribution,
                         {str(self.analytic_it.id): 100}, "Native distribution model applies otherwise")

    # ------------------------------------------------------------------ reapply / edits
    def test_reapply_after_template_modification(self):
        po = self._new_po(purchase_template_id=self.template.id)
        manual = self.env['purchase.order.line'].create({
            'order_id': po.id, 'product_id': self.product_toner.id, 'product_qty': 4})
        self.assertFalse(manual.from_purchase_template)

        paper_tline = self.template.line_ids.filtered(lambda l: l.product_id == self.product_paper)
        paper_tline.product_qty = 10
        self.template.line_ids.filtered(lambda l: l.product_id == self.product_pen).unlink()

        po.action_apply_purchase_template()
        self.assertTrue(manual.exists(), "Manual lines are kept")
        self.assertEqual(manual.product_qty, 4)
        self.assertEqual(len(self._line(po, self.product_paper)), 1, "No duplicated lines")
        self.assertEqual(self._line(po, self.product_paper).product_qty, 10)
        self.assertEqual(self._line(po, self.product_paper).price_unit, 10.0, "Tier recomputed for qty 10")
        self.assertFalse(self._line(po, self.product_pen), "Removed template line disappears")
        self.assertEqual(len(po.order_line), 4)  # section, paper, note, manual toner

    def test_reapply_twice_is_idempotent(self):
        po = self._new_po(purchase_template_id=self.template.id)
        before = [(l.display_type, l.product_id.id, l.product_qty, l.price_unit) for l in po.order_line]
        po.action_apply_purchase_template()
        po.action_apply_purchase_template()
        after = [(l.display_type, l.product_id.id, l.product_qty, l.price_unit) for l in po.order_line]
        self.assertEqual(before, after)

    def test_reapply_keeps_header(self):
        other_term = self.env['account.payment.term'].create({'name': 'Immediate (test)'})
        po = self._new_po(payment_term_id=other_term.id, note='<p>Custom terms</p>',
                          partner_ref='REF-9')
        po.purchase_template_id = self.template
        po.action_apply_purchase_template()
        self.assertEqual(po.payment_term_id, other_term)
        self.assertIn('Custom terms', po.note)
        self.assertEqual(po.partner_ref, 'REF-9')

    def test_cannot_apply_on_confirmed_order(self):
        po = self._new_po(purchase_template_id=self.template.id)
        po.button_confirm()
        self.assertEqual(po.state, 'purchase')
        with self.assertRaises(UserError):
            po.action_apply_purchase_template()

    def test_apply_without_template_raises(self):
        po = self._new_po()
        with self.assertRaises(UserError):
            po.action_apply_purchase_template()

    # ------------------------------------------------------------------ vendor mapping
    def test_vendor_specific_lines(self):
        self.env['purchase.order.template.line'].create({
            'template_id': self.template.id, 'product_id': self.product_toner.id,
            'product_qty': 1, 'partner_id': self.vendor_b.id, 'sequence': 5})
        po_a = self._new_po(partner=self.vendor_a, purchase_template_id=self.template.id)
        self.assertFalse(self._line(po_a, self.product_toner))
        po_b = self._new_po(partner=self.vendor_b, purchase_template_id=self.template.id)
        self.assertTrue(self._line(po_b, self.product_toner))

    def test_allowed_vendors_and_contacts(self):
        self.template.partner_ids = self.vendor_a
        po_contact = self._new_po(partner=self.vendor_a_contact, purchase_template_id=self.template.id)
        self.assertEqual(len(self._product_lines(po_contact)), 2, "Contacts of an allowed vendor may use it")
        with self.assertRaises(UserError):
            self._new_po(partner=self.vendor_b, purchase_template_id=self.template.id)

    # ------------------------------------------------------------------ archive states
    def test_archived_template(self):
        po = self._new_po(purchase_template_id=self.template.id)
        self.template.action_archive()
        self.assertFalse(self.env['purchase.order.template'].search([('id', '=', self.template.id)]),
                         "Archived templates are not proposed")
        self.assertEqual(len(self._product_lines(po)), 2, "Existing RFQs keep their lines")
        with self.assertRaises(UserError):
            po.action_apply_purchase_template()
        with self.assertRaises(UserError):
            self._new_po(purchase_template_id=self.template.id)

    def test_archived_or_unpurchasable_product_skipped(self):
        self.product_pen.action_archive()
        po = self._new_po(purchase_template_id=self.template.id)
        self.assertEqual(self._product_lines(po).product_id, self.product_paper)

        self.product_pen.action_unarchive()
        self.product_pen.purchase_ok = False
        po.action_apply_purchase_template()
        self.assertEqual(self._product_lines(po).product_id, self.product_paper)
        self.assertIn('Pen', po.message_ids[0].body)

    # ------------------------------------------------------------------ multi-company
    def test_multi_company_template_restrictions(self):
        template_b = self.env['purchase.order.template'].create({
            'name': 'Company B template', 'company_id': self.company_b.id,
            'line_ids': [Command.create({'product_id': self.product_toner.id})],
        })
        po = self._new_po()
        with self.assertRaises(UserError):
            po._purchase_template_apply(template_b)
        with self.assertRaises(UserError):
            # check_company on the many2one
            po.write({'purchase_template_id': template_b.id})

        shared = self.env['purchase.order.template'].create({
            'name': 'Shared', 'company_id': False,
            'line_ids': [Command.create({'product_id': self.product_toner.id, 'product_qty': 2})],
        })
        po_b = self.env['purchase.order'].with_company(self.company_b).create({
            'partner_id': self.vendor_a.id, 'company_id': self.company_b.id,
            'purchase_template_id': shared.id})
        self.assertEqual(po_b.order_line.product_id, self.product_toner)
        self.assertEqual(po_b.order_line.company_id, self.company_b)
        self.assertFalse(po_b.order_line.tax_ids.filtered(lambda t: t.company_id != self.company_b),
                         "Only taxes of the order company are applied")

    def test_shared_template_skips_other_company_products(self):
        product_later_restricted = self.env['product.product'].create({
            'name': 'Later restricted to company A', 'purchase_ok': True})
        shared = self.env['purchase.order.template'].create({
            'name': 'Shared mixed', 'company_id': False,
            'line_ids': [Command.create({'product_id': product_later_restricted.id}),
                         Command.create({'product_id': self.product_toner.id})],
        })
        # the product is restricted to a company after the template was built
        product_later_restricted.company_id = self.company
        po_b = self.env['purchase.order'].with_company(self.company_b).create({
            'partner_id': self.vendor_a.id, 'company_id': self.company_b.id,
            'purchase_template_id': shared.id})
        self.assertEqual(po_b.order_line.product_id, self.product_toner)

    def test_multi_company_record_rule(self):
        template_b = self.env['purchase.order.template'].create({
            'name': 'Company B template', 'company_id': self.company_b.id})
        user = new_test_user(self.env, login='rfq_tpl_user', groups='purchase.group_purchase_user',
                             company_id=self.company.id, company_ids=[Command.set(self.company.ids)])
        Template = self.env['purchase.order.template'].with_user(user)
        visible = Template.search([])
        self.assertIn(self.template, visible)
        self.assertNotIn(template_b, visible)
        with self.assertRaises(AccessError):
            Template.create({'name': 'Users cannot create templates'})

    def test_branch_uses_parent_company_template(self):
        """v17 branches: a parent company template (and its products) is usable in a branch."""
        branch = self.env['res.company'].create({'name': 'RFQ Templates Branch', 'parent_id': self.company.id})
        self.env.user.company_ids |= branch
        self.product_toner.company_id = self.company
        parent_template = self.env['purchase.order.template'].create({
            'name': 'Parent company template', 'company_id': self.company.id,
            'line_ids': [Command.create({'product_id': self.product_toner.id, 'product_qty': 3})],
        })
        po_branch = self.env['purchase.order'].with_company(branch).create({
            'partner_id': self.vendor_a.id, 'company_id': branch.id,
            'purchase_template_id': parent_template.id})
        self.assertEqual(po_branch.order_line.product_id, self.product_toner)
        self.assertEqual(po_branch.order_line.product_qty, 3)

        # ...but a branch template cannot be used by the parent company
        branch_template = self.env['purchase.order.template'].create({
            'name': 'Branch template', 'company_id': branch.id})
        po = self._new_po()
        with self.assertRaises(UserError):
            po._purchase_template_apply(branch_template)
        with self.assertRaises(UserError):
            po.write({'purchase_template_id': branch_template.id})

    def test_duplicated_order_lines_are_manual(self):
        """A duplicated RFQ has no template, so its lines must not be flagged as template lines."""
        po = self._new_po(purchase_template_id=self.template.id)
        self.assertTrue(all(po.order_line.mapped('from_purchase_template')))
        copy = po.copy()
        self.assertFalse(copy.purchase_template_id)
        self.assertTrue(copy.order_line)
        self.assertFalse(any(copy.order_line.mapped('from_purchase_template')))

    def test_copy_several_templates(self):
        """v18: copy() runs on several records at once; each copy keeps its own name."""
        other = self.env['purchase.order.template'].create({'name': 'Pantry Restock'})
        copies = (self.template | other).copy()
        self.assertEqual(copies.mapped('name'), ['Office Supplies (copy)', 'Pantry Restock (copy)'])
        self.assertEqual(len(copies[0].line_ids), len(self.template.line_ids))

    def test_form_quantity_change_reprices(self):
        """v19: loaded lines are not flagged as manual prices (technical_price_unit),
        so changing the quantity in the form re-prices from the vendor price list."""
        po_form = Form(self.env['purchase.order'])
        po_form.partner_id = self.vendor_a
        po_form.purchase_template_id = self.template
        checked = False
        for index in range(len(po_form.order_line)):
            with po_form.order_line.edit(index) as line:
                if line.product_id == self.product_paper:
                    self.assertEqual(line.price_unit, 8.0, "60 units: tier min 50")
                    line.product_qty = 10
                    self.assertEqual(line.price_unit, 10.0, "10 units: back to the min 1 tier")
                    checked = True
        self.assertTrue(checked)
        po = po_form.save()
        self.assertEqual(self._line(po, self.product_paper).price_unit, 10.0)
