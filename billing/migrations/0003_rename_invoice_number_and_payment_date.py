# Generated for renaming invoice_number -> number and payment_date -> date

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0002_phase1_models'),
    ]

    operations = [
        migrations.RenameField(
            model_name='invoice',
            old_name='invoice_number',
            new_name='number',
        ),
        migrations.RenameField(
            model_name='payment',
            old_name='payment_date',
            new_name='date',
        ),
        migrations.AlterModelOptions(
            name='payment',
            options={'ordering': ['-date', '-created_at'], 'verbose_name': 'Payment', 'verbose_name_plural': 'Payments'},
        ),
    ]
