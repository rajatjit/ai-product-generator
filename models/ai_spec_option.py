from odoo import fields, models

class AISpecOption(models.Model):
    _name = 'ai.spec.option'
    _description = 'AI Specification Option'
    _order = 'name'

    name = fields.Char(required=True)
    code = fields.Char()
    _sql_constraints = [
        ('name_unique', 'unique(name)', 'Specification option names must be unique.')
    ]