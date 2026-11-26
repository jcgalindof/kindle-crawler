#!/usr/bin/env python3
"""Crawler incremental del catálogo Kindle+ México.

Recorre las 26 categorías temáticas inmediatas de Kindle+ y mezcla cada tarjeta
con el catálogo existente por ASIN. Nunca reemplaza metadatos válidos con
valores vacíos o promocionales.

Prueba segura de una sola página (no modifica el catálogo):
    python kindle_crawler.py --validate-only

Corrida normal, reanudable:
    python kindle_crawler.py

Nueva corrida desde la primera fuente, conservando el catálogo:
    python kindle_crawler.py --restart
"""

import argparse
import csv
import hashlib
import json
import os
import random
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
PROFILE = ROOT / "amazon_profile_categories"

CATALOG_URL = (
    "https://www.amazon.com.mx/b/ref=ku_br_rw_lp_mn?node=9257648011"
)
LEGACY_GENERAL_ID = "catalog"

CATEGORIES_FILE = DATA / "amazon_main_categories.json"
BASE_BOOKS_FILE = DATA / "kindle_plus_mexico.json"
LEGACY_CATEGORIZED_FILE = DATA / "kindle_plus_mexico_categorized.json"
OUTPUT_JSON = DATA / "kindle_plus_mexico_2.0.json"
OUTPUT_CSV = DATA / "kindle_plus_mexico_2.0.csv"
STATE_FILE = DATA / "kindle_plus_mexico_2.0_progress.json"
REPORT_FILE = DATA / "kindle_plus_mexico_2.0_report.json"

STATE_VERSION = 3
DEFAULT_DELAY = 9.0
LEGACY_PAGE_LIMIT = 25

ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")
BAD_AUTHOR_RE = re.compile(
    r"kindle\+|kindle unlimited|gratis con|membres[ií]a|aprende m[aá]s|"
    r"tapa blanda|paperback|calificaci[oó]n|estrellas|env[ií]o gratis|comprar|"
    r"ofertas? nuevas?|disponible al instante|patrocinado|p[aá]gina del producto",
    re.IGNORECASE,
)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def save_json(path, value, *, compact=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(
            value,
            handle,
            ensure_ascii=False,
            indent=None if compact else 2,
            separators=(",", ":") if compact else None,
        )
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def clean_text(value):
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split()).strip()
    return cleaned or None


def valid_author(value):
    value = clean_text(value)
    return bool(
        value
        and 3 <= len(value) <= 160
        and not BAD_AUTHOR_RE.search(value)
    )


def has_verified_author(book):
    return (
        book.get("author_source") in ("amazon_search_card", "amazon_product_page")
        and valid_author(book.get("author"))
    )


def valid_asin(value):
    return bool(ASIN_RE.fullmatch(str(value or "").strip().upper()))


def normalize_categories(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            value = [value]
    if not isinstance(value, list):
        return []
    return sorted({
        clean_text(item)
        for item in value
        if clean_text(item) and clean_text(item) != "Tienda Kindle"
    })


def load_books():
    source = next(
        path for path in (
            OUTPUT_JSON,
            LEGACY_CATEGORIZED_FILE,
            BASE_BOOKS_FILE,
        )
        if path.exists()
    )
    rows = load_json(source)
    if not isinstance(rows, list):
        raise ValueError(f"{source} debe contener una lista JSON")

    books = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        asin = str(row.get("asin") or "").strip().upper()
        if not valid_asin(asin):
            continue
        book = dict(row)
        book["asin"] = asin
        book["amazon_categories"] = normalize_categories(
            book.get("amazon_categories", book.get("categories", []))
        )
        books[asin] = book
    return books, source


def load_categories():
    rows = load_json(CATEGORIES_FILE)
    categories = []
    for row in rows:
        name = clean_text(row.get("name"))
        url = clean_text(row.get("url"))
        if (
            name
            and url
            and name != "Tienda Kindle"
            and "srs=9257648011" in url
        ):
            categories.append({
                "id": str(row["id"]),
                "name": name,
                "url": url,
            })
    if len(categories) != 26:
        raise ValueError(
            f"Se esperaban 26 categorías temáticas y se encontraron "
            f"{len(categories)}"
        )
    return categories


def page_url(base_url, number):
    parsed = urlparse(base_url)
    query = parse_qs(parsed.query)
    query["page"] = [str(number)]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def is_blocked(page):
    body = page.locator("body").inner_text(timeout=10000)[:5000].lower()
    text = f"{page.title()} {body}".lower()
    return any(marker in text for marker in (
        "captcha",
        "robot check",
        "enter the characters",
        "ingresa los caracteres",
        "automated access",
    ))


def response_guard(response, page):
    if response and response.status in (403, 429, 503):
        raise RuntimeError(f"Amazon respondió HTTP {response.status}")
    if is_blocked(page):
        raise RuntimeError(
            "Amazon mostró CAPTCHA o bloqueo. Se detuvo sin intentar evadirlo."
        )


def wait_for_cards(page, timeout=15000):
    selector = '[data-component-type="s-search-result"][data-asin]'
    page.locator(selector).first.wait_for(timeout=timeout)


def extract_books(page, source_name, source_category, page_number):
    selector = '[data-component-type="s-search-result"][data-asin]'
    return page.locator(selector).evaluate_all(
        """(cards, args) => {
            const text = node => node?.innerText?.replace(/\\s+/g, ' ').trim() || null;

            const first = (card, selectors) => {
                for (const selector of selectors) {
                    const node = card.querySelector(selector);
                    if (node) return node;
                }
                return null;
            };

            const badAuthor = value => !value ||
                /Kindle\\+|Kindle Unlimited|Gratis con|membres[ií]a|Aprende m[aá]s|tapa blanda|paperback|estrellas|calificaci[oó]n/i.test(value);

            const authorFromCard = card => {
                const authorSelectors = [
                    'a[href*="field-author="]',
                    'a[href*="rh=p_27"]',
                    'a[href*="p_27%3A"]'
                ];
                const names = [];
                for (const selector of authorSelectors) {
                    for (const node of card.querySelectorAll(selector)) {
                        const value = text(node);
                        if (value && !badAuthor(value) && !names.includes(value)) {
                            names.push(value);
                        }
                    }
                    if (names.length) break;
                }
                if (names.length) return names.join(', ');

                const rows = card.querySelectorAll(
                    '.a-row.a-size-base.a-color-secondary, [data-cy="title-recipe"] h2 + div'
                );
                for (const row of rows) {
                    const value = text(row);
                    if (!value || badAuthor(value)) continue;
                    const match = value.match(/^(?:de|por|by)\\s+(.+?)(?:\\s+[|·]\\s+|$)/i);
                    if (match && match[1] && !badAuthor(match[1])) return match[1].trim();
                }
                return null;
            };

            return cards.map(card => {
                const asin = (card.getAttribute('data-asin') || '').trim().toUpperCase();
                const titleNode = first(card, [
                    '[data-cy="title-recipe"] h2 span',
                    'h2 a span',
                    'h2 span',
                    'h2'
                ]);
                const linkNode = first(card, [
                    '[data-cy="title-recipe"] a[href]',
                    'h2 a[href]',
                    'a.a-link-normal.s-no-outline[href]'
                ]);
                const ratingNode = first(card, ['span.a-icon-alt']);
                const reviewNode = first(card, [
                    'span.a-size-base.s-underline-text',
                    'a[href*="customerReviews"] span',
                    'a[aria-label*="calificaciones"]'
                ]);
                const imageNode = first(card, ['img.s-image', 'img[data-image-latency]']);
                const fullText = card.innerText || '';
                const eligibility = fullText.match(
                    /Kindle\\+|Kindle Unlimited|Gratis con la membres[ií]a/i
                );
                const rawUrl = linkNode?.getAttribute('href');
                const url = rawUrl
                    ? new URL(rawUrl, location.origin).href
                    : (asin ? `https://www.amazon.com.mx/dp/${asin}` : null);

                return {
                    asin,
                    title: text(titleNode),
                    author: authorFromCard(card),
                    url,
                    rating: text(ratingNode),
                    review_count: text(reviewNode),
                    image_url: imageNode?.currentSrc || imageNode?.src || null,
                    image_alt: imageNode?.alt || text(titleNode),
                    kindle_plus_eligible: Boolean(eligibility),
                    eligibility_evidence: eligibility?.[0] || null,
                    source_name: args.sourceName,
                    source_category: args.sourceCategory,
                    page_number: args.pageNumber,
                    collected_at: new Date().toISOString()
                };
            }).filter(book => /^[A-Z0-9]{10}$/.test(book.asin) && book.title);
        }""",
        {
            "sourceName": source_name,
            "sourceCategory": source_category,
            "pageNumber": page_number,
        },
    )


def next_page_url(page):
    link = page.locator(".s-pagination-next")
    if link.count() == 0:
        return None
    link = link.first
    if (
        link.get_attribute("aria-disabled") == "true"
        or "s-pagination-disabled" in (link.get_attribute("class") or "").split()
    ):
        return None
    href = link.get_attribute("href")
    if not href:
        raise RuntimeError("El botón Siguiente está activo, pero no tiene enlace")
    target = urljoin(page.url, href)
    parsed = urlparse(target)
    if parsed.scheme != "https" or parsed.hostname != "www.amazon.com.mx":
        raise RuntimeError("El enlace Siguiente apunta fuera de Amazon México")
    return target


def signature_key(asins):
    return hashlib.sha256(",".join(sorted(set(asins))).encode("ascii")).hexdigest()


def merge_book(existing, incoming, category):
    book = dict(existing or {})
    changes = []

    def set_if_missing(key, value):
        value = clean_text(value) if isinstance(value, str) else value
        if value not in (None, "", [], {}) and book.get(key) in (None, "", [], {}):
            book[key] = value
            changes.append(key)

    book["asin"] = incoming["asin"]
    set_if_missing("title", incoming.get("title"))

    candidate_author = incoming.get("author")
    if valid_author(candidate_author) and not has_verified_author(book):
        book["author"] = clean_text(candidate_author)
        book["author_source"] = "amazon_search_card"
        changes.append("author")

    for key in (
        "url", "rating", "review_count", "image_url", "image_alt",
        "eligibility_evidence", "collected_at",
    ):
        set_if_missing(key, incoming.get(key))

    if incoming.get("kindle_plus_eligible") and not (
        book.get("kindle_plus_eligible") is True
        or str(book.get("kindle_plus_eligible")).lower() == "true"
    ):
        book["kindle_plus_eligible"] = True
        changes.append("kindle_plus_eligible")

    categories = set(normalize_categories(book.get("amazon_categories", [])))
    if category and category != "Tienda Kindle" and category not in categories:
        categories.add(category)
        changes.append("amazon_categories")
    book["amazon_categories"] = sorted(categories)

    book["last_seen_at"] = incoming.get("collected_at") or now_iso()
    book["last_seen_source"] = incoming.get("source_name")
    book["last_seen_page"] = incoming.get("page_number")
    return book, changes


def save_catalog(books):
    rows = sorted(books.values(), key=lambda row: row["asin"])
    save_json(OUTPUT_JSON, rows)

    fields = list(dict.fromkeys(
        key for row in rows for key in row.keys()
    ))
    temp = OUTPUT_CSV.with_name(OUTPUT_CSV.name + ".tmp")
    with temp.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            output = dict(row)
            for key, value in output.items():
                if isinstance(value, (list, dict)):
                    output[key] = json.dumps(value, ensure_ascii=False)
            writer.writerow(output)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, OUTPUT_CSV)


def coverage(books):
    rows = list(books.values())
    return {
        "total": len(rows),
        "with_valid_author": sum(valid_author(row.get("author")) for row in rows),
        "with_verified_author": sum(has_verified_author(row) for row in rows),
        "with_image": sum(bool(clean_text(row.get("image_url"))) for row in rows),
        "kindle_plus_verified": sum(
            row.get("kindle_plus_eligible") is True
            or str(row.get("kindle_plus_eligible")).lower() == "true"
            for row in rows
        ),
        "with_categories": sum(bool(normalize_categories(row.get("amazon_categories"))) for row in rows),
        "with_multiple_categories": sum(
            len(normalize_categories(row.get("amazon_categories"))) > 1
            for row in rows
        ),
    }


def new_source_progress():
    return {
        "next_page": 1,
        "next_url": None,
        "pages_scanned": 0,
        "seen_signatures": [],
        "stop_reason": None,
    }


def new_state(initial_asins):
    return {
        "version": STATE_VERSION,
        "source_progress": {},
        "legacy_sources_to_review": [],
        "initial_asins": sorted(initial_asins),
        "new_asins": [],
        "pages_completed": 0,
        "cards_seen": 0,
        "cards_verified": 0,
        "metadata_updates": 0,
        "started_at": now_iso(),
        "updated_at": now_iso(),
    }


def load_or_create_state(initial_asins, restart, source_ids):
    if restart and STATE_FILE.exists():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archived = STATE_FILE.with_name(f"{STATE_FILE.stem}_{stamp}.json")
        shutil.copy2(STATE_FILE, archived)
        print(f"🗃️ Progreso anterior archivado: {archived.name}")

    if STATE_FILE.exists() and not restart:
        state = load_json(STATE_FILE)
        if state.get("version") == 2:
            legacy_ids = [LEGACY_GENERAL_ID, *source_ids]
            index = state.pop("source_index")
            number = state.pop("next_page")
            signature = state.pop("last_signature", [])
            # La versión 2 marcaba como terminadas las fuentes truncadas.
            state["legacy_sources_to_review"] = state.pop("completed_sources", [])
            state["source_progress"] = {}
            state["version"] = STATE_VERSION
            if (
                index == len(legacy_ids)
                and number == 1
                and state["legacy_sources_to_review"] == legacy_ids
                and state["pages_completed"] == LEGACY_PAGE_LIMIT * len(legacy_ids)
            ):
                # Corrida completa con el límite anterior: recuperar el
                # enlace Siguiente de la página 25 en cada fuente.
                for source_id in source_ids:
                    progress = new_source_progress()
                    progress.update(
                        next_page=LEGACY_PAGE_LIMIT + 1,
                        pages_scanned=LEGACY_PAGE_LIMIT,
                        resume_link_from_page=LEGACY_PAGE_LIMIT,
                    )
                    state["source_progress"][source_id] = progress
            elif 0 < index < len(legacy_ids) and number > 1:
                progress = new_source_progress()
                progress["next_page"] = number
                progress["pages_scanned"] = number - 1
                if signature:
                    progress["seen_signatures"] = [signature_key(signature)]
                state["source_progress"][legacy_ids[index]] = progress
            print("🔄 Avance anterior recuperado")
        if state.get("version") != STATE_VERSION:
            raise ValueError(
                "El checkpoint pertenece a otra versión. Usa --restart para "
                "archivarlo e iniciar un recorrido nuevo."
            )
        state["legacy_sources_to_review"] = [
            source_id for source_id in state["legacy_sources_to_review"]
            if source_id in source_ids
        ]
        return state

    return new_state(initial_asins)


def save_report(state, books, status, source_file):
    initial = set(state.get("initial_asins", []))
    actual_new = sorted(set(books) - initial)
    state["new_asins"] = actual_new
    state["updated_at"] = now_iso()
    report = {
        "status": status,
        "catalog_url": CATALOG_URL,
        "source_catalog_file": str(source_file),
        "started_at": state.get("started_at"),
        "updated_at": state["updated_at"],
        "pages_completed": state.get("pages_completed", 0),
        "cards_seen": state.get("cards_seen", 0),
        "cards_verified": state.get("cards_verified", 0),
        "metadata_updates": state.get("metadata_updates", 0),
        "new_asin_count": len(actual_new),
        "new_asins": actual_new,
        "coverage": coverage(books),
        "sources": {
            source_id: {
                "pages_scanned": progress["pages_scanned"],
                "next_page": progress["next_page"],
                "stop_reason": progress["stop_reason"],
            }
            for source_id, progress in state["source_progress"].items()
            if source_id != LEGACY_GENERAL_ID
        },
        "legacy_sources_to_review": state["legacy_sources_to_review"],
    }
    save_json(REPORT_FILE, report)
    save_json(STATE_FILE, state)
    return report


def validate_one_page(page, source):
    target = source["url"]
    response = page.goto(target, wait_until="domcontentloaded", timeout=45000)
    response_guard(response, page)
    wait_for_cards(page)
    books = extract_books(page, source["name"], source["name"], 1)
    verified = [book for book in books if book["kindle_plus_eligible"]]
    valid_authors = [book for book in books if valid_author(book.get("author"))]

    print("\n🔬 VALIDACIÓN DE UNA PÁGINA (sin escribir catálogo)")
    print(f"Categoría: {source['name']}")
    print(f"Listado: {target}")
    print(f"Tarjetas: {len(books)}")
    print(f"Kindle+ verificado en tarjeta: {len(verified)}")
    print(f"Autor válido extraído: {len(valid_authors)}")
    for book in books[:8]:
        author = book.get("author") or "⚠ sin autor"
        eligible = "✓ Kindle+" if book["kindle_plus_eligible"] else "? sin evidencia"
        print(f"  {eligible} | {book['asin']} | {book['title']} | {author}")

    if not books:
        raise RuntimeError("La página no produjo tarjetas")
    if not verified:
        raise RuntimeError("Ninguna tarjeta mostró evidencia de Kindle+")
    if not valid_authors:
        print(
            "⚠️ Las tarjetas actuales no publican autor. Se conservará vacío "
            "en vez de inventarlo; usa kindle_enrich_amazon_authors.py para "
            "leerlo desde la ficha del libro."
        )
    print("✅ Selectores mínimos validados. El catálogo no fue modificado.")


def crawl(args):
    books, source_file = load_books()
    sources = load_categories()
    source_ids = [source["id"] for source in sources]
    initial_count = len(books)

    print(f"📚 Catálogo cargado: {initial_count:,} ASIN ({source_file.name})")
    print(f"📂 Categorías inmediatas de Kindle+: {len(sources)}")

    if args.category:
        wanted = {name.casefold() for name in args.category}
        sources = [source for source in sources if source["name"].casefold() in wanted]
        unknown = wanted - {source["name"].casefold() for source in sources}
        if unknown:
            raise ValueError(f"Categorías desconocidas: {', '.join(sorted(unknown))}")

    if args.max_categories is not None:
        sources = sources[:args.max_categories]

    state = None
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE),
            headless=args.headless,
            locale="es-MX",
            viewport={"width": 1440, "height": 1000},
        )
        page = context.pages[0] if context.pages else context.new_page()

        try:
            if not args.headless and not args.no_prompt:
                page.goto(
                    "https://www.amazon.com.mx/",
                    wait_until="domcontentloaded",
                    timeout=45000,
                )
                input(
                    "\n🔐 Verifica tu sesión de Amazon y presiona ENTER "
                    "para continuar..."
                )

            if args.validate_only:
                validate_one_page(page, sources[0])
                return

            state = load_or_create_state(set(books), args.restart, source_ids)
            progress_by_source = state["source_progress"]
            max_pages = args.max_pages_per_category
            print(f"🧭 Fuentes en esta corrida: {len(sources)}")
            if max_pages is None:
                print("📄 Se seguirá la paginación que ofrece Amazon")
            else:
                print(f"📄 Hasta {max_pages} páginas por fuente en esta sesión")

            requested_page = False
            for index, source in enumerate(sources, start=1):
                source_id = source["id"]
                progress = progress_by_source.setdefault(source_id, new_source_progress())
                if progress["stop_reason"]:
                    continue
                seen = set(progress["seen_signatures"])
                pages_this_session = 0
                print(f"\n📂 [{index}/{len(sources)}] {source['name']}")

                while max_pages is None or pages_this_session < max_pages:
                    boundary = progress.get("resume_link_from_page")
                    number = boundary or progress["next_page"]
                    target = progress["next_url"]
                    if not target:
                        target = source["url"] if number == 1 else page_url(source["url"], number)
                    if requested_page:
                        time.sleep(args.delay + random.uniform(0, 2))
                    if boundary:
                        print(f"  🔗 Recuperando el enlace Siguiente desde la página {number}")
                    else:
                        print(f"  📖 Página {number}")
                    response = page.goto(
                        target, wait_until="domcontentloaded", timeout=45000
                    )
                    requested_page = True
                    response_guard(response, page)
                    try:
                        wait_for_cards(page)
                    except PWTimeout as exc:
                        response_guard(response, page)
                        raise RuntimeError(
                            f"No aparecieron tarjetas en {source['name']}, página {number}. "
                            "El avance queda en esta página."
                        ) from exc

                    cards = extract_books(
                        page, source["name"], source["name"], number
                    )
                    if not cards:
                        raise RuntimeError(f"No se pudieron leer las tarjetas de la página {number}")
                    signature = signature_key(book["asin"] for book in cards)
                    if signature in seen:
                        print("  🏁 Amazon repitió una página de esta fuente")
                        progress["stop_reason"] = "repeated_page"
                        break
                    following = next_page_url(page)

                    if boundary:
                        if following:
                            numbers = parse_qs(urlparse(following).query).get("page")
                            if numbers and numbers != [str(progress["next_page"])]:
                                raise RuntimeError(
                                    f"Amazon no mostró el enlace esperado a la página "
                                    f"{progress['next_page']} de {source['name']}."
                                )
                        progress.pop("resume_link_from_page")
                        seen.add(signature)
                        progress["seen_signatures"].append(signature)
                        progress["next_url"] = following
                        if not following:
                            progress["next_page"] = None
                            progress["stop_reason"] = "end_of_pagination"
                            print(f"  🏁 La página {number} es la última disponible")
                            break
                        save_report(state, books, "running", source_file)
                        continue

                    verified = [
                        book for book in cards if book["kindle_plus_eligible"]
                    ]
                    new_count = 0
                    updated_count = 0
                    skipped_unverified = 0

                    for incoming in cards:
                        asin = incoming["asin"]
                        existing = books.get(asin)
                        if not incoming["kindle_plus_eligible"] and not existing:
                            skipped_unverified += 1
                            continue
                        merged, changes = merge_book(
                            existing, incoming, source["name"]
                        )
                        books[asin] = merged
                        if existing is None:
                            new_count += 1
                        elif changes:
                            updated_count += 1
                            state["metadata_updates"] += len(changes)

                    seen.add(signature)
                    progress["seen_signatures"].append(signature)
                    progress["pages_scanned"] += 1
                    progress["next_page"] = number + 1 if following else None
                    progress["next_url"] = following
                    if not following:
                        progress["stop_reason"] = "end_of_pagination"
                    pages_this_session += 1
                    state["pages_completed"] += 1
                    state["cards_seen"] += len(cards)
                    state["cards_verified"] += len(verified)
                    state["updated_at"] = now_iso()

                    save_catalog(books)
                    save_report(state, books, "running", source_file)

                    print(
                        f"  ✅ {len(cards)} tarjetas | {len(verified)} Kindle+ | "
                        f"{new_count} ASIN nuevos | {updated_count} actualizados"
                    )
                    if skipped_unverified:
                        print(
                            f"  🛡️ {skipped_unverified} ASIN nuevos omitidos "
                            "por no mostrar evidencia Kindle+"
                        )

                    if not following:
                        print("  🏁 Última página disponible")
                        break

                if progress["stop_reason"]:
                    if source_id in state["legacy_sources_to_review"]:
                        state["legacy_sources_to_review"].remove(source_id)
                else:
                    print(f"  ⏸️ Siguiente al reanudar: página {progress['next_page']}")
                save_report(state, books, "running", source_file)

            exhausted = all(
                progress_by_source.get(source_id, {}).get("stop_reason")
                for source_id in source_ids
            )
            status = "completed" if exhausted else "limited"
            if exhausted and any(
                progress_by_source[source_id]["stop_reason"] == "repeated_page"
                for source_id in source_ids
            ):
                status = "pagination_stalled"
            report = save_report(state, books, status, source_file)
            print("\n================================")
            print("📚 FIN DE LA SESIÓN DEL CRAWLER")
            print("================================")
            print(f"ASIN antes: {initial_count:,}")
            print(f"ASIN ahora: {len(books):,}")
            print(f"ASIN nuevos: {report['new_asin_count']:,}")
            print(f"Con autor verificado: {report['coverage']['with_verified_author']:,}")
            print(f"Con imagen: {report['coverage']['with_image']:,}")
            print(f"Con categorías: {report['coverage']['with_categories']:,}")
            print(f"Reporte: {REPORT_FILE}")

        except KeyboardInterrupt:
            print("\n⏹️ Interrumpido manualmente; el último checkpoint permanece guardado.")
            if state is not None:
                save_catalog(books)
                save_report(state, books, "interrupted", source_file)
        except Exception as exc:
            if state is not None:
                save_catalog(books)
                save_report(state, books, "error", source_file)
            if args.keep_open_on_error:
                print(f"\n⏸️ Recorrido detenido: {exc}", flush=True)
                try:
                    input("Revisa el navegador y presiona Enter aquí para cerrarlo... ")
                except (EOFError, KeyboardInterrupt):
                    pass
            raise
        finally:
            context.close()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Crawler incremental Kindle+ México por ASIN"
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="prueba sólo una página y no modifica el catálogo",
    )
    parser.add_argument(
        "--max-pages-per-category", "--pages",
        type=int,
        help="hasta N páginas por fuente en esta sesión; conserva la siguiente página",
    )
    parser.add_argument(
        "--max-categories",
        type=int,
        default=None,
        help="limita el número de fuentes; útil para una corrida pequeña",
    )
    parser.add_argument(
        "--category",
        action="append",
        help="procesa sólo la fuente indicada; se puede repetir",
    )
    parser.add_argument(
        "--delay", type=float, default=DEFAULT_DELAY,
        help="pausa base en segundos, más 0 a 2 al azar (por defecto: %(default)g)",
    )
    parser.add_argument("--headless", action="store_true")
    parser.add_argument(
        "--keep-open-on-error",
        action="store_true",
        help="si hay un error, deja la ventana abierta hasta que presiones Enter",
    )
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help="no espera confirmación manual de sesión",
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help="archiva el checkpoint e inicia desde la primera fuente",
    )
    args = parser.parse_args()
    if args.max_pages_per_category is not None and args.max_pages_per_category < 1:
        parser.error("--max-pages-per-category debe ser al menos 1")
    if args.max_categories is not None and args.max_categories < 1:
        parser.error("--max-categories debe ser al menos 1")
    if args.delay < 0:
        parser.error("--delay no puede ser negativo")
    if args.keep_open_on_error and args.headless:
        parser.error("--keep-open-on-error necesita una ventana visible")
    return args


def main():
    crawl(parse_args())


if __name__ == "__main__":
    main()
