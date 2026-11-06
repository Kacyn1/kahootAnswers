"""Aplikacja okienkowa: wklejasz link do quizu Kahoot, widzisz poprawne odpowiedzi."""

import queue
import threading
import tkinter as tk
from tkinter import ttk

from kahoot_core import KahootError, Quiz, load_quiz, quiz_as_text

BG = "#f5f5f7"
INK = "#1d1d1f"
MUTED = "#6e6e73"
GREEN = "#14803c"
RED = "#b3261e"
POLL_MS = 80


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.quiz: Quiz | None = None
        self.results: queue.Queue = queue.Queue()
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

    def start(self) -> None:
        link = self.link.get()
        self.button.config(state="disabled")
        self.status.config(text="Pobieram quiz...")
        threading.Thread(target=self.fetch, args=(link,), daemon=True).start()
        self.root.after(POLL_MS, self.poll)

    def fetch(self, link: str) -> None:
        try:
            self.results.put(load_quiz(link))
        except KahootError as error:
            self.results.put(error)

    def poll(self) -> None:
        try:
            result = self.results.get_nowait()
        except queue.Empty:
            self.root.after(POLL_MS, self.poll)
            return
        self.button.config(state="normal")
        if isinstance(result, KahootError):
            self.quiz = None
            self.copy_button.config(state="disabled")
            self.status.config(text="Nie udało się pobrać quizu.")
            self.write([(str(result), "error")])
            return
        self.quiz = result
        self.copy_button.config(state="normal")
        self.status.config(text=f"Pytań: {len(result.questions)}")
        self.render()

    def render(self) -> None:
        if self.quiz is None:
            return
        quiz = self.quiz
        parts = [(quiz.title + "\n", "title")]
        parts.append((f"Autor: {quiz.author or 'nieznany'}\n", "meta"))
        for q in quiz.questions:
            parts.append((f"{q.number}. {q.text}\n", "question"))
            parts.append((f"{q.kind}\n", "kind"))
            parts.extend((f"✓ {answer}\n", "answer") for answer in q.answers)
            if self.show_wrong.get():
                parts.extend((f"✗ {answer}\n", "wrong") for answer in q.wrong)
            if q.note:
                parts.append((f"{q.note}\n", "note"))
        self.write(parts)

    def write(self, parts: list[tuple[str, str]]) -> None:
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        for content, tag in parts:
            self.text.insert("end", content, tag)
        self.text.config(state="disabled")
        self.text.yview_moveto(0)

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
