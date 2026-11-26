#!/usr/bin/env python3
"""Enriquece autores desde las fichas de Amazon, con checkpoint reanudable.

Las tarjetas actuales de búsqueda de Amazon México no siempre publican el
autor. Este segundo paso consulta los ASIN sin un autor verificado en Amazon.
Se detiene ante CAPTCHA o bloqueo.
"""

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

import kindle_crawler_category_match as catalog


STATE_FILE = catalog.DATA / "kindle_plus_mexico_2.0_author_progress.json"
REPORT_FILE = catalog.DATA / "kindle_plus_mexico_2.0_author_report.json"
DEFAULT_DELAY = 5.0


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup_source(source_file):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = catalog.ROOT / "backups" / f"before_author_enrichment_{stamp}"
    target.mkdir(parents=True, exist_ok=False)
    candidates = [source_file]
    csv_sibling = source_file.with_suffix(".csv")
    if csv_sibling.exists():
        candidates.append(csv_sibling)

    manifest = []
    for source in candidates:
        copied = target / source.name
        shutil.copy2(source, copied)
        if copied.stat().st_size != source.stat().st_size:
            raise RuntimeError(f"El respaldo de {source.name} quedó incompleto")
        if sha256(copied) != sha256(source):
            raise RuntimeError(f"Falló la verificación SHA-256 de {source.name}")
        manifest.append({
            "file": source.name,
            "bytes": source.stat().st_size,
            "sha256": sha256(source),
        })

    catalog.save_json(target / "manifest.json", manifest)
    return target


def product_url(asin):
    return f"https://www.amazon.com.mx/dp/{asin}"


def extract_product_metadata(page):
    return page.evaluate(
        r"""() => {
            const clean = value => value?.replace(/\s+/g, ' ').trim() || null;
            const authors = new Set();
            const unlabeled = new Set();
            const containers = document.querySelectorAll(
                '#bylineInfo .author, #bylineInfo_feature_div .author'
            );

            for (const container of containers) {
                const link = container.querySelector('a.contributorNameID, a[href]');
                const name = clean(link?.innerText);
                if (!name) continue;
                const role = (clean(container.innerText) || '').replace(name, '');
                if (/\(\s*(?:autor(?:a|es)?|coautor(?:a|es)?|authors?|co-authors?)\b/i.test(role)) {
                    authors.add(name);
                } else if (!/\([^)]*\)/.test(role)) {
                    unlabeled.add(name);
                }
            }

            const title = clean(
                document.querySelector('#productTitle, #ebooksProductTitle')?.innerText
            );
            return {
                title,
                author: [...authors].join(', ') || null,
                author_candidate: [...unlabeled].join(', ') || null,
            };
        }"""
    )


def fetch_author(page, asin):
    response = page.goto(
        product_url(asin), wait_until="domcontentloaded", timeout=45000
    )
    catalog.response_guard(response, page)
    product = urlparse(page.url)
    if product.hostname == "www.amazon.com.mx" and "/ap/signin" in product.path:
        raise RuntimeError("Amazon pidió iniciar sesión. Verifica el perfil y reanuda el lote.")
    product_asin = re.search(
        r"/(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})(?:/|$)", product.path, re.IGNORECASE
    )
    if (
        product.hostname != "www.amazon.com.mx"
        or product_asin is None
        or product_asin.group(1).upper() != asin.upper()
    ):
        return {"title": None, "author": None}
    try:
        page.locator(
            "#productTitle, #ebooksProductTitle, #bylineInfo"
        ).first.wait_for(timeout=12000)
    except PWTimeout:
        return {"title": None, "author": None}
    return extract_product_metadata(page)


def new_state(pending, backup_dir):
    return {
        "version": 1,
        "pending_asins": pending,
        "cursor": 0,
        "checked": 0,
        "authors_found": 0,
        "not_found": 0,
        "started_at": catalog.now_iso(),
        "updated_at": catalog.now_iso(),
        "backup_dir": str(backup_dir),
    }


def load_state(books, source_file, restart):
    if STATE_FILE.exists() and not restart:
        state = catalog.load_json(STATE_FILE)
        if state.get("version") != 1:
            raise ValueError("Checkpoint de autores incompatible; usa --restart")
        known = set(state.get("pending_asins", []))
        additions = sorted(
            asin for asin, book in books.items()
            if not catalog.has_verified_author(book) and asin not in known
        )
        if additions:
            state["pending_asins"].extend(additions)
            catalog.save_json(STATE_FILE, state)
            print(f"➕ {len(additions):,} ASIN nuevos añadidos a la cola de autores")
        return state

    if restart and STATE_FILE.exists():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archived = STATE_FILE.with_name(f"{STATE_FILE.stem}_{stamp}.json")
        shutil.copy2(STATE_FILE, archived)
        print(f"🗃️ Progreso anterior archivado: {archived.name}")

    backup_dir = backup_source(source_file)
    pending = sorted(
        asin for asin, book in books.items()
        if not catalog.has_verified_author(book)
    )
    state = new_state(pending, backup_dir)
    catalog.save_json(STATE_FILE, state)
    return state


def save_progress(state, books, status):
    state["updated_at"] = catalog.now_iso()
    report = {
        "status": status,
        "started_at": state.get("started_at"),
        "updated_at": state["updated_at"],
        "pending_total": len(state.get("pending_asins", [])),
        "cursor": state.get("cursor", 0),
        "checked": state.get("checked", 0),
        "authors_found": state.get("authors_found", 0),
        "not_found": state.get("not_found", 0),
        "remaining": max(
            0,
            len(state.get("pending_asins", [])) - state.get("cursor", 0),
        ),
        "coverage": catalog.coverage(books),
        "backup_dir": state.get("backup_dir"),
    }
    catalog.save_json(STATE_FILE, state)
    catalog.save_json(REPORT_FILE, report)
    return report


def run(args):
    books, source_file = catalog.load_books()
    missing = [
        asin for asin, book in books.items()
        if not catalog.has_verified_author(book)
    ]
    print(f"📚 Catálogo: {len(books):,} ASIN ({source_file.name})")
    print(f"✍️ Sin autor verificado: {len(missing):,}")

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(catalog.PROFILE),
            headless=args.headless,
            locale="es-MX",
            viewport={"width": 1440, "height": 1000},
        )
        page = context.pages[0] if context.pages else context.new_page()
        state = None

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
                asin = args.asin or (missing[0] if missing else next(iter(books)))
                metadata = fetch_author(page, asin)
                print("\n🔬 VALIDACIÓN DE UNA FICHA (sin escribir catálogo)")
                print(f"ASIN: {asin}")
                print(f"Título: {metadata.get('title') or '⚠ no encontrado'}")
                print(f"Autor: {metadata.get('author') or '⚠ no encontrado'}")
                if not catalog.valid_author(metadata.get("author")):
                    raise RuntimeError(
                        "La ficha no produjo un autor válido; revisa el selector"
                    )
                print("✅ Selector de autor validado. El catálogo no fue modificado.")
                return

            state = load_state(books, source_file, args.restart)
            pending = state["pending_asins"]
            start = state["cursor"]
            end = len(pending)
            if args.limit:
                end = min(end, start + args.limit)

            print(f"🔄 Reanudando en {start:,}/{len(pending):,}")
            print(f"💾 Checkpoint cada {args.checkpoint_every} fichas")

            for index in range(start, end):
                asin = pending[index]
                metadata = fetch_author(page, asin)
                book = books[asin]
                author = metadata.get("author")

                if catalog.valid_author(author):
                    book["author"] = catalog.clean_text(author)
                    book["author_source"] = "amazon_product_page"
                    book["author_checked_at"] = catalog.now_iso()
                    state["authors_found"] += 1
                    marker = "✅"
                else:
                    book["author_checked_at"] = catalog.now_iso()
                    state["not_found"] += 1
                    marker = "⚠️"

                if metadata.get("title") and not catalog.clean_text(book.get("title")):
                    book["title"] = catalog.clean_text(metadata["title"])

                state["cursor"] = index + 1
                state["checked"] += 1
                print(
                    f"{marker} [{index + 1}/{len(pending)}] {asin} | "
                    f"{author or 'autor no encontrado'}"
                )

                if (
                    state["checked"] % args.checkpoint_every == 0
                    or state["cursor"] == end
                ):
                    catalog.save_catalog(books)
                    save_progress(state, books, "running")

                if index + 1 < end:
                    pause = args.delay + random.uniform(0, 2)
                    time.sleep(pause)

            status = "completed" if end == len(pending) else "limited"
            catalog.save_catalog(books)
            report = save_progress(state, books, status)
            print("\n================================")
            print("✍️ ENRIQUECIMIENTO DE AUTORES")
            print("================================")
            print(f"Revisados: {report['checked']:,}")
            print(f"Autores encontrados: {report['authors_found']:,}")
            print(f"Pendientes: {report['remaining']:,}")
            print(f"Reporte: {REPORT_FILE}")

        except KeyboardInterrupt:
            print("\n⏹️ Interrumpido; se guardó el último avance.")
            if state is not None:
                catalog.save_catalog(books)
                save_progress(state, books, "interrupted")
            raise SystemExit(130)
        except Exception:
            if state is not None:
                catalog.save_catalog(books)
                save_progress(state, books, "error")
            raise
        finally:
            context.close()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Enriquece autores desde fichas Amazon por ASIN"
    )
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--asin", help="ASIN para --validate-only")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="máximo de fichas en esta sesión; 0 procesa todas",
    )
    parser.add_argument(
        "--delay", type=float, default=DEFAULT_DELAY,
        help="pausa base en segundos entre fichas, más 0–2 s aleatorios (predeterminado: %(default)s)",
    )
    parser.add_argument("--checkpoint-every", type=int, default=10)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--no-prompt", action="store_true")
    parser.add_argument("--restart", action="store_true")
    args = parser.parse_args()
    if args.limit < 0:
        parser.error("--limit no puede ser negativo")
    if args.delay < 0:
        parser.error("--delay no puede ser negativo")
    if args.checkpoint_every < 1:
        parser.error("--checkpoint-every debe ser al menos 1")
    return args


if __name__ == "__main__":
    run(parse_args())
