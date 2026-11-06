"""Pobieranie publicznych quizów Kahoot i wyciąganie z nich poprawnych odpowiedzi."""

import html
import http.client
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field

API_URL = "https://create.kahoot.it/rest/kahoots/{uuid}/card/?includeKahoot=true"
USER_AGENT = "kahoot-answers-desktop"
TIMEOUT_SECONDS = 20
MAX_IMAGE_BYTES = 15 * 1024 * 1024

UUID_PATTERN = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
UUID_RE = re.compile(UUID_PATTERN, re.IGNORECASE)
QUIZ_ID_RE = re.compile(r"quizId=(" + UUID_PATTERN + ")", re.IGNORECASE)

LATEX_RE = re.compile(r"<latex>(.*?)</latex>", re.IGNORECASE | re.DOTALL)
SCRIPT_RE = re.compile(r"<(sub|sup)>(.*?)</\1>", re.IGNORECASE | re.DOTALL)
BREAK_TAG_RE = re.compile(r"<(?:br|p|div|li)(?:\s[^<>]*)?/?>|</(?:p|div|li)>", re.IGNORECASE)
# Tylko znane znaczniki: ogólny wzorzec zjadłby tekst typu "x<y oraz z>3".
TAG_RE = re.compile(
    r"</?(?:b|i|u|s|em|strong|code|pre|span|font|a|ul|ol|h[1-6]|sub|sup|br|p|div|li|latex)"
    r"(?:\s[^<>]*)?/?>",
    re.IGNORECASE,
)
LATEX_COMMAND_RE = re.compile(r"[a-zA-Z]+")

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

# Typy, w których flagi "correct" naprawdę oznaczają poprawną odpowiedź.
SCORED_CHOICE_TYPES = {
    "quiz": "quiz",
    "true_false": "prawda / fałsz",
    "multiple_select_quiz": "wielokrotny wybór",
    "open_ended": "wpisz odpowiedź",
}

TYPE_LABELS = {
    **SCORED_CHOICE_TYPES,
    "jumble": "ułóż w kolejności",
    "slider": "suwak",
    "pin_it": "zaznacz na obrazku",
    **NO_ANSWER_TYPES,
}

BACKSLASH = chr(92)

SUBSCRIPTS = dict(
    zip("0123456789+-−=()aehijklmnoprstuvx", "₀₁₂₃₄₅₆₇₈₉₊₋₋₌₍₎ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ")
)
SUPERSCRIPTS = dict(
    zip(
        "0123456789+-−=()abcdefghijklmnoprstuvwxyzT⊤∘",
        "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁻⁼⁽⁾ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻᵀᵀ°",
    )
)
SCRIPT_CHARS = set(SUBSCRIPTS.values()) | set(SUPERSCRIPTS.values())

LATEX_SYMBOLS = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "varepsilon": "ε", "zeta": "ζ", "eta": "η", "theta": "θ", "vartheta": "ϑ",
    "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ",
    "pi": "π", "rho": "ρ", "sigma": "σ", "tau": "τ", "upsilon": "υ", "phi": "φ",
    "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π",
    "Sigma": "Σ", "Upsilon": "Υ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
    "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥", "neq": "≠", "ne": "≠",
    "ll": "≪", "gg": "≫", "approx": "≈", "sim": "~", "equiv": "≡", "propto": "∝",
    "cdot": "·", "times": "×", "div": "÷", "pm": "±", "mp": "∓", "ast": "*",
    "infty": "∞", "sum": "∑", "prod": "∏", "int": "∫", "partial": "∂", "nabla": "∇",
    "in": "∈", "notin": "∉", "subset": "⊂", "cup": "∪", "cap": "∩", "forall": "∀",
    "exists": "∃", "to": "→", "rightarrow": "→", "leftarrow": "←", "Rightarrow": "⇒",
    "Leftrightarrow": "⇔", "ldots": "…", "dots": "…", "cdots": "⋯", "top": "⊤",
    "circ": "∘", "degree": "°", "quad": " ", "qquad": " ", "%": "%",
}

# Kropka po \left lub \right oznacza "brak nawiasu", więc też znika.
LATEX_IGNORED = {
    "big", "Big", "bigg", "Bigg", "bigl", "bigr", "displaystyle", "textstyle",
    "limits", "nolimits",
}
LATEX_DELIMITERS = {"left", "right"}
LATEX_TEXT_COMMANDS = {
    "text", "textbf", "textit", "textrm", "mathrm", "mathbf", "mathit", "mathsf",
    "mathbb", "mathcal", "operatorname", "boldsymbol",
}
LATEX_ACCENTS = {
    "hat": ("̂", "hat"), "widehat": ("̂", "hat"),
    "bar": ("̄", "bar"), "overline": ("̄", "bar"),
    "tilde": ("̃", "tilde"), "widetilde": ("̃", "tilde"),
    "dot": ("̇", "dot"), "ddot": ("̈", "ddot"), "vec": ("⃗", "vec"),
}
LATEX_FRACTIONS = {"frac", "dfrac", "tfrac", "cfrac"}
LATEX_SPACING = {",": " ", ";": " ", ":": " ", " ": " ", "!": "", BACKSLASH: "; "}


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
    image: str = ""
    # Wycinek obrazka jako ułamki jego wymiarów: (lewo, góra, prawo, dół).
    image_crop: tuple[float, float, float, float] | None = None


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
    # Linki gry mają też hostId, więc quizId musi mieć pierwszeństwo.
    named = QUIZ_ID_RE.search(link)
    if named:
        return named.group(1).lower()
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
    except (OSError, http.client.HTTPException) as error:
        raise KahootError(
            "Nie udało się połączyć z Kahoot. Sprawdź internet i spróbuj ponownie."
        ) from error
    except ValueError as error:
        raise KahootError("Kahoot zwrócił nieczytelną odpowiedź.") from error


def fetch_image_bytes(url: str) -> bytes:
    """Pobiera obrazek pytania. Adres pochodzi od autora quizu, więc tylko https."""
    if not url.lower().startswith("https://"):
        raise ValueError("obrazek nie jest dostępny przez https")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        data = response.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("obrazek jest za duży")
    return data


def to_script(text: str, kind: str) -> str:
    """Zamienia tekst na indeks dolny ("sub") lub górny ("sup")."""
    text = text.strip()
    if not text:
        return ""
    table, marker = (SUBSCRIPTS, "_") if kind == "sub" else (SUPERSCRIPTS, "^")
    if all(char in table for char in text):
        return "".join(table[char] for char in text)
    return marker + text if len(text) == 1 else f"{marker}({text})"


def bracket(text: str) -> str:
    """Dodaje nawias, gdy bez niego zapis a/b byłby niejednoznaczny."""
    return f"({text})" if any(char in " +-−*/=<>," for char in text) else text


def accent(text: str, mark: str, label: str) -> str:
    # Znak łączony działa na jedną literę; indeksy po niej mogą zostać.
    if text and all(char in SCRIPT_CHARS for char in text[1:]):
        return text[0] + mark + text[1:]
    return f"{label}({text})"


class LatexReader:
    """Czytelny zapis wzoru LaTeX: pokrywa to, co spotyka się w quizach."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.position = 0

    def at_end(self) -> bool:
        return self.position >= len(self.source)

    def sequence(self, stop: str = "") -> str:
        parts = []
        while not self.at_end():
            char = self.source[self.position]
            if char == stop:
                self.position += 1
                break
            if char == "}":
                self.position += 1
            elif char in "_^":
                self.position += 1
                parts.append(to_script(self.argument(), "sub" if char == "_" else "sup"))
            elif char in "~&":
                self.position += 1
                parts.append(" ")
            else:
                parts.append(self.atom())
        return "".join(parts)

    def argument(self) -> str:
        while not self.at_end() and self.source[self.position].isspace():
            self.position += 1
        return self.atom()

    def atom(self) -> str:
        if self.at_end():
            return ""
        char = self.source[self.position]
        if char == "{":
            self.position += 1
            return self.sequence("}")
        if char == BACKSLASH:
            return self.command()
        self.position += 1
        return char

    def fraction(self, start: int) -> str:
        top, bottom = self.argument(), self.argument()
        text = f"{bracket(top)}/{bracket(bottom)}"
        before = self.source[start - 1 : start] if start else ""
        rest = self.source[self.position :]
        if before.isdigit():
            # Liczba mieszana: bez spacji 3 i 1/2 zlałyby się w 31/2.
            return f" {text}"
        closes_bracket = rest.startswith(BACKSLASH + "right")
        if before.isalnum() or rest[:1].isalnum() or (
            rest[:1] == BACKSLASH and not closes_bracket
        ):
            # Bez nawiasu 1/2x można odczytać jak 1/(2x).
            return f"({text})"
        return text

    def command(self) -> str:
        start = self.position
        self.position += 1
        match = LATEX_COMMAND_RE.match(self.source, self.position)
        if not match:
            char = self.source[self.position : self.position + 1]
            self.position += 1
            return LATEX_SPACING.get(char, char)
        name = match.group()
        self.position = match.end()
        if name in LATEX_SYMBOLS:
            return LATEX_SYMBOLS[name]
        if name in LATEX_IGNORED:
            return ""
        if name in LATEX_DELIMITERS:
            if self.source[self.position : self.position + 1] == ".":
                self.position += 1
            return ""
        if name in LATEX_TEXT_COMMANDS:
            return self.argument()
        if name in LATEX_ACCENTS:
            return accent(self.argument(), *LATEX_ACCENTS[name])
        if name in LATEX_FRACTIONS:
            return self.fraction(start)
        if name == "binom":
            top, bottom = self.argument(), self.argument()
            return f"C({top}, {bottom})"
        if name == "sqrt":
            return self.root()
        if name in ("begin", "end"):
            self.argument()
            return " "
        # Funkcje typu \ln, \max, \lim czyta się po prostu ich nazwą.
        return name

    def root(self) -> str:
        degree = ""
        if self.source[self.position : self.position + 1] == "[":
            end = self.source.find("]", self.position)
            if end != -1:
                degree = to_script(self.source[self.position + 1 : end], "sup")
                self.position = end + 1
        return f"{degree}√({self.argument()})"


def latex_to_text(source: str) -> str:
    return LatexReader(source).sequence()


def html_to_text(text: str) -> str:
    text = SCRIPT_RE.sub(
        lambda m: to_script(html.unescape(TAG_RE.sub("", m.group(2))), m.group(1).lower()),
        text,
    )
    text = BREAK_TAG_RE.sub(" ", text)
    # Niektóre pytania mają <br> zakodowane jako encję, więc drugi raz po dekodowaniu.
    return BREAK_TAG_RE.sub(" ", html.unescape(TAG_RE.sub("", text)))


def clean(text: str | None) -> str:
    """Zamienia HTML i wzory z treści Kahoota na zwykły tekst."""
    if not text:
        return ""
    # Wzory osobno: w środku bywa "<", którego nie wolno czytać jak znacznika.
    pieces = LATEX_RE.split(text)
    converted = [
        latex_to_text(html.unescape(piece)) if index % 2 else html_to_text(piece)
        for index, piece in enumerate(pieces)
    ]
    return " ".join("".join(converted).split())


def choice_text(choice: dict) -> str:
    text = clean(choice.get("answer"))
    if text:
        return text
    image = choice.get("image")
    return f"[obrazek] {image}" if image else "[pusta odpowiedź]"


def format_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def image_crop(raw: dict) -> tuple[float, float, float, float] | None:
    meta = raw.get("imageMetadata") or {}
    crop = meta.get("crop")
    width, height = meta.get("width"), meta.get("height")
    if not (crop and width and height):
        return None
    # "target" to rozmiar wycinka, a nie jego drugi narożnik.
    left, top = crop["origin"]["x"], crop["origin"]["y"]
    right, bottom = left + crop["target"]["x"], top + crop["target"]["y"]
    return (left / width, top / height, right / width, bottom / height)


def parse_question(number: int, raw: dict) -> Question:
    kind = raw.get("type", "")
    text = clean(raw.get("question")) or clean(raw.get("title")) or "(pytanie bez tekstu)"
    question = Question(number, TYPE_LABELS.get(kind, kind or "nieznany typ"), text)
    question.image = raw.get("image") or ""
    if question.image:
        question.image_crop = image_crop(raw)
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
        if limits.get("correct") is not None:
            question.answers = [format_number(limits["correct"])]
            if limits.get("tolerance"):
                question.note = f"Tolerancja: ±{format_number(limits['tolerance'])}"
        else:
            question.note = "Quiz nie podaje poprawnej wartości."
    elif kind == "pin_it":
        question.note = "Poprawne miejsce to obszar na obrazku. Aplikacja go nie zaznacza."
    elif kind in SCORED_CHOICE_TYPES:
        question.answers = [choice_text(c) for c in choices if c.get("correct")]
        question.wrong = [choice_text(c) for c in choices if not c.get("correct")]
        if not question.answers:
            question.note = "Quiz nie oznacza żadnej odpowiedzi jako poprawnej."
    elif choices:
        # Nieznany typ może być ankietą, w której flagi są ustawione na wszystkim.
        flagged = ", ".join(choice_text(c) for c in choices if c.get("correct"))
        question.note = (
            f"Nieznany typ pytania, więc aplikacja nie wie, czy ma ono poprawną "
            f"odpowiedź. Oznaczone w danych: {flagged or 'brak'}."
        )
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
        if q.image:
            lines.append(f"   (obrazek: {q.image})")
        lines.extend(f"   -> {answer}" for answer in q.answers)
        if q.note:
            lines.append(f"   ({q.note})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
