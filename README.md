# Matrix Finance TUI

Matrix Finance TUI to menedżer finansów osobistych oparty na interfejsie terminalowym (Text User Interface), napisany w języku Python. Projekt stawia na szybkość obsługi za pomocą klawiatury, minimalizm interfejsu oraz architekturę local-first, gwarantującą pełną prywatność danych.

## Główne funkcjonalności

* **Interaktywny pulpit (Dashboard):** Podgląd aktualnych sald (karta/gotówka), wskaźnik zużycia budżetu na bieżący miesiąc oraz kalendarz intensywności wydatków (heatmapa).
* **Zarządzanie transakcjami:** Wprowadzanie, edycja i kategoryzacja przychodów oraz wydatków w ramach paginowanej tabeli z możliwością filtrowania.
* **Skarbonki i cele:** Śledzenie postępów oszczędzania z możliwością bezpośrednich wpłat i wypłat wpływających na główne saldo.
* **Płatności cykliczne:** Zautomatyzowany moduł generujący transakcje dla regularnych rachunków i subskrypcji. System automatycznie wykrywa i sugeruje zaksięgowanie zaległych operacji.
* **Raportowanie i eksport:** Podsumowania bilansowe wybranego okresu, analiza największych wydatków i najdroższych kategorii. Obsługa eksportu danych do formatów TXT oraz CSV.
* **Bezpieczeństwo i backup:** Aplikacja obsługuje profile użytkowników (hashowanie PBKDF2HMAC). Wbudowany mechanizm kopii zapasowej pozwala na eksport bazy danych do pliku zaszyfrowanego algorytmem AES-256 (Fernet) i późniejszy jego import.

## Technologie

* Python 3.10+
* Textual
* SQLite3
* Cryptography

## Instalacja i uruchomienie

1. Sklonuj repozytorium:
    ```bash
    git clone [https://github.com/ArturKnopek/Matrix-Finance-TUI.git](https://github.com/ArturKnopek/Matrix-Finance-TUI.git)
    cd Matrix-Finance-TUI
    ```

2. Utwórz i aktywuj środowisko wirtualne (zalecane):
    ```bash
    python -m venv venv
    
    # Windows:
    venv\Scripts\activate
    
    # Linux/macOS:
    source venv/bin/activate
    ```

3. Zainstaluj zależności:
    ```bash
    pip install -r requirements.txt
    ```

4. Uruchom aplikację:
    ```bash
    python main.py
    ```

## Nawigacja (Skróty klawiszowe)

* `1` - `7` : Przełączanie głównych widoków
* `Ctrl + N` : Dodaj nowy element
* `Ctrl + E` : Edytuj zaznaczony rekord
* `Ctrl + D` : Usuń zaznaczony rekord
* `Ctrl + S` : Zapisz formularz
* `ESC` : Anuluj / Zamknij okno dialogowe
* `Ctrl + R` : Odśwież widok
* `Ctrl + P` : Wstrzymaj płatność cykliczną
* `Ctrl + L` : Wyloguj użytkownika
* `Ctrl + Q` : Wyjście z programu

## Licencja

Projekt udostępniany na licencji MIT.