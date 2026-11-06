"""Aplikacja okienkowa: wklejasz link do quizu Kahoot, widzisz poprawne odpowiedzi."""

import io
import queue
import threading
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageOps, ImageTk

from kahoot_core import (
    KahootError,
    Question,
    Quiz,
    fetch_image_bytes,
    load_quiz,
    quiz_as_text,
)

BG = "#f5f5f7"
INK = "#1d1d1f"
MUTED = "#6e6e73"
GREEN = "#14803c"
RED = "#b3261e"
POLL_MS = 80
IMAGE_WORKERS = 6
IMAGE_MAX_SIZE = (440, 280)


def decode_image(data: bytes, crop: tuple | None) -> Image.Image:
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGBA")
    if crop:
        left, top, right, bottom = crop
        width, height = image.size
        image = image.crop(
            (round(left * width), round(top * height),
             round(right * width), round(bottom * height))
        )
    image.thumbnail(IMAGE_MAX_SIZE, Image.Resampling.LANCZOS)
    return image


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.quiz: Quiz | None = None
        self.loading = False
        self.results: queue.Queue = queue.Queue()
        self.image_jobs: queue.Queue = queue.Queue()
        # None oznacza obrazek, którego nie udało się pobrać.
        self.images: dict[tuple, ImageTk.PhotoImage | None] = {}
        self.requested: set[tuple] = set()
        self.show_wrong = tk.BooleanVar(value=False)

        root.title("Odpowiedzi Kahoot")
        root.geometry("760x640")
        root.minsize(480, 360)
        root.configure(bg=BG)

        top = ttk.Frame(root, padding=(12, 12, 12, 6))
        top.pack(fill="x")
        self.link = tk.StringVar()
        entry = ttk.Entry(top, textvariable=self.link, font=("Segoe UI", 11))
        entry.pack(side="left", fill="x", expand=True, padx=(0, 8), ipady=3)
        entry.bind("<Return>", lambda _event: self.start())
        entry.focus_set()
        self.button = ttk.Button(top, text="Pokaż odpowiedzi", command=self.start)
        self.button.pack(side="left")

        bar = ttk.Frame(root, padding=(12, 0, 12, 6))
        bar.pack(fill="x")
        self.status = ttk.Label(bar, text="Wklej link do quizu i naciśnij Enter.")
        self.status.pack(side="left", fill="x", expand=True)
        self.copy_button = ttk.Button(
            bar, text="Kopiuj", command=self.copy, state="disabled"
        )
        self.copy_button.pack(side="right")
        ttk.Checkbutton(
            bar, text="Pokaż błędne", variable=self.show_wrong, command=self.render
        ).pack(side="right", padx=8)

        body = ttk.Frame(root, padding=(12, 0, 12, 12))
        body.pack(fill="both", expand=True)
        scroll = ttk.Scrollbar(body)
        scroll.pack(side="right", fill="y")
        self.text = tk.Text(
            body,
            wrap="word",
            state="disabled",
            font=("Segoe UI", 11),
            bg="white",
            fg=INK,
            relief="flat",
            padx=14,
            pady=12,
            yscrollcommand=scroll.set,
        )
        self.text.pack(side="left", fill="both", expand=True)
        scroll.config(command=self.text.yview)

        self.text.tag_configure("title", font=("Segoe UI", 16, "bold"), spacing3=2)
        self.text.tag_configure("meta", foreground=MUTED, spacing3=12)
        self.text.tag_configure(
            "question", font=("Segoe UI", 11, "bold"), spacing1=12, spacing3=4
        )
        self.text.tag_configure("kind", foreground=MUTED, font=("Segoe UI", 9))
        self.text.tag_configure(
            "answer", foreground=GREEN, font=("Segoe UI", 11, "bold"), lmargin1=18,
            lmargin2=18,
        )
        self.text.tag_configure("wrong", foreground=RED, lmargin1=18, lmargin2=18)
        self.text.tag_configure("note", foreground=MUTED, lmargin1=18, lmargin2=18)
        self.text.tag_configure("error", foreground=RED)

        for _ in range(IMAGE_WORKERS):
            threading.Thread(target=self.image_worker, daemon=True).start()
        self.root.after(POLL_MS, self.poll)

    def start(self) -> None:
        if self.loading:
            return
        self.loading = True
        self.button.config(state="disabled")
        self.status.config(text="Pobieram quiz...")
        threading.Thread(target=self.fetch, args=(self.link.get(),), daemon=True).start()

    def fetch(self, link: str) -> None:
        try:
            self.results.put(("quiz", load_quiz(link)))
        except KahootError as error:
            self.results.put(("error", str(error)))
        except Exception as error:
            # Kahoot może zmienić format danych; okno nie może wtedy utknąć.
            self.results.put((
                "error",
                f"Kahoot zwrócił dane, których aplikacja nie umie odczytać "
                f"({type(error).__name__}).",
            ))

    def image_worker(self) -> None:
        while True:
            key = self.image_jobs.get()
            url, crop = key
            try:
                image = decode_image(fetch_image_bytes(url), crop)
            except Exception:
                # Zły obrazek nie może psuć quizu: zostanie zamiast niego link.
                image = None
            self.results.put(("image", key, image))

    def poll(self) -> None:
        while True:
            try:
                kind, *payload = self.results.get_nowait()
            except queue.Empty:
                break
            if kind == "image":
                self.image_ready(*payload)
            else:
                self.loading = False
                self.button.config(state="normal")
                if kind == "quiz":
                    self.quiz_ready(*payload)
                else:
                    self.show_error(*payload)
        self.root.after(POLL_MS, self.poll)

    def quiz_ready(self, quiz: Quiz) -> None:
        self.quiz = quiz
        self.copy_button.config(state="normal")
        self.status.config(text=f"Pytań: {len(quiz.questions)}")
        self.render()

    def show_error(self, message: str) -> None:
        self.quiz = None
        self.copy_button.config(state="disabled")
        self.status.config(text="Nie udało się pobrać quizu.")
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("end", message, "error")
        self.text.config(state="disabled")

    def render(self) -> None:
        if self.quiz is None:
            return
        quiz = self.quiz
        text = self.text
        position = text.yview()[0]
        text.config(state="normal")
        text.delete("1.0", "end")
        text.insert("end", quiz.title + "\n", "title")
        text.insert("end", f"Autor: {quiz.author or 'nieznany'}\n", "meta")
        for q in quiz.questions:
            text.insert("end", f"{q.number}. {q.text}\n", "question")
            text.insert("end", f"{q.kind}\n", "kind")
            if q.image:
                self.add_image_slot(q)
            for answer in q.answers:
                text.insert("end", f"✓ {answer}\n", "answer")
            if self.show_wrong.get():
                for answer in q.wrong:
                    text.insert("end", f"✗ {answer}\n", "wrong")
            if q.note:
                text.insert("end", f"{q.note}\n", "note")
        text.config(state="disabled")
        text.yview_moveto(position)

    def add_image_slot(self, q: Question) -> None:
        mark = f"image-{q.number}"
        self.text.mark_set(mark, "end-1c")
        self.text.mark_gravity(mark, "left")
        self.text.insert("end", "\n")
        key = (q.image, q.image_crop)
        if key in self.images:
            self.fill_image_slot(mark, q)
        elif key not in self.requested:
            self.requested.add(key)
            self.image_jobs.put(key)

    def fill_image_slot(self, mark: str, q: Question) -> None:
        photo = self.images[(q.image, q.image_crop)]
        if photo is None:
            self.text.insert(mark, f"Nie udało się wczytać obrazka: {q.image}", "note")
        else:
            self.text.image_create(mark, image=photo)

    def image_ready(self, key: tuple, image: Image.Image | None) -> None:
        self.images[key] = ImageTk.PhotoImage(image) if image else None
        if self.quiz is None:
            return
        self.text.config(state="normal")
        for q in self.quiz.questions:
            if (q.image, q.image_crop) == key:
                self.fill_image_slot(f"image-{q.number}", q)
        self.text.config(state="disabled")

    def copy(self) -> None:
        if self.quiz is None:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(quiz_as_text(self.quiz))
        self.status.config(text="Skopiowano odpowiedzi do schowka.")


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
