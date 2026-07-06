from database.database import get_connection


def get_pending_verifications():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM verifications
        WHERE status = 'pending'
        ORDER BY created_at ASC
    """)

    rows = cursor.fetchall()

    conn.close()

    return rows


def get_approved_verifications():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM verifications
        WHERE status = 'approved'
        ORDER BY created_at DESC
    """)

    rows = cursor.fetchall()

    conn.close()

    return rows


def get_rejected_verifications():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM verifications
        WHERE status = 'rejected'
        ORDER BY created_at DESC
    """)

    rows = cursor.fetchall()

    conn.close()

    return rows


def get_blocked_verifications():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM verifications
        WHERE status = 'blocked'
        ORDER BY created_at DESC
    """)

    rows = cursor.fetchall()

    conn.close()

    return rows

def get_verification_by_id(verification_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM verifications
        WHERE id = ?
    """, (verification_id,))

    row = cursor.fetchone()

    conn.close()

    return row