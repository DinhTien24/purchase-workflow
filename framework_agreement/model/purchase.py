# -*- coding: utf-8 -*-
#    Author: Nicolas Bessi, Leonardo Pistone
#    Copyright 2013-2015 Camptocamp SA
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.

from openerp import models, fields, api
from openerp import exceptions, _


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    portfolio_id = fields.Many2one(
        'framework.agreement.portfolio',
        'Portfolio',
        domain="[('supplier_id', '=', partner_id)]",
    )


class PurchaseOrderLine(models.Model):
    """Add on change on price to raise a warning if line is subject to
    an agreement.
    """

    _inherit = "purchase.order.line"

    framework_agreement_id = fields.Many2one(
        'framework.agreement',
        'Agreement',
        domain=[('portfolio_id', '=', 'order_id.portfolio_id')],
    )

    portfolio_id = fields.Many2one(
        'framework.agreement.portfolio',
        'Portfolio',
        readonly=True,
        related='order_id.portfolio_id',
    )

    @api.multi
    def onchange_product_id(self, pricelist_id, product_id, qty, uom_id,
                            partner_id, date_order=False,
                            fiscal_position_id=False, date_planned=False,
                            name=False, price_unit=False, state='draft'):
        res = super(PurchaseOrderLine, self).onchange_product_id(
            pricelist_id,
            product_id,
            qty,
            uom_id,
            partner_id,
            date_order=date_order,
            fiscal_position_id=fiscal_position_id,
            date_planned=date_planned,
            name=name,
            price_unit=price_unit,
        )
        context = self.env.context
        if 'domain' not in res:
            res['domain'] = {}

        if not context.get('portfolio_id') or not product_id:
            res['domain']['framework_agreement_id'] = [('id', '=', 0)]
            res['value']['framework_agreement_id'] = False
            return res

        currency = self.env['res.currency'].browse(context.get('currency_id'))

        ag_domain = [
            ('draft', '=', False),
            ('product_id', '=', product_id),
            ('available_quantity', '>=', qty or 0.0),
            ('portfolio_id', '=', context['portfolio_id']),
        ]
        if date_planned:
            ag_domain += [
                ('start_date', '<=', date_planned),
                ('end_date', '>=', date_planned),
            ]
        if context.get('incoterm_id'):
            ag_domain += [('incoterm_id', '=', context['incoterm_id'])]
        res['domain']['framework_agreement_id'] = ag_domain

        Agreement = self.env['framework.agreement']
        agreement = Agreement.browse(context.get('agreement_id'))
        good_agreements = Agreement.search(ag_domain).filtered(
            lambda a: a.has_currency(currency))

        if agreement and agreement in good_agreements:
            pass  # it's good! let's keep it!
        else:
            if len(good_agreements) == 1:
                cheapest = good_agreements.get_cheapest_in_set(qty, currency)
                agreement = cheapest
            else:
                agreement = Agreement

        if agreement:
            res['value']['price_unit'] = agreement.get_price(qty, currency)
        res['value']['framework_agreement_id'] = agreement.id
        return res

    @api.multi
    def get_agreement_domain(self):
        self.ensure_one()
        domain = [
            ('draft', '=', False),
            ('available_quantity', '>=', self.product_qty),
        ]

        if self.order_id.date_order:
            domain += [
                ('start_date', '<=', self.order_id.date_order),
                ('end_date', '>=', self.order_id.date_order),
            ]
        if self.product_id:
            domain += [('product_id', '=', self.product_id.id)]
        if self.order_id.incoterm_id:
            domain += [('incoterm_id', '=', self.order_id.incoterm_id.id)]
        if self.order_id.portfolio_id:
            domain += [('portfolio_id', '=', self.order_id.portfolio_id.id)]

        return domain

    @api.onchange('price_unit')
    def onchange_price_unit(self):
        if self.framework_agreement_id:
            agreement_price = self.framework_agreement_id.get_price(
                self.product_qty,
                currency=self.order_id.pricelist_id.currency_id)
            if agreement_price != self.price_unit:
                msg = _(
                    "You have set the price to %s \n"
                    " but there is a running agreement"
                    " with price %s") % (
                        self.price_unit, agreement_price
                )
                raise exceptions.Warning(msg)

    @api.multi
    def _propagate_fields(self):
        self.ensure_one()
        agreement = self.framework_agreement_id

        if agreement.payment_term_id:
            self.payment_term_id = agreement.payment_term_id

        if agreement.incoterm_id:
            self.incoterm_id = agreement.incoterm_id

        if agreement.incoterm_address:
            self.incoterm_address = agreement.incoterm_address

    @api.onchange('framework_agreement_id')
    def onchange_agreement(self):
        self._propagate_fields()

        if isinstance(self.id, models.NewId):
            return
        if self.framework_agreement_id:
            agreement = self.framework_agreement_id
            if agreement.supplier_id.id != self.order_id.partner_id:
                raise exceptions.Warning(
                    _('Invalid agreement '
                      'Agreement and supplier does not match')
                )

            raise exceptions.Warning(
                _('Agreement Warning! '
                  'If you change the agreement of this line'
                  ' prices will not be updated.')
            )
