# -*- coding: utf-8 -*-
# © 2016 Akretion (Alexis de Lattre <alexis.delattre@akretion.com>)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from openerp import models, fields, api, workflow, _
from openerp.exceptions import Warning as UserError
from openerp.tools import float_compare, float_is_zero
import requests
import base64
import logging
from urlparse import urlparse
import os

logger = logging.getLogger(__name__)


class MooncardTransaction(models.Model):
    _inherit = 'mooncard.transaction'

    invoice_id = fields.Many2one(
        'account.invoice', string='Invoice', readonly=True)
    invoice_state = fields.Selection(
        related='invoice_id.state', readonly=True,
        string="Invoice State")
    payment_move_line_id = fields.Many2one(
        'account.move.line', string='Payment Move Line', readonly=True)
    payment_move_id = fields.Many2one(
        'account.move', string="Payment Move",
        related='payment_move_line_id.move_id', readonly=True)
    reconcile_id = fields.Many2one(
        'account.move.reconcile', string="Reconcile",
        related='payment_move_line_id.reconcile_id', readonly=True)
    load_move_id = fields.Many2one(
        'account.move', string="Load Move", readonly=True)

    @api.multi
    def process_line(self):
        # TODO: in the future, we may have to support the case where
        # both mooncard_invoice and mooncard_expense are installed
        for line in self:
            if line.state != 'draft':
                logger.warning(
                    'Skipping mooncard transaction %s which is not draft',
                    line.name)
            if line.transaction_type == 'presentment':
                line.generate_bank_journal_move()
                line.generate_invoice()
                line.reconcile()
                line.state = 'done'
            elif line.transaction_type == 'load':
                line.generate_load_move()
                line.state = 'done'

    @api.multi
    def _prepare_load_move(self):
        self.ensure_one()
        date = self.date[:10]
        period = self.env['account.period'].find(dt=date)
        precision = self.env['decimal.precision'].precision_get('Account')
        load_amount = self.total_company_currency
        if float_compare(load_amount, 0, precision_digits=precision) > 0:
            credit = 0
            debit = load_amount
        else:
            credit = load_amount
            debit = 0
        journal = self.mooncard_token_id.journal_id
        mvals = {
            'journal_id': journal.id,
            'date': date,
            'period_id': period.id,
            'ref': self.name,
            'line_id': [
                (0, 0, {
                    'account_id': journal.default_debit_account_id.id,
                    'debit': debit,
                    'credit': credit,
                    'name': _('Load Mooncard prepaid-account'),
                    }),
                (0, 0, {
                    'account_id':
                    self.company_id.internal_bank_transfer_account_id.id,
                    'debit': credit,
                    'credit': debit,
                    'name': _('Load Mooncard prepaid-account'),
                    }),
                ],
            }
        return mvals

    @api.one
    def generate_load_move(self):
        assert not self.load_move_id, 'already has a load move !'
        if not self.company_id.internal_bank_transfer_account_id:
            raise UserError(_(
                "Missing 'Internal Bank Transfer Account' on company %s.")
                % self.company_id.name)
        if not self.mooncard_token_id.journal_id:
            raise UserError(_(
                "Bank Journal not configured on Mooncard Token '%s'")
                % self.mooncard_token_id.name)
        move = self.env['account.move'].create(self._prepare_load_move())
        move.post()
        self.load_move_id = move.id
        return True

    @api.one
    def generate_bank_journal_move(self):
        assert not self.payment_move_line_id, 'Payment line already created'
        if not self.mooncard_token_id.journal_id:
            raise UserError(_(
                "Bank Journal not configured on Mooncard Token '%s'")
                % self.mooncard_token_id.name)
        journal = self.mooncard_token_id.journal_id
        amlo = self.env['account.move.line']
        date = self.date[:10]
        partner = self.env.ref('mooncard_base.mooncard_supplier')
        period = self.env['account.period'].find(dt=date)
        mvals = {
            'journal_id': journal.id,
            'date': date,
            'period_id': period.id,
            'ref': self.name,
            }
        bank_move = self.env['account.move'].create(mvals)
        expense_amount = self.total_company_currency * -1
        precision = self.env['decimal.precision'].precision_get('Account')
        if float_compare(
                expense_amount, 0, precision_digits=precision) > 0:
            credit = 0
            debit = expense_amount
        else:
            credit = expense_amount
            debit = 0
        mlvals1 = {
            'name': self.description,
            'move_id': bank_move.id,
            'partner_id': partner.id,
            'account_id': partner.property_account_payable.id,
            'credit': credit,
            'debit': debit,
            }
        move_line1 = amlo.create(mlvals1)
        self.payment_move_line_id = move_line1.id
        mlvals2 = {
            'name': self.description,
            'move_id': bank_move.id,
            'partner_id': partner.id,
            'account_id': journal.default_credit_account_id.id,
            'credit': debit,
            'debit': credit,
            }
        amlo.create(mlvals2)
        bank_move.post()

    @api.model
    def _countries_vat_refund(self):
        return self.env.user.company_id.country_id

    @api.one
    def generate_invoice(self):
        assert not self.invoice_id, 'already linked to an invoice'
        assert self.transaction_type == 'presentment', 'wrong transaction type'
        aiio = self.env['account.invoice.import']
        precision = self.env['decimal.precision'].precision_get('Account')
        date = self.date[:10]
        partner = self.env.ref('mooncard_base.mooncard_supplier')
        if not self.product_id:
            raise UserError(_(
                "Missing Expense Product on Mooncard transaction %s")
                % self.name)

        if (
                not float_is_zero(
                    self.vat_company_currency, precision_digits=precision)):
            if (
                    self.country_id and
                    self.company_id.country_id and
                    self.country_id not in self._countries_vat_refund()):
                raise UserError(_(
                    "The mooncard transaction '%s' is associated with country "
                    "'%s'. As we cannot refund VAT from this country, "
                    "the VAT amount of that transaction should be updated "
                    "to 0.")
                    % (self.name, self.country_id.name))
            product_taxes = self.product_id.supplier_taxes_id
            if not product_taxes:
                raise UserError(_(
                    "Missing supplier taxes on product '%s'.")
                    % self.product_id.name_get()[0][1])
            if any([tax.price_include for tax in product_taxes]):
                raise UserError(_(
                    "Supplier taxes on product '%s' must all have the option "
                    "'Tax Included in Price' disabled.")
                    % self.product_id.name_get()[0][1])
        if not self.description:
            raise UserError(_(
                "Missing label on Mooncard transaction %s")
                % self.name)
        url = self.image_url
        if not url:
            raise UserError(_(
                "Missing image URL on Mooncard transaction %s")
                % self.name)
        amount_untaxed = self.total_company_currency * -1\
            - self.vat_company_currency * -1
        rimage = requests.get(url)
        if rimage.status_code != 200:
            raise UserError(_(
                "Could not download the image of Mooncard transaction %s "
                "from URL %s (HTTP error code %s).")
                % (self.name, url, rimage.status_code))
        image_b64 = base64.encodestring(rimage.content)
        file_extension = os.path.splitext(urlparse(url).path)[1]
        filename = 'Receipt-%s%s' % (self.name, file_extension)
        parsed_inv = {
            'partner': {'recordset': partner},
            'date': date,
            'date_due': date,
            'currency': {'recordset': self.company_id.currency_id},
            'amount_total': self.total_company_currency * -1,
            'amount_untaxed': amount_untaxed,
            'invoice_number': self.name,
            'lines': [{
                'product': {'recordset': self.product_id},
                'price_unit': amount_untaxed,
                'name': self.description,
                'qty': 1,
                'uom': {'recordset': self.env.ref('product.product_uom_unit')},
                }],
            'attachments': {filename: image_b64},
            }
        logger.debug('Mooncard invoice import parsed_inv=%s', parsed_inv)
        parsed_inv = aiio.update_clean_parsed_inv(parsed_inv)
        invoice = aiio._create_invoice(parsed_inv)
        invoice.message_post(_(
            "Invoice created from Mooncard transaction %s.") % self.name)
        workflow.trg_validate(
            self._uid, 'account.invoice', invoice.id, 'invoice_open', self._cr)
        assert float_compare(
            invoice.amount_tax, abs(self.vat_company_currency),
            precision_digits=precision) == 0, 'bug on VAT'
        self.invoice_id = invoice.id

    @api.one
    def reconcile(self):
        assert self.payment_move_line_id
        assert self.invoice_id
        assert self.invoice_id.move_id
        assert not self.reconcile_id, 'already has a reconcile mark'
        movelines_to_rec = self.payment_move_line_id
        for line in self.invoice_id.move_id.line_id:
            if line.account_id == self.payment_move_line_id.account_id:
                movelines_to_rec += line
                break
        rec_id = movelines_to_rec.reconcile()
        self.reconcile_id = rec_id