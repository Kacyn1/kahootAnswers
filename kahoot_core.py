"""Pobieranie publicznych quizów Kahoot i wyciąganie z nich poprawnych odpowiedzi."""

import html
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field

API_URL = "https://create.kahoot.it/rest/kahoots/{uuid}/card/?includeKahoot=true"
USER_AGENT = "kahoot-answers-desktop"
TIMEOUT_SECONDS = 20

UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)
TAG_RE = re.compile(r"<[^>]+>")

# Typy bez dobrej odpowiedzi: flagi "correct" są tu ustawione na wszystkich
# opcjach albo nie ma ich wcale, więc nie można ich traktować jak odpowiedzi.
NO_ANSWER_TYPES = {
    "survey": "ankieta",
    "multiple_select_poll": "ankieta wielokrotnego wyboru",
    "feedback": "pytanie o opinię",
    "brainstorming": "burza mózgów",
    "word_cloud": "chmura słów",
    "open_ended_poll": "ankieta otwarta",
    "drop_pin": "pinezka bez oceniania",
    "scale": "skala",
    "nps": "skala",
}

TYPE_LABELS = {
    "quiz": "quiz",
    "true_false": "prawda / fałsz",
    "multiple_select_quiz": "wielokrotny wybór",
    "open_ended": "wpisz odpowiedź",
    "jumble": "ułóż w kolejności",
    "slider": "suwak",
    "pin_it": "zaznacz na obrazku",
    **NO_ANSWER_TYPES,
}


class KahootError(Exception):
    """Błąd z komunikatem przeznaczonym do pokazania użytkownikowi."""


@dataclass
class Question:
    number: int
    kind: str
    text: str
    answers: list[str] = field(default_factory=list)
    wrong: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class Quiz:
    uuid: str
    title: str
    author: str
    questions: list[Question]


def extract_uuid(link: str) -> str:
    """Zwraca identyfikator quizu z linku albo z samego identyfikatora."""
    link = link.strip()
    if not link:
        raise KahootError("Wklej link do quizu.")
    match = UUID_RE.search(link)
    if match:
        return match.group(0).lower()
    if re.fullmatch(r"[\d\s]{4,10}", link):
        raise KahootError(
            "To wygląda na kod PIN gry. Kod PIN nie wskazuje quizu, który można "
            "pobrać. Wklej link do strony quizu (create.kahoot.it/details/...)."
        )
    raise KahootError(
        "Nie znalazłem identyfikatora quizu w tym linku. Potrzebny jest link w "
        "stylu create.kahoot.it/details/nazwa/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx."
    )


def fetch_quiz_json(uuid: str) -> dict:
    request = urllib.request.Request(
        API_URL.format(uuid=uuid), headers={"User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise KahootError(
                "Ten quiz jest prywatny, więc jego odpowiedzi nie są dostępne."
            ) from error
        if error.code == 404:
            raise KahootError(
                "Nie ma takiego quizu. Mógł zostać usunięty albo jest prywatny."
            ) from error
        raise KahootError(f"Kahoot zwrócił błąd {error.code}.") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise KahootError(
            "Nie udało się połączyć z Kahoot. Sprawdź internet i spróbuj ponownie."
        ) from error
    except ValueError as error:
        raise KahootError("Kahoot zwrócił nieczytelną odpowiedź.") from error


def clean(text: str | None) -> str:
    """Usuwa znaczniki HTML i encje, które Kahoot trzyma w treści pytań."""
    if not text:
        return ""
    return " ".join(html.unescape(TAG_RE.sub("", text)).split())


def choice_text(choice: dict) -> str:
    text = clean(choice.get("answer"))
    if text:
        return text
    image = choice.get("image")
    return f"[obrazek] {image}" if image else "[pusta odpowiedź]"


def format_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def parse_question(number: int, raw: dict) -> Question:
    kind = raw.get("type", "")
    text = clean(raw.get("question")) or clean(raw.get("title")) or "(pytanie bez tekstu)"
    question = Question(number, TYPE_LABELS.get(kind, kind or "nieznany typ"), text)
    choices = raw.get("choices") or []

    if kind in NO_ANSWER_TYPES:
        question.note = "Brak poprawnej odpowiedzi - to pytanie nie jest oceniane."
    elif kind == "jumble":
        # Kolejność na liście to poprawna kolejność; flagi "correct" nic tu nie znaczą.
        question.answers = [
            f"{index}. {choice_text(choice)}"
            for index, choice in enumerate(choices, start=1)
        ]
    elif kind == "slider":
        limits = raw.get("choiceRange") or {}
        if "correct" in limits:
            question.answers = [format_number(limits["correct"])]
            if limits.get("tolerance"):
                question.note = f"Tolerancja: ±{format_number(limits['tolerance'])}"
        else:
            question.note = "Quiz nie podaje poprawnej wartości."
    elif kind == "pin_it":
        question.note = "Poprawne miejsce to obszar na obrazku."
        if raw.get("image"):
            question.note += f" Obrazek: {raw['image']}"
    elif choices:
        question.answers = [choice_text(c) for c in choices if c.get("correct")]
        question.wrong = [choice_text(c) for c in choices if not c.get("correct")]
        if not question.answers:
            question.note = "Quiz nie oznacza żadnej odpowiedzi jako poprawnej."
    else:
        question.note = "Quiz nie podaje odpowiedzi dla tego typu pytania."
    return question


def parse_quiz(data: dict) -> Quiz:
    kahoot = data.get("kahoot")
    if not isinstance(kahoot, dict) or "questions" not in kahoot:
        raise KahootError("Kahoot nie zwrócił pytań dla tego quizu.")
    # Slajdy informacyjne nie są pytaniami, więc nie dostają numeru.
    raws = [q for q in kahoot["questions"] if q.get("type") != "content"]
    return Quiz(
        uuid=kahoot.get("uuid", ""),
        title=clean(kahoot.get("title")) or "(bez tytułu)",
        author=clean(kahoot.get("creator_username")),
        questions=[parse_question(i, q) for i, q in enumerate(raws, start=1)],
    )


def load_quiz(link: str) -> Quiz:
    return parse_quiz(fetch_quiz_json(extract_uuid(link)))


def quiz_as_text(quiz: Quiz) -> str:
    lines = [quiz.title, ""]
    for q in quiz.questions:
        lines.append(f"{q.number}. {q.text}")
        lines.extend(f"   -> {answer}" for answer in q.answers)
        if q.note:
            lines.append(f"   ({q.note})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
