
import csv
import json
import os
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import (
    urljoin, urlparse, parse_qs, urlencode, urlunparse
)

from playwright.sync_api import sync_playwright


# ============================================================
# CONFIGURACION
# ============================================================

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
PROFILE = ROOT / "amazon_profile_categories"

JSON_FILE = DATA / "amazon_categories.json"
CSV_FILE = DATA / "amazon_categories.csv"
STATE_FILE = DATA / "category_list_progress.json"

BASE_URL = (
    "https://www.amazon.com.mx/s?"
    "i=kindle-unlimited&"
    "srs=9257648011&"
    "rh=n%3A9257648011&"
    "s=popularity-rank&fs=true"
)

ROOT_NAME = "eBooks Kindle"

# No es obligatorio alcanzar este limite.
MAX_CATEGORIES = 1500
DELAY_SECONDS = 5
HEADLESS = False
SAVE_EVERY = 5

DATA.mkdir(parents=True, exist_ok=True)


# ============================================================
# UTILIDADES
# ============================================================

def now():
    return datetime.now(timezone.utc).isoformat()


def clean_text(value):
    return re.sub(r"\s+", " ", value or "").strip()


def normalize(value):
    value = unicodedata.normalize(
        "NFKD", clean_text(value)
    )
    value = "".join(
        c for c in value
        if not unicodedata.combining(c)
    )
    return value.casefold()


def valid_amazon_url(url):
    parsed = urlparse(url)

    return (
        parsed.scheme == "https"
        and parsed.hostname in (
            "www.amazon.com.mx",
            "amazon.com.mx"
        )
        and parsed.path.startswith(
            ("/s", "/b", "/kindle")
        )
    )


def canonical_url(url):
    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    # Conservamos filtros de navegacion.
    # Eliminamos tracking, pagina y ordenamiento.
    keep = [
        "i", "rh", "srs", "bbn",
        "node", "fs", "k"
    ]

    query = {
        key: params[key]
        for key in keep
        if key in params
    }

    return urlunparse((
        "https",
        "www.amazon.com.mx",
        parsed.path,
        "",
        urlencode(query, doseq=True),
        ""
    ))


def save_json(path, data):
    temp = path.with_suffix(".json.tmp")

    with temp.open("w", encoding="utf-8") as f:
        json.dump(
            data, f,
            ensure_ascii=False,
            indent=2
        )
        f.flush()
        os.fsync(f.fileno())

    os.replace(temp, path)


# ============================================================
# GUARDAR RESULTADOS
# ============================================================

def save_catalog(state):
    categories = state["categories"]

    save_json(JSON_FILE, categories)

    fields = [
        "id",
        "name",
        "parent_id",
        "parent_name",
        "depth",
        "path",
        "url",
        "visited",
        "discovered_at",
        "visited_at",
        "kindle_filter_seen"
    ]

    temp = CSV_FILE.with_suffix(".csv.tmp")

    with temp.open(
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as f:
        writer = csv.DictWriter(
            f, fieldnames=fields
        )
        writer.writeheader()

        for item in categories:
            row = dict(item)
            row["path"] = " > ".join(item["path"])
            writer.writerow({
                key: row.get(key)
                for key in fields
            })

        f.flush()
        os.fsync(f.fileno())

    os.replace(temp, CSV_FILE)

    save_json(STATE_FILE, state)

    print(
        f"💾 {len(categories)} categorias guardadas"
    )


def load_state():
    if STATE_FILE.exists():
        print("🔄 Recuperando progreso anterior")

        return json.loads(
            STATE_FILE.read_text(encoding="utf-8")
        )

    return {
        "categories": [],
        "queue": [],
        "visited_urls": [],
        "next_id": 1,
        "processed": 0,
        "created_at": now()
    }


# ============================================================
# DETECCION DE BLOQUEOS
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
# EXTRAER CATEGORIAS DEL SIDEBAR
# ============================================================


def extract_sidebar(page, current_name):
    """
    Extrae las categorías visibles del panel lateral.

    No depende de encontrar el nombre de la categoría
    actual como un elemento HTML independiente.

    IMPORTANTE:
    Los enlaces extraídos son candidatos a hijos.
    Esta función no garantiza todavía la jerarquía.
    """

    return page.evaluate(
        """() => {
            const sidebar =
                document.querySelector('#departments');

            if (!sidebar) {
                return {
                    found: false,
                    children: [],
                    error: 'No existe #departments'
                };
            }

            const links = [
                ...sidebar.querySelectorAll('a[href]')
            ];

            const seen = new Set();

            const children = links
                .map(a => ({
                    name: (a.innerText || '')
                        .replace(/\\s+/g, ' ')
                        .trim(),
                    url: a.href
                }))
                .filter(item => {
                    if (!item.name || !item.url) {
                        return false;
                    }

                    if (seen.has(item.url)) {
                        return false;
                    }

                    seen.add(item.url);
                    return true;
                });

            return {
                found: true,
                children
            };
        }"""
    )



# ============================================================
# COMPROBAR CONTEXTO KINDLE+
# ============================================================

def kindle_filter_present(page):
    """
    Comprobacion indicativa, no verificacion
    de elegibilidad individual.
    """
    return page.evaluate(
        """() => {
            const sidebar =
                document.querySelector('#s-refinements')
                || document.body;

            const text =
                (sidebar.innerText || '').toLowerCase();

            return text.includes(
                'elegible para kindle+'
            ) || text.includes(
                'kindle unlimited'
            );
        }"""
    )


# ============================================================
# AGREGAR CATEGORIA
# ============================================================

def add_category(
    state,
    name,
    url,
    parent=None
):
    name = clean_text(name)
    url = canonical_url(url)

    if not name or not valid_amazon_url(url):
        return False

    existing_urls = {
        item["url"]
        for item in state["categories"]
    }

    if url in existing_urls:
        return False

    # Enlaces de refinamiento deben conservar
    # un parametro de categoria identificable.
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)

    if (
        parent is not None
        and not any(
            key in qs
            for key in ("rh", "node", "bbn")
        )
    ):
        return False

    category_id = state["next_id"]
    state["next_id"] += 1

    if parent:
        path = parent["path"] + [name]
        parent_id = parent["id"]
        parent_name = parent["name"]
    else:
        path = [name]
        parent_id = None
        parent_name = None

    item = {
        "id": category_id,
        "name": name,
        "parent_id": parent_id,
        "parent_name": parent_name,
        "depth": len(path) - 1,
        "path": path,
        "url": url,
        "visited": False,
        "discovered_at": now(),
        "visited_at": None,
        "kindle_filter_seen": False
    }

    state["categories"].append(item)
    state["queue"].append(category_id)

    print(
        "  ➕ " + " > ".join(path)
    )

    return True


# ============================================================
# LOCALIZAR CATEGORIA RAIZ
# ============================================================

def initialize(page, state):
    print("🔎 Abriendo catalogo Kindle+...")

    response = page.goto(
        BASE_URL,
        wait_until="domcontentloaded",
        timeout=45000
    )

    if response and response.status in (
        403, 429, 503
    ):
        raise RuntimeError(
            f"HTTP {response.status}"
        )

    if is_blocked(page):
        raise RuntimeError(
            "Amazon solicita verificacion"
        )

    page.wait_for_timeout(1500)

    # En la pagina raiz, eBooks Kindle aparece
    # como categoria seleccionada.
    # Si no podemos resolver su enlace, utilizamos
    # la propia URL del catalogo como punto inicial.
    add_category(
        state,
        ROOT_NAME,
        BASE_URL
    )

    save_catalog(state)


# ============================================================
# CRAWLER BFS
# ============================================================

def crawl():
    state = load_state()

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE),
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
                "\n🔐 Verifica tu sesion de Amazon.\n"
                "Presiona ENTER para comenzar..."
            )

            if not state["categories"]:
                initialize(page, state)

            visited_this_run = 0

            while state["queue"]:
                if (
                    state["processed"]
                    >= MAX_CATEGORIES
                ):
                    print(
                        "🏁 Limite de categorias alcanzado"
                    )
                    break

                category_id = state["queue"][0]

                category = next(
                    (
                        item
                        for item in state["categories"]
                        if item["id"] == category_id
                    ),
                    None
                )

                if category is None:
                    state["queue"].pop(0)
                    continue

                if category["visited"]:
                    state["queue"].pop(0)
                    continue

                print(
                    f"\n📂 {category['name']}"
                )
                print(
                    "   " +
                    " > ".join(category["path"])
                )

                response = page.goto(
                    category["url"],
                    wait_until="domcontentloaded",
                    timeout=45000
                )

                if response and response.status in (
                    403, 429, 503
                ):
                    print(
                        f"⛔ HTTP {response.status}"
                    )
                    break

                if is_blocked(page):
                    print("⛔ CAPTCHA detectado")
                    break

                try:
                    page.locator(
                        "#departments"
                    ).wait_for(timeout=15000)
                except Exception:
                    print(
                        "⚠️ No se encontro el sidebar"
                    )
                    break

                page.wait_for_timeout(1000)

                result = extract_sidebar(
                    page,
                    category["name"]
                )

                if not result["found"]:
                    print(
                        "⚠️ No pude identificar el nodo "
                        "actual. Deteniendo para evitar "
                        "clasificaciones incorrectas."
                    )
                    break

                category["kindle_filter_seen"] = (
                    kindle_filter_present(page)
                )

                added = 0

                for child in result["children"]:
                    if add_category(
                        state,
                        child["name"],
                        urljoin(
                            page.url,
                            child["url"]
                        ),
                        parent=category
                    ):
                        added += 1

                category["visited"] = True
                category["visited_at"] = now()

                state["visited_urls"].append(
                    category["url"]
                )

                state["queue"].pop(0)
                state["processed"] += 1

                visited_this_run += 1

                print(
                    f"✅ {added} subcategorias nuevas"
                )
                print(
                    f"📊 Total: "
                    f"{len(state['categories'])}"
                )
                print(
                    f"📋 Pendientes: "
                    f"{len(state['queue'])}"
                )

                if (
                    visited_this_run % SAVE_EVERY == 0
                    or not state["queue"]
                ):
                    save_catalog(state)

                time.sleep(DELAY_SECONDS)

        except KeyboardInterrupt:
            print(
                "\n⏹️ Interrumpido manualmente"
            )

        except Exception as exc:
            print(
                f"\n⚠️ Error: {exc}"
            )

        finally:
            save_catalog(state)
            context.close()

    print("\n================================")
    print("📚 ARBOL DE CATEGORIAS")
    print("================================")
    print(
        f"Descubiertas: "
        f"{len(state['categories'])}"
    )
    print(
        f"Procesadas: {state['processed']}"
    )
    print(
        f"Pendientes: {len(state['queue'])}"
    )
    print(f"JSON: {JSON_FILE}")
    print(f"CSV: {CSV_FILE}")
    print("================================")


if __name__ == "__main__":
    crawl()
