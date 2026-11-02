# -*- coding: utf-8 -*-
from odoo import fields, models


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    from_purchase_template = fields.Boolean(
        string='Loaded from Template', default=False, copy=False,
        help="Technical: lines loaded from an RFQ template are replaced when a "
             "template is applied again; manual lines are kept.")
