from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User

from database import CATEGORIES


class LoginForm(AuthenticationForm):
    error_messages = {"invalid_login": "Неверное имя пользователя или пароль.",
                      "inactive": "Учётная запись отключена."}


class RegistrationForm(UserCreationForm):
    class Meta:
        model = User
        fields = ["username"]
        labels = {"username": "Имя пользователя"}


class EventForm(forms.Form):
    title = forms.CharField(label="Название", max_length=160)
    description = forms.CharField(label="Описание", widget=forms.Textarea(attrs={"rows": 6}))
    category = forms.ChoiceField(label="Категория", choices=CATEGORIES)
    region = forms.CharField(label="Регион", max_length=100)
    venue = forms.CharField(label="Место проведения", max_length=200)
    starts_at = forms.DateTimeField(
        label="Начало (московское время)", input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
    )
    ends_at = forms.DateTimeField(
        label="Окончание (московское время)", input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
    )
    capacity = forms.IntegerField(label="Количество мест", min_value=1)

    def __init__(self, *args, registration_count=0, **kwargs):
        self.registration_count = registration_count
        super().__init__(*args, **kwargs)

    def clean(self):
        data = super().clean()
        start, end = data.get("starts_at"), data.get("ends_at")
        if start and end and end <= start:
            self.add_error("ends_at", "Окончание должно быть позже начала.")
        if data.get("capacity", 0) < self.registration_count:
            self.add_error("capacity", "Количество мест не может быть меньше числа заявок.")
        return data


class ReviewForm(forms.Form):
    rating = forms.TypedChoiceField(
        label="Оценка", choices=[(i, str(i)) for i in range(1, 6)], coerce=int,
    )
    text = forms.CharField(
        label="Ваш отзыв", max_length=1000,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="До 1000 символов. Расскажите, что вам запомнилось.",
    )
