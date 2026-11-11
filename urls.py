from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

import views
from forms import LoginForm

admin.site.site_header = "Единство народов — пользователи"
admin.site.site_title = "Управление пользователями"
admin.site.index_title = "Администрирование Django"

urlpatterns = [
    path("", views.event_list, name="event_list"),
    path("events/new/", views.event_edit, name="event_create"),
    path("events/<int:event_id>/", views.event_detail, name="event_detail"),
    path("events/<int:event_id>/edit/", views.event_edit, name="event_edit"),
    path("events/<int:event_id>/cancel/", views.event_cancel, name="event_cancel"),
    path("events/<int:event_id>/join/", views.event_join, name="event_join"),
    path("events/<int:event_id>/leave/", views.event_leave, name="event_leave"),
    path("events/<int:event_id>/review/", views.review_save, name="review_save"),
    path("events/<int:event_id>/review/delete/", views.review_delete, name="review_delete"),
    path("my/", views.my_events, name="my_events"),
    path("management/", views.management, name="management"),
    path("register/", views.register, name="register"),
    path("login/", auth_views.LoginView.as_view(
        template_name="registration/login.html", authentication_form=LoginForm,
    ), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("admin/", admin.site.urls),
]
