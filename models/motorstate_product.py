# -*- coding: utf-8 -*-
from odoo import fields, models, api, _
import logging
import base64
import requests
from odoo.exceptions import UserError
_logger = logging.getLogger(__name__)

AI_TEXT_FIELDS = (
    'product_title',
    'ecom_description',
    'short_description',
    'ecom_keywords',
)

class MotorState(models.Model):
    _inherit = 'motorstate.product'

    short_description = fields.Char("Short Description")
    ecom_description = fields.Char("eCommerce Description")
    product_title = fields.Char("Product Title")
    ecom_keywords = fields.Char("eCommerce Keywords")
    ecom_disclaimer = fields.Char("eCommerce Disclaimer")
    name = fields.Char(string='Specification Name')
    value = fields.Char(string='Specification Value')
    specification_ids = fields.One2many(
        'motorstate.spec', 'product_id', string='Specifications')
    doc_filename = fields.Char("Document Filename")
    doc_attachment = fields.Binary("Supporting Document",
                                   attachment=True, help="Upload a PDF/DOCX/TXT that will be sent to the AI")
    hide_update_btn = fields.Boolean(
        compute='_compute_hide_update_btn',
        default=False,
    )
    ai_fields_generated = fields.Boolean(
        string="AI Fields Generated",
        compute="_compute_ai_fields_generated",
        store=True
    )
    product_created = fields.Boolean(
        string="Product Created",
        compute="_compute_product_created",
        store=True
    )

    @api.depends('part_number')
    def _compute_hide_update_btn(self):
        for record in self:
            product = self.env['product.template'].search([
                ('default_code', '=', record.part_number)
            ], limit=1)
            record.hide_update_btn = not bool(product)

    @api.depends('product_title','ecom_description','short_description','ecom_keywords',
                 'ecom_disclaimer','specification_ids','specification_ids.name','specification_ids.value')
    def _compute_ai_fields_generated(self):
        def clean(v):
            if not v:
                return ''
            try:
                return html2plaintext(v).strip()
            except Exception:
                return str(v).strip()

        for rec in self:
            has_text = any([
                clean(rec.product_title),
                clean(rec.ecom_description),
                clean(rec.short_description),
                clean(rec.ecom_keywords),
                clean(rec.ecom_disclaimer),
            ])
            has_specs = any(clean(l.name) or clean(l.value) for l in rec.specification_ids)
            rec.ai_fields_generated = bool(has_text or has_specs)
    
    @api.depends('product_temp_id')
    def _compute_product_created(self):
        for record in self:
            product = self.env['product.template'].search([
                ('id', '=', record.product_temp_id.id)
            ], limit=1)
            record.product_created = True if product else False
                           
    def action_generate_ai_fields(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'ai.generated.fields.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_product_id': self.id,
            }
        }

    def action_create_products_from_data(self):
        res = super().action_create_products_from_data()
        """
        Push mapped fields/specs to linked product.template for each selected record.
        """

        Spec = self.env['product.specification']

        for rec in self:
            pt = rec.product_temp_id
            if not pt:
                # Raise on the offending record (shows clean popup)
                raise UserError(_(
                    "Motorstate product '%s' is not linked to a product template."
                ) % (rec.display_name,))

            # Map fields exactly as requested
            vals = {}
            if 'name' in pt._fields:
                vals['name'] = (rec.product_title or pt.name or '').strip()
            if 'ecommerce_description' in pt._fields:
                vals['ecommerce_description'] = rec.ecom_description or ''
            if 'description_ecommerce' in pt._fields:
                vals['description_ecommerce'] = rec.short_description or ''
            if 'ecommerce_disclaimer' in pt._fields:
                vals['ecommerce_disclaimer'] = rec.ecom_disclaimer or ''
            if vals:
                pt.write(vals)
            # Replace specifications for this template
            Spec.search([('product_tmpl_id', '=', pt.id)]).unlink()
            for ms_spec in rec.specification_ids:
                Spec.create({
                    'product_tmpl_id': pt.id,
                    'name': ms_spec.name or '',
                    'value': ms_spec.value or '',
                })
            #Add status and upc to the product template
            pt.write({
                'status': rec.x_studio_motorstate_status,
                'upc': rec.x_studio_upc,
            })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Product Updated"),
                'message': _("Product details are pushed to Product Template."),
                'type': 'success',
            }
        }

class MotorStateProductSpecification(models.Model):
    _name = 'motorstate.spec'
    _description = 'Product Specification'
    
    sequence = fields.Integer(string='Sequence', default=10)
    product_id = fields.Many2one('motorstate.product', string='Product')
    name = fields.Char(string='Specification Name')
    value = fields.Char(string='Specification Value')