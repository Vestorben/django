from functools import wraps

from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods
from sqlalchemy import func, select

from database import CATEGORIES, Event, Registration, Review, Session
from forms import EventForm, RegistrationForm, ReviewForm


def superuser_required(view):
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


def event_or_404(session, event_id):
    event = session.get(Event, event_id)
    if event is None:
        raise Http404("Мероприятие не найдено")
    return event


def registration_count(session, event_id):
    return session.scalar(select(func.count()).select_from(Registration).where(
        Registration.event_id == event_id,
    ))


def event_list(request):
    query = request.GET.get("q", "").strip()[:160]
    region = request.GET.get("region", "").strip()[:100]
    category = request.GET.get("category", "").strip()
    with Session() as session:
        statement = select(Event)
        if query:
            statement = statement.where(Event.title.icontains(query, autoescape=True))
        if region:
            statement = statement.where(Event.region == region)
        if category:
            statement = statement.where(Event.category == category)
        # Сначала предстоящие, затем прошедшие; отменённые остаются видимыми.
        events = session.scalars(statement.order_by(
            (Event.ends_at <= timezone.now()), Event.starts_at,
        )).all()
        regions = session.scalars(select(Event.region).distinct().order_by(Event.region)).all()
        counts = dict(session.execute(select(
            Registration.event_id, func.count(Registration.id),
        ).group_by(Registration.event_id)).all())
        for event in events:
            event.available = max(0, event.capacity - counts.get(event.id, 0))
        return render(request, "event_list.html", {
            "events": events, "regions": regions, "categories": CATEGORIES,
            "query": query, "region": region, "category": category,
        })


def detail_context(session, event, user, review_form=None):
    signed_up = False
    own_review = None
    if user.is_authenticated:
        signed_up = session.scalar(select(Registration.id).where(
            Registration.event_id == event.id, Registration.user_id == user.id,
        )) is not None
        own_review = session.scalar(select(Review).where(
            Review.event_id == event.id, Review.user_id == user.id,
        ))
    reviews = session.scalars(select(Review).where(
        Review.event_id == event.id,
    ).order_by(Review.created_at.desc(), Review.id.desc())).all()
    participants = []
    if user.is_superuser:
        participants = session.scalars(select(Registration).where(
            Registration.event_id == event.id,
        ).order_by(Registration.created_at, Registration.id)).all()
    user_ids = {review.user_id for review in reviews} | {p.user_id for p in participants}
    names = dict(get_user_model().objects.filter(id__in=user_ids).values_list("id", "username"))
    for row in [*reviews, *participants]:
        row.username = names.get(row.user_id, "Удалённый пользователь")
    count = registration_count(session, event.id)
    now = timezone.now()
    can_review = signed_up and event.ends_at <= now and not event.is_cancelled
    if review_form is None:
        initial = {"rating": own_review.rating, "text": own_review.text} if own_review else None
        review_form = ReviewForm(initial=initial)
    return {
        "event": event, "signed_up": signed_up, "own_review": own_review,
        "reviews": reviews, "participants": participants, "count": count,
        "available": max(0, event.capacity - count),
        "can_join": event.starts_at > now and not event.is_cancelled and count < event.capacity,
        "can_leave": signed_up and event.starts_at > now,
        "can_review": can_review, "review_form": review_form,
    }


def event_detail(request, event_id):
    with Session() as session:
        event = event_or_404(session, event_id)
        return render(request, "event_detail.html", detail_context(session, event, request.user))


@login_required
@require_POST
def event_join(request, event_id):
    with Session() as session:
        event = event_or_404(session, event_id)
        existing = session.scalar(select(Registration.id).where(
            Registration.event_id == event_id, Registration.user_id == request.user.id,
        ))
        if existing is not None:
            messages.error(request, "Вы уже записаны на это мероприятие.")
        elif event.is_cancelled:
            messages.error(request, "Мероприятие отменено. Запись закрыта.")
        elif event.starts_at <= timezone.now():
            messages.error(request, "Мероприятие уже началось. Запись закрыта.")
        elif registration_count(session, event_id) >= event.capacity:
            messages.error(request, "Свободных мест нет.")
        else:
            # Обычная последовательная проверка мест для учебного проекта.
            session.add(Registration(event_id=event_id, user_id=request.user.id))
            session.commit()
            messages.success(request, "Вы записаны на мероприятие.")
    return redirect("event_detail", event_id=event_id)


@login_required
@require_POST
def event_leave(request, event_id):
    with Session() as session:
        event = event_or_404(session, event_id)
        registration = session.scalar(select(Registration).where(
            Registration.event_id == event_id, Registration.user_id == request.user.id,
        ))
        if registration is None:
            messages.error(request, "У вас нет заявки на это мероприятие.")
        elif event.starts_at <= timezone.now():
            messages.error(request, "После начала мероприятия отменить запись нельзя.")
        else:
            session.delete(registration)
            session.commit()
            messages.success(request, "Ваша запись отменена.")
    return redirect("event_detail", event_id=event_id)


@login_required
def my_events(request):
    with Session() as session:
        events = session.scalars(select(Event).join(
            Registration, Registration.event_id == Event.id,
        ).where(Registration.user_id == request.user.id).order_by(Event.starts_at)).all()
        now = timezone.now()
        return render(request, "my_events.html", {
            "upcoming": [e for e in events if not e.is_cancelled and e.ends_at > now],
            "past": [e for e in events if not e.is_cancelled and e.ends_at <= now],
            "cancelled": [e for e in events if e.is_cancelled],
        })


@login_required
@require_POST
def review_save(request, event_id):
    with Session() as session:
        event = event_or_404(session, event_id)
        registration = session.scalar(select(Registration.id).where(
            Registration.event_id == event_id, Registration.user_id == request.user.id,
        ))
        if registration is None or event.ends_at > timezone.now() or event.is_cancelled:
            raise PermissionDenied
        form = ReviewForm(request.POST)
        if not form.is_valid():
            return render(request, "event_detail.html", detail_context(
                session, event, request.user, form,
            ), status=400)
        # Берём пользователя только из сессии Django, а не из данных формы.
        review = session.scalar(select(Review).where(
            Review.event_id == event_id, Review.user_id == request.user.id,
        ))
        if review is None:
            review = Review(event_id=event_id, user_id=request.user.id)
            session.add(review)
        review.rating = form.cleaned_data["rating"]
        review.text = form.cleaned_data["text"]
        session.commit()
        messages.success(request, "Ваш отзыв сохранён.")
    return redirect("event_detail", event_id=event_id)


@login_required
@require_POST
def review_delete(request, event_id):
    with Session() as session:
        event_or_404(session, event_id)
        review = session.scalar(select(Review).where(
            Review.event_id == event_id, Review.user_id == request.user.id,
        ))
        if review is None:
            raise Http404("Ваш отзыв не найден")
        session.delete(review)
        session.commit()
        messages.success(request, "Ваш отзыв удалён.")
    return redirect("event_detail", event_id=event_id)


@superuser_required
@require_http_methods(["GET", "POST"])
def event_edit(request, event_id=None):
    with Session() as session:
        event = event_or_404(session, event_id) if event_id else None
        count = registration_count(session, event_id) if event else 0
        initial = {name: getattr(event, name) for name in EventForm.base_fields} if event else None
        form = EventForm(request.POST if request.method == "POST" else None,
                         initial=initial, registration_count=count)
        if request.method == "POST" and form.is_valid():
            if event is None:
                event = Event()
                session.add(event)
            for name, value in form.cleaned_data.items():
                setattr(event, name, value)
            session.commit()
            messages.success(request, "Мероприятие сохранено.")
            return redirect("event_detail", event_id=event.id)
        return render(request, "event_form.html", {"form": form, "event": event, "count": count})


@superuser_required
@require_POST
def event_cancel(request, event_id):
    with Session() as session:
        event = event_or_404(session, event_id)
        event.is_cancelled = True
        session.commit()
        messages.success(request, "Мероприятие отменено. Заявки сохранены.")
    return redirect("event_detail", event_id=event_id)


@superuser_required
def management(request):
    with Session() as session:
        events = session.scalars(select(Event).order_by(Event.starts_at.desc())).all()
        counts = dict(session.execute(select(
            Registration.event_id, func.count(Registration.id),
        ).group_by(Registration.event_id)).all())
        for event in events:
            event.registration_count = counts.get(event.id, 0)
        return render(request, "management.html", {
            "events": events, "total": len(events), "registrations": sum(counts.values()),
            "cancelled_count": sum(event.is_cancelled for event in events),
        })


@require_http_methods(["GET", "POST"])
def register(request):
    if request.user.is_authenticated:
        return redirect("event_list")
    form = RegistrationForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Регистрация завершена. Теперь можно выбрать мероприятие.")
        return redirect("event_list")
    return render(request, "registration/register.html", {"form": form})
