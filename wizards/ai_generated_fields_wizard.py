from odoo import _, api, fields, models
from odoo.exceptions import UserError
import openai
from openai import OpenAI
import json
import base64
from io import BytesIO
import pdfplumber

class AIGeneratedFieldsWizard(models.TransientModel):
    _name = 'ai.generated.fields.wizard'
    _description = 'AI Field Generator Wizard'

    product_id = fields.Many2one('motorstate.product', required=True, readonly=True)
    doc_filename = fields.Char("Document Filename")
    doc_attachment = fields.Binary("Supporting Document", attachment=True, help="Upload a PDF/DOCX/TXT that will be sent to the AI")
    global_prompt = fields.Char("Global Prompt", help="Any specific requirements that you want AI to consider goes here. Eg: tone, voice, language, keywords, brand info...")
    generate_title = fields.Boolean("Generate Product Title")
    generate_description = fields.Boolean("Generate Ecom Description")
    generate_keywords = fields.Boolean("Generate Ecom Keywords")
    generate_disclaimer = fields.Boolean("Generate Ecom Disclaimer")
    generate_shortDesc = fields.Boolean("Generate Short Description")
    generate_specifications = fields.Boolean("Generate Specifications", default=False)
    required_spec_option_ids = fields.Many2many('ai.spec.option', string="Required Specifications")

    PRODUCT_CONTENT_SCHEMA = {
        "type": "object",
        "properties": {
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
        "required": ["product_title", "short_description", "ecom_description", "ecom_keywords","ecom_disclaimer","specifications"],
        "additionalProperties": False,
    }

    def action_generate_ai_fields(self):
        if not (self.generate_title or self.generate_description or self.generate_keywords or self.generate_shortDesc or self.generate_disclaimer or self.generate_specifications):
            raise UserError(_("Please select at least one field to generate."))
        
        mandatory = []
        if self.generate_specifications and self.required_spec_option_ids:
            mandatory = self.required_spec_option_ids.mapped('name')
        
        product = self.product_id

        #Build Full Prompt
        base_prompt = (
            f"""
            You are an AI assistant that generates product content for ecommerce website.
            Generate the details for the following product using the available information over the internet and file provided.

            Product Details:
            Part Number: {product.part_number or ''}
            Part Name: {product.part_name or ''}
            Brand: {product.part_brand or ''}
            Product Info: {{"part_length": {product.part_length or ''}, "part_width": {product.part_width or ''}, "part_height": {product.part_height or ''}}}
            Long Description: {product.part_description or ''}
            Category: {{"Category 1": {product.categ_lvl_1 or ''}, "Category 2": {product.categ_lvl_2 or ''}, "Category 3": {product.categ_lvl_3 or ''}}}

            Required Specifications: 
            The JSON field 'specifications' must include ALL of
            f"these keys (in addition to any others you find): {json.dumps(mandatory)}."
            Use EXACT sequence, casing for keys, and supply accurate string values.

            Consider the special requests mentioned here: {self.global_prompt}

            Formatting instructions:
            Include all the relevant specifications required related to the product. 
            Make sure the specification title and it's value starts with an upper case always.
            Use only Camel Case for everything you generate even if the information provided is all uppercase. (first letter uppercase, rest all lowercase)"""
        )

        # Call OpenAI
        api_key = self.env['ir.config_parameter'].sudo().get_param('openai_api_key')
        
        client = OpenAI(api_key=api_key)


        #semantic_file_search
        if self.doc_attachment:
            file_data = base64.b64decode(self.doc_attachment)
            file_content = BytesIO(file_data)
            file_name = self.doc_filename or "brand_catalogue.pdf"
            file_tuple = (file_name, file_content)

            upload = client.files.create(                                                       #upload file
                file=file_tuple,
                purpose="assistants"
            )
            f_id = upload.id
            if not f_id:
                raise UserError(_("OpenAI upload failed: no file id returned."))

            vector_store = client.vector_stores.create(                                         #create vectorstore
                name= f"Knowledge_base_{(product.part_brand or self.doc_filename)}",
            )
            vs_id = vector_store.id
            if not vs_id:
                raise UserError(_("Vector store creation returned no id."))

            result = client.vector_stores.files.create(                                         #add uploaded file to the vector_store
                vector_store_id=vs_id,
                file_id=f_id
            )
        
        try:
            if self.doc_attachment:                            #generate with vector_store
                response = client.responses.create(
                    model="gpt-4o",
                    tools=[{
                        "type": "web_search_preview",
                        "type": "file_search",
                        "vector_store_ids": [vs_id]
                        }],
                    input=base_prompt,
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": "product_content",
                            "schema": self.PRODUCT_CONTENT_SCHEMA,
                            "strict": True,
                        }
                    }
                )

            else:                                               #generate without vector_store
                response = client.responses.create(
                    model="gpt-4o",
                    tools=[{
                        "type": "web_search_preview"
                        }],
                    input=base_prompt,
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": "product_content",
                            "schema": self.PRODUCT_CONTENT_SCHEMA,
                            "strict": True,
                        }
                    }
                )
        
            # Try to load JSON response
            try:
                result_json = response.output_text
                data = json.loads(result_json)
            except json.JSONDecodeError as e:
                raise UserError(_("Could not parse AI response as JSON. Response was:\n%s") % result_json)

            if self.generate_title:
                product.product_title = data.get('product_title')
            if self.generate_description:
                product.ecom_description = data.get('ecom_description')
            if self.generate_shortDesc:
                product.short_description = data.get('short_description')
            if self.generate_keywords:
                product.ecom_keywords = data.get('ecom_keywords')
            if self.generate_disclaimer:
                product.ecom_disclaimer = data.get('ecom_disclaimer')
            if self.generate_specifications and data.get('specifications'):
                specs = data.get('specifications')
                product.specification_ids = [(5, 0, 0)]  # Remove existing lines
                # build new lines
                new_lines = []
                for key, full_spec in specs.items():
                    # full_spec is like "Brand: A-1 PRODUCTS"
                    if ': ' in full_spec:
                        name, val = full_spec.split(': ', 1)
                    else:
                        # fallback if no colon
                        name, val = key, full_spec
                    new_lines.append((0, 0, {
                        'product_id': product.id,
                        'name':  name,
                        'value': val,
                    }))

                # assign them
                product.specification_ids = new_lines

        except Exception as e:
            raise UserError(_("OpenAI API Error: %s" % str(e)))

        return {'type': 'ir.actions.act_window_close'}