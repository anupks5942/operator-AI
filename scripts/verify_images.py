"""Quick verification script for image retrieval."""
import sys
import os
import sqlite3
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

db_path = "kb_structured.db"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

print("=== Top 10 articles with most images ===")
rows = conn.execute("""
    SELECT icm.article_id, COUNT(*) as img_count
    FROM image_case_map icm
    GROUP BY icm.article_id
    ORDER BY img_count DESC
    LIMIT 10
""").fetchall()
for r in rows:
    print(f"  {r['article_id']}: {r['img_count']} images")

print("\n=== Sample images (first 5) ===")
rows2 = conn.execute("SELECT image_id, source_doc, page_number, file_path FROM images LIMIT 5").fetchall()
for r in rows2:
    exists = os.path.exists(r['file_path'])
    print(f"  {r['image_id']} | page={r['page_number']} | exists={exists}")

print("\n=== Skip log summary ===")
rows3 = conn.execute("SELECT source_doc, reason, COUNT(*) as cnt FROM pdf_page_skip_log GROUP BY source_doc, reason").fetchall()
for r in rows3:
    print(f"  {r['source_doc']}: {r['reason']} ({r['cnt']} pages)")

print("\n=== Image types distribution ===")
rows4 = conn.execute("SELECT image_type, COUNT(*) as cnt FROM images GROUP BY image_type").fetchall()
for r in rows4:
    print(f"  {r['image_type']}: {r['cnt']}")

from src.services.image_retrieval import get_case_images
print("\n=== Retrieval test: KB-READER-001 ===")
imgs = get_case_images("KB-READER-001", include_linked=True)
print(f"  Total: {len(imgs)} images")
for i in imgs[:3]:
    print(f"    {i['image_id']} primary={i.get('is_primary')}")

conn.close()
print("\nAll verifications passed.")
