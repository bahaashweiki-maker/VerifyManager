from database.database import get_connection


def get_page(page_key: str):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM pages
        WHERE page_key = ?
        LIMIT 1
    """, (page_key,))

    page = cursor.fetchone()

    conn.close()

    return page


def get_all_pages():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM pages
        ORDER BY id ASC
    """)

    pages = cursor.fetchall()

    conn.close()

    return pages


def create_page(
    page_key: str,
    title: str,
    text: str,
):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT OR IGNORE INTO pages
        (
            page_key,
            title,
            text
        )
        VALUES (?, ?, ?)
    """, (
        page_key,
        title,
        text
    ))

    conn.commit()
    conn.close()