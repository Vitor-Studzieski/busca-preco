from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("pricing", "0003_observation_club_price_and_more")]

    operations = [
        migrations.CreateModel(
            name="InitialAccountSetup",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False,
                                           verbose_name="ID")),
                ("completed_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
    ]
