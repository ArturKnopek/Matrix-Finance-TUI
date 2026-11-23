# Matrix Finance TUI

Matrix Finance TUI to menedżer finansów osobistych oparty na interfejsie terminalowym (Text User Interface), napisany w języku Python. Projekt stawia na szybkość obsługi za pomocą klawiatury, minimalizm interfejsu oraz architekturę local-first, gwarantującą pełną prywatność danych.

## Główne funkcjonalności

* **Interaktywny pulpit (Dashboard):** salda wszystkich kont, środki odłożone w celach i majątek netto, wskaźnik zużycia przychodów w miesiącu, status budżetu kategorii, najbliższe płatności cykliczne (z oznaczeniem zaległych) oraz kalendarz intensywności wydatków (heatmapa skalowana względem najdroższego dnia, podpowiedź z kwotą po najechaniu myszą).
* **Zarządzanie transakcjami:** wprowadzanie, edycja i kategoryzacja przychodów oraz wydatków w paginowanej tabeli z wyszukiwaniem (bez względu na wielkość liter, także polskich) oraz filtrami kategorii i konta.
* **Skarbonki i cele:** śledzenie postępów oszczędzania z wpłatami i wypłatami wpływającymi na saldo konta. Usunięcie celu zwraca zgromadzone środki na konto.
* **Płatności cykliczne:** zlecenia dzienne, tygodniowe, miesięczne i roczne. Silnik księguje **wszystkie** zaległe terminy (np. 3 pominięte miesiące = 3 transakcje), liczy daty od daty startu bez „dryfu” (31. dzień → ostatni dzień krótszego miesiąca), pokazuje najbliższy termin i miesięczny koszt zleceń.
* **Raportowanie i eksport:** bilans, porównanie z poprzednim miesiącem, średnie dzienne, TOP kategorie i sklepy z udziałem procentowym, największy wydatek/dochód. Eksport do TXT oraz CSV (średnik + UTF‑8 z BOM — poprawnie otwiera się w polskim Excelu) do `Dokumenty/Matrix_Raporty`. Archiwizacja miesiąca.
* **Konta:** dowolna liczba kont (Ustawienia → „Nowe konto”), korekta salda dowolnego konta.
* **Bezpieczeństwo i backup:** profile użytkowników (hashowanie PBKDF2‑SHA256). Kopia zapasowa jest spójnym snapshotem bazy (SQLite backup API — działa poprawnie w trybie WAL) zaszyfrowanym AES (Fernet), z możliwością importu.

## Interfejs dopasowujący się do okna

Układ automatycznie reaguje na rozmiar terminala (od ok. 60×20 do bardzo szerokich ekranów):

* **Menu boczne** chowa się, gdy okno ma mniej niż 100 kolumn — numery zakładek widać wtedy w nagłówku. `F2` / `Ctrl+B` pokazuje/ukrywa menu ręcznie, a `ESC` otwiera je chwilowo.
* **Pulpit** przechodzi między układem 1, 2 i 3 kolumn kart; paski postępu i heatmapa skalują się do dostępnego miejsca.
* **Tabele** same dobierają szerokości kolumn: najpierw zwężają długie teksty (z „…”), a dopiero gdy brakuje miejsca — chowają mniej ważne kolumny. Liczba wierszy na stronie zależy od wysokości okna, a zaznaczony rekord zostaje zachowany przy zmianie rozmiaru.
* **Stopka** skraca etykiety skrótów (pełne → krótkie → same klawisze), żeby zawsze się mieściła.
* **Formularze, raporty i okna dialogowe** zmieniają szerokość etykiet, liczbę kolumn i odstępy przy wąskim lub niskim oknie.

## Technologie

* Python 3.10+
* Textual 7
* SQLite3
* Cryptography

## Instalacja i uruchomienie

1. Sklonuj repozytorium:
    ```bash
    git clone https://github.com/ArturKnopek/Matrix-Finance-TUI.git
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
    # testy i budowanie .exe:
    pip install -r requirements-dev.txt
    ```

4. Uruchom aplikację:
    ```bash
    python main.py
    ```

Dane zapisywane są w `~/.matrix_finance/` (`auth.db`, `data/<id_użytkownika>.db`). Błędy trafiają do `~/.matrix_finance/matrix.log`, a po włączeniu opcji „Diagnostyka” w Ustawieniach — szczegółowe logi do `debug.log`.

## Nawigacja (skróty klawiszowe)

| Klawisz | Działanie |
|---|---|
| `1` – `7` | przełączanie zakładek |
| `↑` `↓` / `Tab` | poruszanie się po menu i polach formularza |
| `Enter` | wejście do zakładki · edycja zaznaczonego wiersza · zapis formularza |
| `ESC` | anuluj formularz · powrót do menu · wyczyść filtry |
| `F1` | pomoc (lista skrótów) |
| `F2` / `Ctrl + B` | pokaż/ukryj menu boczne |
| `PgUp` / `PgDn` | poprzednia/następna strona tabeli (strzałki na krawędzi strony też przełączają) |
| `Ctrl + N` | nowy element |
| `Ctrl + E` | edytuj zaznaczony rekord |
| `Ctrl + D` | usuń zaznaczony rekord |
| `Ctrl + S` | zapisz formularz |
| `Ctrl + P` | wstrzymaj/wznów płatność cykliczną |
| `+` / `-` | wpłata / wypłata (zakładka Skarbonki) |
| `/` | wyszukiwanie (zakładka Transakcje) |
| `Ctrl + R` | odśwież i zaksięguj zaległe płatności |
| `Ctrl + L` | wyloguj |
| `Ctrl + Q` | wyjście |

Myszą: pierwsze kliknięcie zaznacza wiersz, kliknięcie w zaznaczony wiersz otwiera edycję.

### Wpisywanie dat i kwot

* **Data:** puste pole = dziś, `wczoraj`, `12` (dzień miesiąca roboczego), `12.05`, `12.05.2026`, `2026-05-12`.
* **Kwota:** `12,50`, `1 200`, a także proste działania, np. `12.5+3*2` albo `(120+80)/2`.

## Testy

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Testy obejmują silnik bazy (salda, płatności cykliczne, archiwum, kopie), parsowanie danych oraz interfejs uruchamiany bez terminala (Textual Pilot) w kilku rozmiarach okna — m.in. sprawdzają, że stopka i kolumny tabel mieszczą się w oknie.

## Migracja ze starej bazy `budget.db`

```bash
python -m src.migrate --old-db sciezka/do/budget.db --user TwojLogin
```

## Licencja

Projekt udostępniany na licencji MIT.
