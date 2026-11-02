# -*- coding: utf-8 -*-
{
    'name': 'RFQ / Purchase Templates',
    'version': '16.0.1.0.0',
    'summary': 'Reusable RFQ templates: load products, quantities, UoMs, notes '
               'and analytics into purchase orders with native vendor pricing and taxes',
    'description': """
RFQ / Purchase Templates
========================
* Reusable purchase templates with products, quantities, units of measure,
  sections, notes and analytic distribution.
* Vendor-specific mapping: restrict a template to some vendors, propose a default
  vendor, and mark individual lines as vendor-specific.
* Load a template on any draft RFQ from the form (instant) or re-apply it later
  with a button. Manual lines and header data are preserved.
* Prices, vendor price lists (quantity tiers, UoM, currency), fiscal positions,
  taxes and analytic distribution models are computed by Odoo's own purchase engine.
* Multi-company aware, Arabic translation included.
""",
    'category': 'Inventory/Purchase',
    'author': 'Ibrahim Yahia',
    'website': 'https://www.linkedin.com/in/ibrahim-yahia',
    'license': 'LGPL-3',
    'depends': ['purchase'],
    'data': [
        'security/ir.model.access.csv',
        'security/purchase_rfq_templates_security.xml',
        'views/purchase_order_template_views.xml',
        'views/purchase_order_views.xml',
    ],
    'images': ['static/description/banner.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
}
