from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("pricing", "0004_initialaccountsetup")]

    operations = [
        migrations.AddField(
            model_name="observation",
            name="price_unit",
            field=models.CharField(blank=True, default="", max_length=2, verbose_name="unidade do preço"),
        ),
    ]
