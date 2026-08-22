#!/usr/bin/env python3
"""Index documents for retrieval, from the command line.

    python scripts/ingest_rag_documents.py --file handbook.pdf
    python scripts/ingest_rag_documents.py --dir ./docs --collection handbook
    python scripts/ingest_rag_documents.py --dir ./docs --recursive --dry-run
    python scripts/ingest_rag_documents.py --list --collection handbook

This used to POST to a separate "RAG Pipeline" service and needed that service,
Qdrant, and three environment variables before it could do anything. Retrieval
now runs in-process, so this calls it directly and works on a fresh checkout
with nothing configured.

Where the vectors go is still configurable — set RAG_BACKEND to qdrant,
pgvector, pinecone, faiss or chromadb and this script is unchanged.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.rag.service import get_rag_service  # noqa: E402
from src.tools.file_analysis import ALLOWED_SUFFIXES  # noqa: E402


def collect(args: argparse.Namespace) -> list[Path]:
    """Every file this run should index."""
    if args.file:
        return [Path(args.file)]

    root = Path(args.dir)
    if not root.is_dir():
        raise SystemExit(f"not a directory: {root}")
    found = root.rglob("*") if args.recursive else root.glob("*")
    return sorted(
        path for path in found
        if path.is_file() and path.suffix.lower() in ALLOWED_SUFFIXES
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--file", help="one file to index")
    source.add_argument("--dir", help="a directory of files to index")
    parser.add_argument("--collection", default=None, help="collection name")
    parser.add_argument("--recursive", action="store_true", help="descend into subdirectories")
    parser.add_argument("--dry-run", action="store_true", help="show what would be indexed")
    parser.add_argument("--list", action="store_true", help="list what is already indexed")
    parser.add_argument("--delete", metavar="SOURCE", help="remove one document")
    args = parser.parse_args()

    service = get_rag_service()
    collection = service.collection_for(args.collection)

    if args.list:
        documents = service.documents(args.collection)
        stats = service.stats(args.collection)
        print(f"{collection}: {stats['chunks']} chunk(s) from {len(documents)} document(s) "
              f"in {stats['backend']}, embedded with {stats['embeddings']}")
        for item in documents:
            print(f"  {item['source']:<48} {item['chunks']:>4} chunk(s)  {item['characters']:>8} chars")
        return 0

    if args.delete:
        removed = service.delete_document(args.delete, args.collection)
        print(f"removed {removed} chunk(s) for {args.delete!r}"
              if removed else f"{args.delete!r} was not indexed in {collection}")
        return 0 if removed else 1

    if not (args.file or args.dir):
        parser.error("one of --file, --dir, --list or --delete is required")

    targets = collect(args)
    if not targets:
        print("nothing to index")
        return 1

    if args.dry_run:
        print(f"would index {len(targets)} file(s) into {collection}:")
        for path in targets:
            print(f"  {path}")
        return 0

    print(f"indexing {len(targets)} file(s) into {collection} "
          f"({service.store.name}, {service.embedder.name} embeddings)")

    indexed = failed = 0
    for path in targets:
        try:
            result = service.ingest_file(path, collection=args.collection)
        except Exception as exc:                      # one bad file must not stop the run
            print(f"  {path.name:<44} failed: {exc}")
            failed += 1
            continue
        if result.chunks:
            replaced = f", replaced {result.replaced}" if result.replaced else ""
            print(f"  {path.name:<44} {result.chunks:>4} chunk(s){replaced}")
            indexed += 1
        else:
            print(f"  {path.name:<44} skipped: {result.note}")
            failed += 1

    stats = service.stats(args.collection)
    print(f"\n{indexed} indexed, {failed} skipped — {collection} now holds "
          f"{stats['chunks']} chunk(s) from {stats['documents']} document(s)")
    return 0 if indexed else 1


if __name__ == "__main__":
    raise SystemExit(main())
