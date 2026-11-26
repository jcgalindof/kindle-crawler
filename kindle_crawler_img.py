
import csv
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs, urlunparse

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout


# ============================================================
# CONFIGURACIÓN
# ============================================================

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
PROFILE_DIR = ROOT / "amazon_profile"

CSV_FILE = DATA_DIR / "kindle_plus_mexico.csv"
JSON_FILE = DATA_DIR / "kindle_plus_mexico.json"
PROGRESS_FILE = DATA_DIR / "image_crawler_progress.json"

BASE_URL = (
    "https://www.amazon.com.mx/s?"
    "i=kindle-unlimited&"
    "srs=9257648011&"
    "rh=n%3A9257648011&"
    "s=popularity-rank&"
    "fs=true"
)

TOTAL_PAGES = 400
DELAY_SECONDS = 5
SAVE_EVERY = 10
HEADLESS = False

DATA_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# CARGAR CATÁLOGO
# ============================================================

def load_catalog():
    if CSV_FILE.exists():
        with CSV_FILE.open(
            "r", encoding="utf-8-sig", newline=""
        ) as f:
            rows = list(csv.DictReader(f))

    elif JSON_FILE.exists():
        rows = json.loads(
            JSON_FILE.read_text(encoding="utf-8")
        )

    else:
        raise FileNotFoundError(
            f"No encontré los archivos en:\n{DATA_DIR}\n"
            "Se necesita kindle_plus_mexico.csv o "
            "kindle_plus_mexico.json"
        )

    books = {}

    for book in rows:
        asin = str(book.get("asin", "")).strip()

        if asin:
            books[asin] = book

    print(f"📚 Catálogo cargado: {len(books)} libros")
    return books


# ============================================================
# GUARDADO SEGURO
# ============================================================

def save_catalog(books):
    rows = list(books.values())

    fields = list(dict.fromkeys(
        key
        for row in rows
        for key in row.keys()
    ))

    for field in [
        "image_url",
        "image_alt",
        "image_seen_at",
        "author"
    ]:
        if field not in fields:
            fields.append(field)

    tmp_json = JSON_FILE.with_suffix(".json.tmp")
    tmp_csv = CSV_FILE.with_suffix(".csv.tmp")

    with tmp_json.open("w", encoding="utf-8") as f:
        json.dump(
            rows,
            f,
            ensure_ascii=False,
            indent=2
        )
        f.flush()
        os.fsync(f.fileno())

    with tmp_csv.open(
        "w", encoding="utf-8-sig", newline=""
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fields,
            extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)
        f.flush()
        os.fsync(f.fileno())

    os.replace(tmp_json, JSON_FILE)
    os.replace(tmp_csv, CSV_FILE)

    print(f"💾 Guardados {len(rows)} libros")


# ============================================================
# PROGRESO
# ============================================================

def load_progress():
    if not PROGRESS_FILE.exists():
        return 1

    try:
        progress = json.loads(
            PROGRESS_FILE.read_text(encoding="utf-8")
        )

        last_page = int(progress.get("last_page", 0))
        return min(max(last_page + 1, 1), TOTAL_PAGES + 1)

    except (ValueError, json.JSONDecodeError):
        return 1


def save_progress(page_number):
    temp = PROGRESS_FILE.with_suffix(".json.tmp")

    temp.write_text(
        json.dumps({
            "last_page": page_number,
            "updated_at": datetime.now(
                timezone.utc
            ).isoformat()
        }, indent=2),
        encoding="utf-8"
    )

    os.replace(temp, PROGRESS_FILE)


# ============================================================
# URL
# ============================================================

def build_page_url(number):
    parsed = urlparse(BASE_URL)
    params = parse_qs(parsed.query)
    params["page"] = [str(number)]

    return urlunparse(
        parsed._replace(
            query=urlencode(params, doseq=True)
        )
    )


# ============================================================
# DETECTAR BLOQUEOS
# ============================================================

def is_blocked(page):
    title = page.title().lower()

    body = page.locator("body").inner_text(
        timeout=10000
    )[:4000].lower()

    markers = [
        "captcha",
        "robot check",
        "enter the characters",
        "ingresa los caracteres",
        "automated access"
    ]

    return any(
        marker in title or marker in body
        for marker in markers
    )


# ============================================================
# EXTRAER IMÁGENES Y AUTORES
# ============================================================

def extract_data(page):
    return page.locator(
        '[data-component-type="s-search-result"][data-asin]'
    ).evaluate_all(
        """cards => cards.map(card => {

            const asin = card.getAttribute("data-asin");

            const img = card.querySelector(
                "img.s-image"
            );

            const imageUrl =
                img?.getAttribute("src") ||
                img?.getAttribute("data-src") ||
                null;

            const imageAlt =
                img?.getAttribute("alt") ||
                null;

            // Buscar autores en el texto próximo al título.
            // No asumir que el texto publicitario es un autor.
            let author = null;

            const heading = card.querySelector("h2");

            if (heading) {
                const container =
                    heading.closest(".a-row")?.parentElement;

                if (container) {
                    const text = container.innerText || "";

                    const match = text.match(
                        /(?:de|por|by)\\s+([^\\n|]+?)(?:\\s*\\||\\s*$)/im
                    );

                    if (match) {
                        author = match[1].trim();
                    }
                }
            }

            return {
                asin,
                image_url: imageUrl,
                image_alt: imageAlt,
                author
            };

        }).filter(item => item.asin)"""
    )


def valid_author(author):
    if not author:
        return False

    author = author.strip()

    if len(author) < 3 or len(author) > 100:
        return False

    invalid = [
        "kindle+",
        "kindle unlimited",
        "gratis con",
        "membresía",
        "paperback",
        "tapa blanda",
        "tapa dura",
        "calificación",
        "estrellas",
        "entrega gratis",
        "comprar"
    ]

    lower = author.lower()

    return not any(term in lower for term in invalid)


# ============================================================
# CRAWLER
# ============================================================

def crawl():
    books = load_catalog()

    start_page = load_progress()

    if start_page > TOTAL_PAGES:
        print("✅ Las 400 páginas ya están procesadas.")
        print(
            "Para repetir la extracción elimina "
            "data/image_crawler_progress.json"
        )
        return

    print(f"🚀 Comenzando desde página {start_page}")
    print(f"📂 Datos: {DATA_DIR}")
    print(f"🖼️ Total de páginas: {TOTAL_PAGES}")

    updated_images = 0
    updated_authors = 0
    last_completed_page = start_page - 1

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=HEADLESS,
            locale="es-MX",
            viewport={
                "width": 1440,
                "height": 1000
            }
        )

        page = (
            context.pages[0]
            if context.pages
            else context.new_page()
        )

        try:
            page.goto(
                "https://www.amazon.com.mx/",
                wait_until="domcontentloaded",
                timeout=45000
            )

            input(
                "\n🔐 Verifica tu sesión en Chromium.\n"
                "Presiona ENTER para comenzar..."
            )

            for number in range(
                start_page,
                TOTAL_PAGES + 1
            ):
                print(
                    f"\n📖 Página {number}/{TOTAL_PAGES}"
                )

                response = page.goto(
                    build_page_url(number),
                    wait_until="domcontentloaded",
                    timeout=45000
                )

                if response and response.status in (
                    403, 429, 503
                ):
                    print(
                        f"⛔ HTTP {response.status}. "
                        "Deteniendo."
                    )
                    break

                if is_blocked(page):
                    print(
                        "⛔ CAPTCHA o bloqueo detectado."
                    )
                    break

                try:
                    page.locator(
                        '[data-component-type="s-search-result"]'
                    ).first.wait_for(timeout=15000)

                except PWTimeout:
                    print(
                        "⚠️ No aparecieron resultados."
                    )
                    break

                results = extract_data(page)

                if not results:
                    print(
                        "⚠️ No se encontraron libros."
                    )
                    break

                images_this_page = 0
                authors_this_page = 0
                matched_this_page = 0

                for item in results:
                    asin = item["asin"]

                    if asin not in books:
                        continue

                    matched_this_page += 1
                    book = books[asin]

                    image_url = item.get("image_url")

                    if image_url:
                        if (
                            book.get("image_url")
                            != image_url
                        ):
                            updated_images += 1
                            images_this_page += 1

                        book["image_url"] = image_url
                        book["image_alt"] = (
                            item.get("image_alt")
                        )
                        book["image_seen_at"] = (
                            datetime.now(
                                timezone.utc
                            ).isoformat()
                        )

                    author = item.get("author")

                    if valid_author(author):
                        old_author = (
                            book.get("author") or ""
                        )

                        if (
                            not valid_author(old_author)
                            and old_author != author
                        ):
                            book["author"] = author
                            updated_authors += 1
                            authors_this_page += 1

                print(
                    f"✅ {len(results)} tarjetas | "
                    f"{matched_this_page} ASIN conocidos"
                )

                print(
                    f"🖼️ Imágenes: +{images_this_page} | "
                    f"✍️ Autores: +{authors_this_page}"
                )

                # Save data first; only then mark progress.
                if number % SAVE_EVERY == 0:
                    save_catalog(books)
                    save_progress(number)

                last_completed_page = number

                if number < TOTAL_PAGES:
                    time.sleep(DELAY_SECONDS)

        except KeyboardInterrupt:
            print(
                "\n⏹️ Interrumpido manualmente."
            )

        except Exception as exc:
            print(f"\n⚠️ Error: {exc}")

        finally:
            save_catalog(books)

            if last_completed_page >= start_page:
                save_progress(last_completed_page)

            context.close()

    with_images = sum(
        bool(book.get("image_url"))
        for book in books.values()
    )

    valid_authors = sum(
        valid_author(book.get("author"))
        for book in books.values()
    )

    print("\n================================")
    print("📚 RESULTADOS")
    print("================================")
    print(f"Libros: {len(books)}")
    print(f"Con imágenes: {with_images}")
    print(f"Con autores válidos: {valid_authors}")
    print(f"Imágenes actualizadas: {updated_images}")
    print(f"Autores corregidos: {updated_authors}")
    print(f"Última página: {last_completed_page}")
    print(f"Archivos: {DATA_DIR}")
    print("================================")


if __name__ == "__main__":
    crawl()
