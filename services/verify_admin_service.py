from database.database import get_connection


def get_pending_verifications():
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT *
            FROM verifications
            WHERE status = 'pending'
            ORDER BY created_at ASC
        """)

        return cursor.fetchall()


def get_approved_verifications():
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT *
            FROM verifications
            WHERE status = 'approved'
            ORDER BY created_at DESC
        """)

        return cursor.fetchall()


def get_rejected_verifications():
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT *
            FROM verifications
            WHERE status = 'rejected'
            ORDER BY created_at DESC
        """)

        return cursor.fetchall()


def get_blocked_verifications():
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT *
            FROM verifications
            WHERE status = 'blocked'
            ORDER BY created_at DESC
        """)

        return cursor.fetchall()


def get_verification_by_id(verification_id):
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT *
            FROM verifications
            WHERE id = ?
        """, (verification_id,))

        return cursor.fetchone()