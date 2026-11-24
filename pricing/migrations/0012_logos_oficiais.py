from django.db import migrations


LOGOS = (
    ("lider-pompeia", "pricing/stores/super-lider.png"),
    ("lider-herculandia", "pricing/stores/super-lider.png"),
    ("tauste-marilia", "pricing/stores/tauste.svg"),
    ("confianca-marilia", "pricing/stores/confianca.png"),
)


def assign_logos(apps, schema_editor):
    Store = apps.get_model("pricing", "Store")
    stores = Store.objects.using(schema_editor.connection.alias)
    for slug, logo in LOGOS:
        stores.filter(slug=slug, logo="").update(logo=logo)


def clear_logos(apps, schema_editor):
    Store = apps.get_model("pricing", "Store")
    stores = Store.objects.using(schema_editor.connection.alias)
    for slug, logo in LOGOS:
        stores.filter(slug=slug, logo=logo).update(logo="")


class Migration(migrations.Migration):
    dependencies = [("pricing", "0011_busca_cacheada")]
    operations = [migrations.RunPython(assign_logos, clear_logos)]
