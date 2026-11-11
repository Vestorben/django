# Django Configuration Guide

Django is a Python web framework with URL routing, HTML templates, forms, authentication, an administration interface, and database migrations. This guide introduces its configuration and points to the official Django 5.2 documentation.

For the application-specific installation steps, database creation commands, and administrator setup, see [SETUP.md](SETUP.md). Actual verification results are recorded in [CHECKS.md](CHECKS.md).

## Install the dependencies

Use Python 3.12 and an activated virtual environment, then install the packages required by this repository:

```bash
python -m pip install -r requirements.txt
python -m django --version
```

## Understand the settings module

Django reads configuration from a Python module selected by `DJANGO_SETTINGS_MODULE`. In this repository, `manage.py` selects the top-level `settings.py` module automatically.

| Setting | Purpose |
| --- | --- |
| `SECRET_KEY` | Signing key; replace the example value with your own random key. |
| `DEBUG` | Enables detailed development error pages. |
| `ALLOWED_HOSTS` | Lists accepted hostnames. |
| `INSTALLED_APPS` | Enables Django applications, including authentication and administration. |
| `MIDDLEWARE` | Configures request handling, sessions, authentication, and CSRF protection. |
| `ROOT_URLCONF` | Selects the URL configuration module. |
| `TEMPLATES` | Configures template directories and context processors. |
| `DATABASES` | Defines database connections. |
| `TIME_ZONE` and `USE_TZ` | Configure local time display and timezone support. |
| `STATIC_URL` and `STATICFILES_DIRS` | Configure local CSS and other static assets. |

Keep `DEBUG = True` for local development only. When disabling it, configure `ALLOWED_HOSTS` for the intended hostnames.

## Configure PostgreSQL

Install PostgreSQL 17, create a database and database user as described in [SETUP.md](SETUP.md), then fill in the connection parameters in `settings.py`:

```python
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "unity",
        "USER": "unity_user",
        "PASSWORD": "replace-with-your-database-password",
        "HOST": "127.0.0.1",
        "PORT": "5432",
    }
}
```

The driver is `psycopg`, installed through `psycopg[binary]` in `requirements.txt`. This application also uses SQLAlchemy, which reads the same connection settings and manages separate event, registration, and review tables.

## Initialize and check the application

Once the settings are complete, initialize the two sets of tables:

```bash
python manage.py migrate
python init_db.py
python manage.py createsuperuser
python manage.py check
python manage.py runserver
```

Django migrations create the authentication, administration, and session tables. The separate initialization script creates SQLAlchemy tables; it does not update existing table structures. Open http://127.0.0.1:8000/ after starting the development server.

## Official documentation

- [Django 5.2 documentation](https://docs.djangoproject.com/en/5.2/)
- [First application tutorial](https://docs.djangoproject.com/en/5.2/intro/tutorial01/)
- [How settings work](https://docs.djangoproject.com/en/5.2/topics/settings/)
- [Settings reference](https://docs.djangoproject.com/en/5.2/ref/settings/)
- [PostgreSQL database notes](https://docs.djangoproject.com/en/5.2/ref/databases/#postgresql-notes)
