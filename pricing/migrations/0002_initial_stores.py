from django.db import migrations


STORES = [
    ("lider-pompeia", "lider", "Pompéia", "https://www.smlider.com.br/1"),
    ("lider-herculandia", "lider", "Herculândia", "https://www.smlider.com.br/2"),
    ("tauste-marilia", "tauste", "Marília", "https://tauste.com.br/marilia/"),
    ("confianca-marilia", "confianca", "Marília", "https://www.confianca.com.br/marilia"),
]


def add_stores(apps, schema_editor):
    stores = apps.get_model("pricing", "Store").objects.using(schema_editor.connection.alias)
    for slug, retailer, unit, url in STORES:
        stores.get_or_create(slug=slug, defaults={"retailer": retailer, "unit": unit, "url": url})


class Migration(migrations.Migration):
    dependencies = [("pricing", "0001_initial")]
    operations = [migrations.RunPython(add_stores, migrations.RunPython.noop)]
