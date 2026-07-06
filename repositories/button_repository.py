from database.database import get_connection


def create_button(
    page_key: str,
    title: str,
    target_page: str,
    order_index: int = 0,
):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO buttons
        (
            page_key,
            title,
            target_page,
            order_index
        )
        VALUES (?, ?, ?, ?)
    """, (
        page_key,
        title,
        target_page,
        order_index,
    ))

    conn.commit()
    conn.close()


def get_buttons(page_key: str):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM buttons
        WHERE page_key = ?
        ORDER BY order_index ASC
    """, (page_key,))

    buttons = cursor.fetchall()

    conn.close()

    return buttons