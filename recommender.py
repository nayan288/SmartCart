"""Item-based collaborative filtering using cosine similarity (pandas + numpy)."""
import numpy as np
import pandas as pd
from db import get_db


def _load_interactions():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT o.user_id, oi.product_id, SUM(oi.quantity) AS qty "
        "FROM orders o JOIN order_items oi ON oi.order_id = o.id "
        "WHERE o.status <> 'Cancelled' GROUP BY o.user_id, oi.product_id"
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    df = pd.DataFrame(rows)
    if not df.empty:
        df["qty"] = df["qty"].astype(float)
    return df


def recommend_for_product(product_id, n=4):
    """Return product ids that are often bought by the same customers."""
    df = _load_interactions()
    if df.empty or product_id not in df["product_id"].values:
        return []

    matrix = df.pivot_table(index="user_id", columns="product_id", values="qty", fill_value=0)
    M = matrix.values.astype(float)

    norms = np.linalg.norm(M, axis=0)
    norms[norms == 0] = 1
    similarity = (M.T @ M) / np.outer(norms, norms)

    cols = list(matrix.columns)
    scores = similarity[cols.index(product_id)]
    ranked = np.argsort(-scores)

    result = [int(cols[i]) for i in ranked if cols[i] != product_id and scores[i] > 0]
    return result[:n]



if __name__ == "__main__":
    print(recommend_for_product(1))