#!/usr/bin/env python3
"""Normalize Kindle+ 2.0 JSON/CSV into website data/books.json.

Usage (from /Volumes/External/kindle-crawler):
 python build_kindle_web_catalog.py /path/to/site/data/books.json
Or without argument, writes data/books.web.json (does not overwrite crawler JSON).
"""
import csv
import json
import re
import sys
import os
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
SRC_JSON_CANDIDATES = (
    ROOT / 'data' / 'kindle_plus_mexico_2.0.json',
    ROOT / 'data' / 'kindle_plus_mexico_categorized.json',
)
SRC_CSV_CANDIDATES = (
    ROOT / 'data' / 'kindle_plus_mexico_2.0.csv',
    ROOT / 'data' / 'kindle_plus_mexico_categorized.csv',
)
DEST = Path(sys.argv[1]).expanduser() if len(sys.argv)>1 else ROOT / 'data' / 'books.web.json'


def load():
    src_json = next((path for path in SRC_JSON_CANDIDATES if path.exists()), None)
    if src_json:
        data = json.loads(src_json.read_text('utf-8'))
        if not isinstance(data,list):
            raise ValueError('El JSON del crawler debe ser una lista.')
        return data
    src_csv = next((path for path in SRC_CSV_CANDIDATES if path.exists()), None)
    if not src_csv:
        raise FileNotFoundError('No existe un catálogo Kindle+ 2.0 ni legado.')
    with src_csv.open(newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def numeric(val, integer=False):
    if val is None or isinstance(val, bool): return None
    if isinstance(val, (int,float)): return int(val) if integer else float(val)
    s=str(val).strip().replace('\u00a0','')
    if not s: return None
    # Reviews commonly use 27,500 or 27.500. Ratings 4.8 or 4,8.
    match=re.search(r'\d[\d.,]*',s)
    if not match: return None
    n=match.group(0)
    if integer:
        n=re.sub(r'[^\d]','',n)
        return int(n) if n else None
    n=n.replace(',','.')
    try:
        v=float(n)
        return round(v,2) if 0<=v<=5 else None
    except ValueError: return None


def eligible(v):
    return v is True or (isinstance(v,str) and v.strip().lower() in ('true','1','yes','sí','si'))


def categories(v):
    if isinstance(v,list): return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v,str) and v.strip():
        try:
            result=json.loads(v)
            if isinstance(result,list): return categories(result)
        except (TypeError,ValueError): pass
    return []


def valid_image(v):
    if not isinstance(v,str): return None
    url=v.strip()
    parsed=urlparse(url)
    if parsed.scheme!='https' or not parsed.hostname: return None
    # Keep metadata; publishing/hotlinking requires separate authorization.
    return url


def valid_author(v):
    if not isinstance(v,str): return None
    v=' '.join(v.split())
    rejected=('kindle+','kindle unlimited','gratis con','membresía','tapa blanda',
              'estrellas','paperback','calificación','envío gratis','comprar')
    if len(v)<3 or len(v)>160 or any(x in v.casefold() for x in rejected): return None
    return v


books={}
for row in load():
    asin=str(row.get('asin') or '').strip()
    title=str(row.get('title') or '').strip()
    if not re.fullmatch(r'[A-Z0-9]{10}',asin) or not title: continue
    rating=numeric(row.get('rating'))
    reviews=numeric(row.get('review_count',row.get('reviews')),integer=True)
    obj={
        'asin':asin,
        'title':title,
        'rating':rating,
        'reviews':reviews,
        'eligible':eligible(row.get('kindle_plus_eligible',row.get('eligible'))),
        'source_page':numeric(row.get('page_number',row.get('source_page')),integer=True),
    }
    img=valid_image(row.get('image_url'))
    if img: obj['image_url']=img
    alt=row.get('image_alt')
    if isinstance(alt,str) and alt.strip(): obj['image_alt']=alt.strip()
    author=valid_author(row.get('author'))
    author_source=row.get('author_source')
    if author and author_source in ('amazon_search_card', 'amazon_product_page'):
        obj['author']=author
        obj['author_source']=author_source
        obj['author_verified']=True
    cats=categories(row.get('amazon_categories',row.get('categories')))
    if cats: obj['categories']=cats
    books[asin]=obj

DEST.parent.mkdir(parents=True,exist_ok=True)
tmp=DEST.with_name(DEST.name+'.tmp')
with tmp.open('w',encoding='utf-8') as f:
    # El PHP puede leer este arreglo registro por registro.
    f.write('[\n')
    for index, book in enumerate(books.values()):
        if index:
            f.write(',\n')
        json.dump(book, f, ensure_ascii=False, separators=(',', ':'))
    f.write('\n]\n')
    f.flush()
    os.fsync(f.fileno())
os.replace(tmp,DEST)
print(f'Exportados {len(books):,} libros a {DEST}')
print(f'Con imagen: {sum(bool(b.get("image_url")) for b in books.values()):,}')
print(f'Con autor verificado: {sum(bool(b.get("author_verified")) for b in books.values()):,}')
