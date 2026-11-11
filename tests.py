"""Запуск: python -m unittest -v. Только временные SQLite-базы, без PostgreSQL.

Рабочие settings.py и database.engine не меняются. Подмена Session действует
лишь в процессе тестов. Данные локальной PostgreSQL-базы не затрагиваются.
"""
import os
import unittest
from datetime import timedelta, timezone as datetime_timezone
from unittest.mock import patch

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")

import database  # Сначала создаём рабочий engine; подключение ещё не открывается.
from django.conf import settings

# Настройки исключительно этого тестового процесса, до инициализации Django.
settings.DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
settings.ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
settings.DEBUG = False

import django
django.setup()

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from sqlalchemy import create_engine, event as sqlalchemy_event, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import seed_data
import views
from database import Base, Event, Registration, Review
from forms import EventForm, RegistrationForm, ReviewForm


class ProjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        call_command("migrate", verbosity=0, interactive=False)

    def setUp(self):
        self.engine = create_engine("sqlite://", poolclass=StaticPool,
                                    connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

        # SQLite теряет часовой пояс DateTime; в PostgreSQL timestamptz его сохраняет.
        @sqlalchemy_event.listens_for(self.session_factory, "loaded_as_persistent")
        def restore_test_timezone(session, obj):
            for name in ("starts_at", "ends_at", "created_at"):
                value = getattr(obj, name, None)
                if value is not None and value.tzinfo is None:
                    setattr(obj, name, value.replace(tzinfo=datetime_timezone.utc))

        self.views_patch = patch.object(views, "Session", self.session_factory)
        self.seed_patch = patch.object(seed_data, "Session", self.session_factory)
        self.views_patch.start()
        self.seed_patch.start()
        self.addCleanup(self.views_patch.stop)
        self.addCleanup(self.seed_patch.stop)
        self.addCleanup(self.engine.dispose)
        User = get_user_model()
        User.objects.all().delete()
        self.user = User.objects.create_user(username="participant")
        self.other = User.objects.create_user(username="another")
        self.admin = User.objects.create_superuser(username="curator", email="")
        self.client = Client()
        self.now = timezone.now().replace(second=0, microsecond=0)
        self.future_id = self.make_event()
        self.past_id = self.make_event(title="Прошедшая встреча", days=-3)

    def make_event(self, title="Керамика Поволжья", days=3, **changes):
        start = self.now + timedelta(days=days)
        values = dict(title=title, description="Знакомство с керамикой.", category="workshop",
                      region="Республика Татарстан", venue="Казань, мастерская",
                      starts_at=start, ends_at=start + timedelta(hours=2), capacity=2)
        values.update(changes)
        with self.session_factory() as session:
            event = Event(**values)
            session.add(event)
            session.commit()
            return event.id

    def sign_up(self, event_id, user=None):
        with self.session_factory() as session:
            session.add(Registration(event_id=event_id, user_id=(user or self.user).id))
            session.commit()

    def count(self, model):
        with self.session_factory() as session:
            return session.scalar(select(func.count()).select_from(model))

    def post(self, route, event_id=None, data=None):
        url = reverse(route, args=[event_id]) if event_id else reverse(route)
        return self.client.post(url, data or {})

    def event_data(self, **changes):
        values = dict(title="Новая выставка", description="Небольшое описание", category="exhibition",
                      region="Москва", venue="Библиотека", capacity="10",
                      starts_at=timezone.localtime(self.now + timedelta(days=6)).strftime("%Y-%m-%dT%H:%M"),
                      ends_at=timezone.localtime(self.now + timedelta(days=6, hours=2)).strftime("%Y-%m-%dT%H:%M"))
        values.update(changes)
        return values

    def test_event_form_required_fields(self):
        form = EventForm({})
        self.assertFalse(form.is_valid())
        self.assertEqual(set(form.errors), set(EventForm.base_fields))

    def test_event_form_dates_capacity_category(self):
        for values in [self.event_data(capacity=0), self.event_data(category="unknown"),
                       self.event_data(ends_at=self.event_data()["starts_at"])]:
            with self.subTest(values=values):
                self.assertFalse(EventForm(values).is_valid())
        self.assertFalse(EventForm(self.event_data(capacity=1), registration_count=2).is_valid())
        form = EventForm(self.event_data(), registration_count=2)
        self.assertTrue(form.is_valid())
        self.assertTrue(timezone.is_aware(form.cleaned_data["starts_at"]))
        self.assertEqual(form.cleaned_data["starts_at"].utcoffset(), timedelta(hours=3))

    def test_review_form_limits(self):
        for data in [{"rating": 0, "text": "Текст"}, {"rating": 6, "text": "Текст"},
                     {"rating": 5, "text": " "}, {"rating": 5, "text": "я" * 1001}]:
            self.assertFalse(ReviewForm(data).is_valid())
        self.assertTrue(ReviewForm({"rating": 4, "text": "Интересная встреча"}).is_valid())

    def test_registration_password_validation(self):
        self.assertFalse(RegistrationForm({"username": "new", "password1": "123", "password2": "123"}).is_valid())
        self.assertFalse(RegistrationForm({"username": "new", "password1": "Long-password-456!", "password2": "other"}).is_valid())

    def test_signup_login_logout_and_password_hash(self):
        password = "Cultural-portal-946!"
        response = self.post("register", data={"username": "newperson", "password1": password, "password2": password})
        self.assertEqual(response.status_code, 302)
        user = get_user_model().objects.get(username="newperson")
        self.assertNotEqual(user.password, password)
        self.assertTrue(user.check_password(password))
        self.assertFalse(user.is_superuser)
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertEqual(self.post("logout").status_code, 302)
        self.assertEqual(self.client.post(reverse("login"), {"username": "newperson", "password": password}).status_code, 302)
        self.assertEqual(self.client.get(reverse("my_events")).status_code, 200)

    def test_guest_pages_and_filters(self):
        second_id = self.make_event(title="Музыка Севера", region="Карелия", category="concert")
        response = self.client.get(reverse("event_list"), {"q": "Керамика", "region": "Республика Татарстан", "category": "workshop"})
        self.assertContainsText(response, "Керамика Поволжья")
        self.assertNotIn("Музыка Севера", response.content.decode())
        self.assertContainsText(self.client.get(reverse("event_detail", args=[second_id])), "Музыка Севера")
        self.assertNotIn("Керамика Поволжья", self.client.get("/", {"q": "%"}).content.decode())

    def assertContainsText(self, response, text):
        self.assertEqual(response.status_code, 200)
        self.assertIn(text, response.content.decode())

    def test_missing_event_and_empty_results(self):
        self.assertEqual(self.client.get("/events/99999/").status_code, 404)
        self.assertContainsText(self.client.get("/", {"q": "несуществующее"}), "Мероприятия не найдены")

    def test_guest_cannot_change_or_access_private_pages(self):
        for route in ["event_join", "event_leave", "review_save", "review_delete", "event_cancel", "event_edit"]:
            self.assertEqual(self.post(route, self.future_id).status_code, 302)
        for route in ["my_events", "management", "event_create"]:
            self.assertEqual(self.client.get(reverse(route)).status_code, 302)
        self.assertEqual(self.count(Registration), 0)

    def test_member_and_staff_without_superuser_cannot_manage(self):
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)
        for route in ["event_create", "management"]:
            self.assertEqual(self.client.get(reverse(route)).status_code, 403)
        self.assertEqual(self.client.get(reverse("event_edit", args=[self.future_id])).status_code, 403)
        self.assertEqual(self.post("event_cancel", self.future_id).status_code, 403)
        self.assertEqual(self.post("event_create", data=self.event_data()).status_code, 403)
        self.assertEqual(self.post("event_edit", self.future_id, self.event_data()).status_code, 403)

    def test_join_and_duplicate(self):
        self.client.force_login(self.user)
        for _ in range(2):
            self.assertEqual(self.post("event_join", self.future_id).status_code, 302)
        self.assertEqual(self.count(Registration), 1)
        self.assertContainsText(self.client.get(reverse("event_detail", args=[self.future_id])), "Вы записаны")

    def test_full_event(self):
        self.sign_up(self.future_id, self.other)
        with self.session_factory() as session:
            session.get(Event, self.future_id).capacity = 1
            session.commit()
        self.client.force_login(self.user)
        self.post("event_join", self.future_id)
        self.assertEqual(self.count(Registration), 1)
        self.assertContainsText(self.client.get(reverse("event_detail", args=[self.future_id])), "Все места заняты")

    def test_started_past_cancelled_events_reject_join(self):
        current_id = self.make_event(days=0, starts_at=self.now - timedelta(minutes=10), ends_at=self.now + timedelta(hours=1))
        cancelled_id = self.make_event(is_cancelled=True)
        self.client.force_login(self.user)
        for event_id in [current_id, self.past_id, cancelled_id]:
            self.post("event_join", event_id)
        self.assertEqual(self.count(Registration), 0)

    def test_leave_own_and_cannot_leave_another_users_registration(self):
        self.sign_up(self.future_id)
        self.sign_up(self.future_id, self.other)
        self.client.force_login(self.user)
        self.post("event_leave", self.future_id, {"user_id": self.other.id})
        self.assertEqual(self.count(Registration), 1)
        with self.session_factory() as session:
            self.assertEqual(session.scalar(select(Registration.user_id)), self.other.id)
        self.post("event_leave", self.future_id, {"user_id": self.other.id})
        self.assertEqual(self.count(Registration), 1)

    def test_cannot_leave_past_event(self):
        self.sign_up(self.past_id)
        self.client.force_login(self.user)
        self.post("event_leave", self.past_id)
        self.assertEqual(self.count(Registration), 1)

    def test_admin_cancel_preserves_registrations_and_my_status(self):
        self.sign_up(self.future_id)
        self.client.force_login(self.admin)
        self.assertEqual(self.post("event_cancel", self.future_id).status_code, 302)
        self.assertEqual(self.count(Registration), 1)
        self.client.force_login(self.user)
        response = self.client.get(reverse("my_events"))
        self.assertContainsText(response, "Отменены организатором")
        self.assertIn("Керамика Поволжья", response.content.decode())
        self.assertContainsText(self.client.get(reverse("event_detail", args=[self.future_id])), "Организатор отменил")

    def test_my_events_groups_and_excludes_other_users(self):
        self.sign_up(self.future_id)
        self.sign_up(self.past_id)
        other_event = self.make_event(title="Чужая запись")
        self.sign_up(other_event, self.other)
        self.client.force_login(self.user)
        response = self.client.get(reverse("my_events"))
        self.assertContainsText(response, "Керамика Поволжья")
        self.assertIn("Прошедшая встреча", response.content.decode())
        self.assertNotIn("Чужая запись", response.content.decode())

    def test_review_create_update_delete(self):
        self.sign_up(self.past_id)
        self.client.force_login(self.user)
        self.assertEqual(self.post("review_save", self.past_id, {"rating": 5, "text": "Отлично"}).status_code, 302)
        self.assertEqual(self.post("review_save", self.past_id, {"rating": 4, "text": "Обновлённый отзыв"}).status_code, 302)
        self.assertEqual(self.count(Review), 1)
        with self.session_factory() as session:
            review = session.scalar(select(Review))
            self.assertEqual((review.rating, review.text), (4, "Обновлённый отзыв"))
        self.post("review_delete", self.past_id)
        self.assertEqual(self.count(Review), 0)

    def test_review_requires_registration_and_finished_non_cancelled_event(self):
        self.client.force_login(self.user)
        self.assertEqual(self.post("review_save", self.past_id, {"rating": 5, "text": "Текст"}).status_code, 403)
        self.sign_up(self.future_id)
        self.assertEqual(self.post("review_save", self.future_id, {"rating": 5, "text": "Текст"}).status_code, 403)
        cancelled = self.make_event(days=-5, is_cancelled=True)
        self.sign_up(cancelled)
        self.assertEqual(self.post("review_save", cancelled, {"rating": 5, "text": "Текст"}).status_code, 403)
        self.assertEqual(self.count(Review), 0)

    def test_invalid_review_keeps_form_errors(self):
        self.sign_up(self.past_id)
        self.client.force_login(self.user)
        response = self.post("review_save", self.past_id, {"rating": 9, "text": "Текст"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("field-errors", response.content.decode())
        self.assertEqual(self.count(Review), 0)

    def test_cannot_edit_or_delete_another_users_review(self):
        self.sign_up(self.past_id, self.other)
        with self.session_factory() as session:
            session.add(Review(event_id=self.past_id, user_id=self.other.id, rating=5, text="Чужой отзыв"))
            session.commit()
        self.client.force_login(self.user)
        self.assertEqual(self.post("review_save", self.past_id, {"user_id": self.other.id, "rating": 1, "text": "Подмена"}).status_code, 403)
        self.assertEqual(self.post("review_delete", self.past_id, {"user_id": self.other.id}).status_code, 404)
        self.sign_up(self.past_id)
        self.post("review_save", self.past_id, {"user_id": self.other.id, "rating": 2, "text": "Мой отзыв"})
        self.assertEqual(self.count(Review), 2)
        with self.session_factory() as session:
            self.assertEqual(session.scalar(select(Review.text).where(Review.user_id == self.other.id)), "Чужой отзыв")

    def test_admin_create_edit_and_capacity_validation(self):
        self.client.force_login(self.admin)
        self.assertContainsText(self.client.get(reverse("event_create")), "Новое мероприятие")
        self.assertEqual(self.post("event_create", data=self.event_data()).status_code, 302)
        self.assertEqual(self.count(Event), 3)
        self.sign_up(self.future_id)
        self.sign_up(self.future_id, self.other)
        response = self.post("event_edit", self.future_id, self.event_data(capacity=1))
        self.assertContainsText(response, "Количество мест не может быть меньше числа заявок")
        with self.session_factory() as session:
            self.assertEqual(session.get(Event, self.future_id).capacity, 2)
        self.assertEqual(self.post("event_edit", self.future_id, self.event_data(capacity=2)).status_code, 302)
        self.assertContainsText(self.client.get(reverse("event_edit", args=[self.future_id])), "Новая выставка")

    def test_admin_summary_and_participant_privacy(self):
        self.sign_up(self.future_id)
        self.client.force_login(self.user)
        response = self.client.get(reverse("event_detail", args=[self.future_id]))
        self.assertNotIn("Этот список доступен только администратору", response.content.decode())
        self.client.force_login(self.admin)
        self.assertContainsText(self.client.get(reverse("event_detail", args=[self.future_id])), "Этот список доступен только администратору")
        self.assertContainsText(self.client.get(reverse("event_detail", args=[self.future_id])), "participant")
        self.assertContainsText(self.client.get(reverse("management")), "Всего заявок")
        self.assertContainsText(self.client.get(reverse("admin:auth_user_changelist")), "participant")

    def test_mutations_require_post(self):
        self.client.force_login(self.admin)
        for route in ["event_join", "event_leave", "event_cancel", "review_save", "review_delete"]:
            self.assertEqual(self.client.get(reverse(route, args=[self.future_id])).status_code, 405)
        self.assertEqual(self.count(Registration), 0)

    def test_csrf_required(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        url = reverse("event_join", args=[self.future_id])
        self.assertEqual(client.post(url).status_code, 403)
        client.get(reverse("event_detail", args=[self.future_id]))
        token = client.cookies["csrftoken"].value
        self.assertEqual(client.post(url, {"csrfmiddlewaretoken": token}).status_code, 302)
        self.assertEqual(self.count(Registration), 1)

    def test_html_is_escaped(self):
        dangerous = '<script>alert("x")</script>'
        with self.session_factory() as session:
            event = session.get(Event, self.future_id)
            event.title = dangerous
            event.description = dangerous
            session.commit()
        response = self.client.get(reverse("event_detail", args=[self.future_id]))
        self.assertNotIn("<script>", response.content.decode())
        self.assertIn("&lt;script&gt;", response.content.decode())

    def test_seed_idempotence_and_states(self):
        with patch("builtins.print"):
            seed_data.seed_data()
            seed_data.seed_data()
        with self.session_factory() as session:
            events = session.scalars(select(Event).where(Event.seed_key.is_not(None))).all()
            self.assertEqual(len(events), 8)
            self.assertTrue(any(e.ends_at < self.now for e in events))
            self.assertTrue(any(e.starts_at > self.now for e in events))
            self.assertTrue(any(e.is_cancelled for e in events))
        self.assertEqual(get_user_model().objects.count(), 3)

    def test_metadata_and_psycopg_configuration(self):
        self.assertEqual(set(Base.metadata.tables), {"culture_events", "culture_registrations", "culture_reviews"})
        self.assertEqual(database.engine.url.drivername, "postgresql+psycopg")


if __name__ == "__main__":
    unittest.main()
