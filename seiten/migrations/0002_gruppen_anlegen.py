from django.db import migrations

GRUPPEN = ["Fördermitglieder", "Mitglieder", "Vorstand"]


def anlegen(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for name in GRUPPEN:
        Group.objects.get_or_create(name=name)


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("seiten", "0001_initial"),
    ]

    operations = [migrations.RunPython(anlegen, migrations.RunPython.noop)]
