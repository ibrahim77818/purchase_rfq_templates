=======================
RFQ / Purchase Templates
=======================

Odoo 16 (Community & Enterprise) — technical name ``purchase_rfq_templates``.

Features
========
* ``purchase.order.template`` / ``purchase.order.template.line``: products, quantities,
  units of measure, sections, notes, optional description override and analytic distribution.
* Vendor mapping: *Default Vendor* (filled on RFQs without vendor), *Allowed Vendors*
  (contacts of an allowed company are accepted), and per-line *Only for Vendor*.
* Header defaults (payment terms, terms & conditions) are applied **only when empty**.
* RFQ form: *RFQ Template* field loads lines instantly (onchange); *Reapply Template*
  button on draft/sent RFQs. Creating an RFQ by code/import with a template and no
  lines applies it automatically (disable with context ``skip_purchase_template_apply``).
* Re-applying replaces only lines previously loaded from a template
  (``from_purchase_template``); manual lines and header data are kept.
* Pricing is native: each line replays the standard product onchange, then the template
  UoM and quantity, then the vendor price computation — so quantity tiers, UoM and
  currency conversion, fiscal-position tax mapping and analytic distribution models
  behave exactly as when a buyer types the line.
* Skipped lines (vendor-specific for another vendor, archived / non-purchasable product,
  product of another company) are reported (form warning or chatter note).
* Multi-company: company-specific or shared templates, ``check_company`` on relations,
  record rules. Purchase users read templates; Purchase managers maintain them.
* Arabic translation (``i18n/ar.po``) and template ``i18n/purchase_rfq_templates.pot``.

Configuration
=============
Purchase ‣ Configuration ‣ RFQ Templates.

Tests
=====
::

    odoo-bin -c odoo.conf -d test_db -i purchase_rfq_templates \
        --test-tags /purchase_rfq_templates --stop-after-init

Author: Ibrahim Yahia — https://www.linkedin.com/in/ibrahim-yahia — LGPL-3
