# -*- coding: utf-8 -*-
# © 2016 Akretion (Alexis de Lattre <alexis.delattre@akretion.com>)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from openerp import models, fields, api, _
from openerp.exceptions import ValidationError


class MooncardCard(models.Model):
    _name = 'mooncard.card'
    _description = 'Moon Card'

    code = fields.Char(string='Short Name')
    user_id = fields.Many2one(
        'res.users', string='User',
        help="Link to user ; only for information purpose.")
    name = fields.Char(
        string='Card/Account Number', required=True, size=9, copy=False,
        help="Enter the 9 digits number written at the bottom of the "
        "front side of your Moon Card. You also need to create an entry "
        "for your multi-card account, cf the Accounts menu entry in "
        "the Mooncard web interface.")
    active = fields.Boolean(string='Active', default=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env['res.company']._company_default_get(
            'mooncard.card'))

    def name_get(self):
        res = []
        for card in self:
            dname = card.name
            if card.code:
                dname = '%s (%s)' % (dname, card.code)
            res.append((card.id, dname))
        return res

    @api.one
    @api.constrains('name')
    def name_check(self):
        if self.name and not self.name.isdigit():
            raise ValidationError(_(
                "'%s' is not a valid Mooncard card/account number. "
                "It should only have digits") % self.name)

    _sql_constrains = [(
        'token_uniq',
        'unique(name)',
        'This Moon Card already exists in the database!'
        )]
