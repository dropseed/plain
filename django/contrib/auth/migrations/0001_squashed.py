# Generated by Django 5.0.dev20230815211558 on 2023-08-15 21:17

import django.contrib.auth.models
import django.contrib.auth.validators
import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


# Functions from the following migrations need manual copying.
# Move them and any dependencies into this file, then update the
# RunPython operations to refer to the local versions:
# django.contrib.auth.migrations.0011_update_proxy_permissions

class Migration(migrations.Migration):

    replaces = [('auth', '0001_initial'), ('auth', '0002_alter_permission_name_max_length'), ('auth', '0003_alter_user_email_max_length'), ('auth', '0004_alter_user_username_opts'), ('auth', '0005_alter_user_last_login_null'), ('auth', '0006_require_contenttypes_0002'), ('auth', '0007_alter_validators_add_error_messages'), ('auth', '0008_alter_user_username_max_length'), ('auth', '0009_alter_user_last_name_max_length'), ('auth', '0010_alter_group_name_max_length'), ('auth', '0011_update_proxy_permissions'), ('auth', '0012_alter_user_first_name_max_length'), ('auth', '0013_remove_user_groups_alter_permission_unique_together_and_more'), ('auth', '0014_remove_user_first_name_remove_user_last_name')]

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='User',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('password', models.CharField(max_length=128, verbose_name='password')),
                ('last_login', models.DateTimeField(blank=True, null=True, verbose_name='last login')),
                ('is_superuser', models.BooleanField(default=False, help_text='Designates that this user has all permissions without explicitly assigning them.', verbose_name='superuser status')),
                ('username', models.CharField(error_messages={'unique': 'A user with that username already exists.'}, help_text='Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.', max_length=150, unique=True, validators=[django.contrib.auth.validators.UnicodeUsernameValidator()], verbose_name='username')),
                ('email', models.EmailField(blank=True, max_length=254, verbose_name='email address')),
                ('is_staff', models.BooleanField(default=False, help_text='Designates whether the user can log into this admin site.', verbose_name='staff status')),
                ('is_active', models.BooleanField(default=True, help_text='Designates whether this user should be treated as active. Unselect this instead of deleting accounts.', verbose_name='active')),
                ('date_joined', models.DateTimeField(default=django.utils.timezone.now, verbose_name='date joined')),
            ],
            options={
                'swappable': 'AUTH_USER_MODEL',
                'verbose_name': 'user',
                'verbose_name_plural': 'users',
            },
            managers=[
                ('objects', django.contrib.auth.models.UserManager()),
            ],
        ),
    ]
