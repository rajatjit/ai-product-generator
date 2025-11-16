# motorstate/wizards/ai_generated_fields_multiple.py

from odoo import _, api, fields, models
from odoo.exceptions import UserError
import json
import base64
from io import BytesIO
from openai import OpenAI

class AIGeneratedFieldsMultiple(models.TransientModel):
    _name = 'ai.generated.fields.multiple'
    _description = 'Generate AI fields for multiple products'

    product_ids = fields.Many2many(
        'motorstate.product',
        string="Products to Process",
    )
    doc_filename = fields.Char("Document Filename")
    doc_attachment = fields.Binary(
        "Supporting Document",
        attachment=True,
        help="Upload a PDF/DOCX/TXT that will be sent to the AI"
    )
    global_prompt = fields.Char(
        "Global Prompt",
        help="Any specific requirements that you want AI to consider goes here."
    )
    generate_title         = fields.Boolean(string="Generate Product Title")
    generate_description   = fields.Boolean(string="Generate Ecom Description")
    generate_keywords      = fields.Boolean(string="Generate Ecom Keywords")
    generate_disclaimer    = fields.Boolean(string="Generate Ecom Disclaimer")
    generate_shortDesc     = fields.Boolean(string="Generate Short Description")
    generate_specifications = fields.Boolean(string="Generate Specifications")
    required_spec_option_ids = fields.Many2many(
        'ai.spec.option',
        string="Required Specifications"
    )

    PRODUCT_CONTENT_SCHEMA = {
        "type": "object",
        "properties": {
            "part_number" : {"type": "string"},
            "product_title": {"type": "string"},
            "short_description": {"type": "string"},
            "ecom_description": {"type": "string"},
            "ecom_keywords": {"type": "string"},
            "ecom_disclaimer": {"type": "string"},
            "specifications": {
                "type": "object",
                "properties": {},
                "additionalProperties": {"type": "string"},
            }
        },
        "required": [
            "part_number",
            "product_title",
            "short_description",
            "ecom_description",
            "ecom_keywords",
            "ecom_disclaimer",
            "specifications"
        ],
        "additionalProperties": False,
    }

    @staticmethod
    def _extract_json_objects(text: str):
        objs = []
        stack = 0
        start = None
        in_str = False
        esc = False

        for i, ch in enumerate(text):
            if ch == '"' and not esc:
                in_str = not in_str
            esc = (ch == '\\' and not esc)
            if in_str:
                continue
            if ch == '{':
                if stack == 0:
                    start = i
                stack += 1
            elif ch == '}':
                if stack:
                    stack -= 1
                    if stack == 0 and start is not None:
                        chunk = text[start:i+1]
                        try:
                            obj = json.loads(chunk)
                            if isinstance(obj, dict):
                                objs.append(obj)
                        except json.JSONDecodeError:
                            pass
                        start = None
        return objs

    @staticmethod
    def _resolve_part_number(d: dict):
        for k in (
            'part_number','Part Number','partNumber',
            'sku','SKU','mpn','MPN','Item Number'
        ):
            if k in d and isinstance(d[k], str) and d[k].strip():
                return d[k].strip()
        specs = d.get('specifications') or {}
        if isinstance(specs, dict):
            for k in (
                'Item Number','Part Number','SKU',
                'MPN','sku','mpn','part_number'
            ):
                v = specs.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
        return None

    def action_generate_ai_fields_multiple(self):
        self.ensure_one()
        if not any([
            self.generate_title,
            self.generate_description,
            self.generate_keywords,
            self.generate_disclaimer,
            self.generate_shortDesc,
            self.generate_specifications,
        ]):
            raise UserError(_("Please select at least one field to generate."))
        if not self.product_ids:
            raise UserError(_("Please select at least one product."))

        mandatory = []
        if self.generate_specifications and self.required_spec_option_ids:
            mandatory = self.required_spec_option_ids.mapped('name')

        api_key = self.env['ir.config_parameter'].sudo().get_param('openai_api_key')
        client = OpenAI(api_key=api_key)

        vs_id = None
        if self.doc_attachment:
            file_data = base64.b64decode(self.doc_attachment)
            file_content = BytesIO(file_data)
            file_name = self.doc_filename or "brand_catalogue.pdf"
            upload = client.files.create(
                file=(file_name, file_content),
                purpose="assistants"
            )
            f_id = upload.id
            if not f_id:
                raise UserError(_("OpenAI upload failed: no file id returned."))
            vector_store = client.vector_stores.create(
                name=f"Knowledge_base_{file_name}",
            )
            vs_id = vector_store.id
            if not vs_id:
                raise UserError(_("Vector store creation returned no id."))
            client.vector_stores.files.create(
                vector_store_id=vs_id,
                file_id=f_id
            )

        for p in self.product_ids:
            base_prompt = (
                f"""
                You are an AI assistant that generates product content for ecommerce website.
                Generate the details for the following product using the available information over the internet and file provided.

                Product Details:
                Part Number: {p.part_number or ''}
                Part Name: {p.part_name or ''}
                Brand: {p.part_brand or ''}
                Product Info: {{\"part_length\": {p.part_length or ''}, \"part_width\": {p.part_width or ''}, \"part_height\": {p.part_height or ''}}}
                Long Description: {p.part_description or ''}
                Category: {{\"Category 1\": {p.categ_lvl_1 or ''}, \"Category 2\": {p.categ_lvl_2 or ''}, \"Category 3\": {p.categ_lvl_3 or ''}}}

                Required Specifications: 
                The JSON field 'specifications' must include ALL of
                f\"these keys (in addition to any others you find): {json.dumps(mandatory)}.\"
                Use EXACT sequence, casing for keys, and supply accurate string values.

                Consider the special requests mentioned here: {self.global_prompt}
                
                Formatting instructions:
                Include all the relevant specifications required related to the product. 
                Make sure the specification title and it's value starts with an upper case always.
                Use only Camel Case for everything you generate even if the information provided is all uppercase.
                """
            )

            stream = client.responses.create(
                model="gpt-4o",
                input=base_prompt,
                tools=[{"type": "web_search_preview"}] if not vs_id else
                      [{"type": "web_search_preview"}, {
                          "type": "file_search",
                          "vector_store_ids": [vs_id]
                      }],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "product_content",
                        "schema": self.PRODUCT_CONTENT_SCHEMA,
                        "strict": True,
                    }
                },
                stream=True,
            )

            buffer = ""
            for chunk in stream:
                if getattr(chunk, 'output_text', None):
                    buffer += chunk.output_text
                    for rec in self._extract_json_objects(buffer):
                        part_no = self._resolve_part_number(rec)
                        prod = self.env['motorstate.product'].search(
                            [('part_number', '=', part_no)], limit=1
                        )
                        if not prod:
                            continue

                        vals = {'ai_response_json': rec}
                        if self.generate_title and rec.get('product_title'):
                            vals['product_title'] = rec['product_title']
                        if self.generate_shortDesc and rec.get('short_description'):
                            vals['short_description'] = rec['short_description']
                        if self.generate_description and rec.get('ecom_description'):
                            vals['ecom_description'] = rec['ecom_description']
                        if self.generate_keywords and rec.get('ecom_keywords'):
                            vals['ecom_keywords'] = rec['ecom_keywords']
                        if self.generate_disclaimer and rec.get('ecom_disclaimer'):
                            vals['ecom_disclaimer'] = rec['ecom_disclaimer']
                        if self.generate_specifications and isinstance(rec.get('specifications'), dict):
                            spec_cmds = [(5, 0, 0)]
                            for k, v in rec['specifications'].items():
                                spec_cmds.append((0, 0, {
                                    'name':  k,
                                    'value': v
                                }))
                            vals['specification_ids'] = spec_cmds

                        prod.write(vals)
                        self.env.cr.commit()

                        buffer = buffer.replace(json.dumps(rec), '')

        return {'type': 'ir.actions.act_window_close'}