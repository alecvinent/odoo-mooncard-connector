# -*- coding: utf-8 -*-
# © 2016-2017 Akretion (Alexis de Lattre <alexis.delattre@akretion.com>)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    'name': 'Mooncard Invoice',
    'version': '10.0.2.0.0',
    'category': 'Accounting & Finance',
    'license': 'AGPL-3',
    'summary': 'Create supplier invoices from mooncard transactions',
    'author': 'Akretion',
    'website': 'http://www.akretion.com',
    'depends': ['mooncard_base', 'account_invoice_import'],
    'data': [
        'security/mooncard_security.xml',
        'security/ir.model.access.csv',
        'views/mooncard_transaction.xml',
        'views/mooncard_card.xml',
    ],
    'images': [
        'static/description/banner_odoo_mooncard.jpg',
        'static/description/diagram_odoo_mooncard.jpg',
        ],
    'installable': True,
}
