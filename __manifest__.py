{
    "name": "Bluemax - AI Product Details Generator",
    "version": "1.0",
    "depends": ["base", "product", "stock", "motorstate_integration"],
    "category": "Productivity",
    "summary": "Generate product fields using AI (OpenAI GPT)",
    "data": [
         "security/ir.model.access.csv",
         "views/motorstate_product_views.xml",
         "views/ai_generated_fields_wizard_view.xml",
         "views/ai_generated_fields_multiple_views.xml",
         "data/ai_spec_option.xml",
         "views/ai_generated_fields_wizard_view.xml",
        #  "views/motorstate_product_actions.xml",
    ],
    "installable": True,
    "application": False,
}
