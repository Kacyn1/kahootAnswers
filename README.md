# Odpowiedzi Kahoot

Aplikacja desktopowa: wklejasz link do publicznego quizu Kahoot i widzisz poprawne odpowiedzi do wszystkich pytań.

## Uruchomienie

Wymaga Pythona 3.10+ z Tkinterem. Nie ma zewnętrznych zależności.

```
python kahoot_answers.py
```

## Budowanie pliku .exe

```
pip install pyinstaller
pyinstaller --onefile --windowed --name "Odpowiedzi Kahoot" kahoot_answers.py
```

## Testy

```
python -m unittest
```

## Ograniczenia

- Działa tylko z quizami publicznymi.
- Potrzebny jest link do quizu (`create.kahoot.it/details/...`), a nie kod PIN gry.
- W pytaniach „zaznacz na obrazku” aplikacja nie wskazuje miejsca, tylko podaje link do obrazka.
- Korzysta z nieoficjalnego API Kahoota, które może się zmienić.
