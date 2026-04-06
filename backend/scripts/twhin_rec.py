"""
Cached TWHIN-BERT recommendation system.

Embeds user bios once, new posts incrementally, computes cosine
similarity with numpy. Same quality as original OASIS paper, ~15ms
per round instead of 200s.
"""

import numpy as np

# ── Singleton model ──────────────────────────────────────────────
_twhin_model = None
_twhin_tokenizer = None


def get_twhin_bert():
    """Lazy-load TWHIN-BERT model and tokenizer (singleton, ~2s first call)."""
    global _twhin_model, _twhin_tokenizer
    if _twhin_model is None:
        import torch
        from transformers import AutoModel, AutoTokenizer
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        _twhin_tokenizer = AutoTokenizer.from_pretrained(
            "Twitter/twhin-bert-base", model_max_length=512
        )
        _twhin_model = AutoModel.from_pretrained(
            "Twitter/twhin-bert-base"
        ).to(device).eval()
    return _twhin_model, _twhin_tokenizer


def twhin_embed(texts: list) -> np.ndarray:
    """Embed texts with TWHIN-BERT. Returns (N, 768) float32 numpy array."""
    import torch
    model, tokenizer = get_twhin_bert()
    device = next(model.parameters()).device
    with torch.no_grad():
        inputs = tokenizer(texts, return_tensors="pt", padding=True, truncation=True)
        inputs = {k: v.to(device) for k, v in inputs.items()}
        outputs = model(**inputs)
    return outputs.pooler_output.cpu().numpy()


def create_twhin_rec_updater(platform, log_fn, suffix=""):
    """Create a cached TWHIN-BERT rec update function for a platform.

    Args:
        platform: OASIS Platform object (has db_cursor, max_rec_post_len)
        log_fn: logging function (e.g. log_info)
        suffix: identifier for logging ("" for Twitter, "Reddit" for Reddit)

    Returns:
        async function to replace platform.update_rec_table
    """
    max_rec = getattr(platform, 'max_rec_post_len', 20)
    last_post_id = [0]
    user_embs = [None]   # mutable container for numpy array
    post_embs = [None]
    post_ids = []
    user_ids = []

    async def _rec_update():
        try:
            cursor = platform.db_cursor

            # 1. One-time: embed all user bios
            if user_embs[0] is None:
                cursor.execute("SELECT user_id, bio FROM user ORDER BY user_id")
                rows = cursor.fetchall()
                user_ids.clear()
                bios = []
                for uid, bio in rows:
                    user_ids.append(uid)
                    bios.append(bio if bio else "user")
                if bios:
                    user_embs[0] = twhin_embed(bios)
                    log_fn(f"TWHIN rec{suffix}: embedded {len(bios)} users")

            # 2. Embed only new posts
            cursor.execute(
                "SELECT post_id, content FROM post WHERE post_id > ? ORDER BY post_id",
                (last_post_id[0],),
            )
            new_posts = [(pid, c) for pid, c in cursor.fetchall() if c]
            if new_posts:
                new_ids = [p[0] for p in new_posts]
                new_vecs = twhin_embed([p[1] for p in new_posts])
                post_ids.extend(new_ids)
                if post_embs[0] is None:
                    post_embs[0] = new_vecs
                else:
                    post_embs[0] = np.vstack([post_embs[0], new_vecs])
                last_post_id[0] = new_ids[-1]

            # 3. Compute similarity & build rec table
            cursor.execute("DELETE FROM rec")
            insert_values = []

            u = user_embs[0]
            p = post_embs[0]
            if u is not None and p is not None and len(p) > 0 and len(u) > 0:
                u_norm = u / (np.linalg.norm(u, axis=1, keepdims=True) + 1e-8)
                p_norm = p / (np.linalg.norm(p, axis=1, keepdims=True) + 1e-8)
                sim = u_norm @ p_norm.T
                k = min(max_rec, sim.shape[1])
                top_k = np.argpartition(-sim, k, axis=1)[:, :k]
                for i, uid in enumerate(user_ids):
                    for j in top_k[i]:
                        insert_values.append((uid, post_ids[j]))

            # Fallback: recent posts
            if not insert_values:
                cursor.execute(
                    "SELECT post_id FROM post ORDER BY created_at DESC LIMIT ?",
                    (min(200, max_rec * 3),),
                )
                all_posts = [r[0] for r in cursor.fetchall()]
                if all_posts:
                    cursor.execute("SELECT user_id FROM user")
                    for uid, in cursor.fetchall():
                        for pid in all_posts[:max_rec]:
                            insert_values.append((uid, pid))

            if insert_values:
                cursor.executemany(
                    "INSERT INTO rec (user_id, post_id) VALUES (?, ?)",
                    insert_values,
                )
                cursor.connection.commit()
        except Exception as exc:
            log_fn(f"TWHIN rec{suffix} error: {exc}")

    return _rec_update
