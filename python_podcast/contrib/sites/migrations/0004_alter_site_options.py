# Generated by Django 4.1.4 on 2022-12-11 06:54

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("sites", "0003_set_site_domain_and_name"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="site",
            options={
                "ordering": ["domain"],
                "verbose_name": "site",
                "verbose_name_plural": "sites",
            },
        ),
    ]
