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


# ======================================
# אישור אימות
# ======================================

def approve_verification(verification_id):
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE verifications
            SET status = 'approved',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (verification_id,))

        conn.commit()


# ======================================
# דחיית אימות
# ======================================

def reject_verification(verification_id):
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE verifications
            SET status = 'rejected',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (verification_id,))

        conn.commit()


# ======================================
# חסימת משתמש
# ======================================

def block_verification(verification_id):
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE verifications
            SET status = 'blocked',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (verification_id,))

        conn.commit()


# ======================================
# מחיקת אימות
# ======================================

def delete_verification(verification_id):
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            DELETE FROM verifications
            WHERE id = ?
        """, (verification_id,))

        conn.commit()


# ======================================
# סטטיסטיקות
# ======================================

def get_verification_stats():
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT status, COUNT(*) AS total
            FROM verifications
            GROUP BY status
        """)

        return cursor.fetchall()
    
def get_verification_index(verifications, verification_id):
    for index, verify in enumerate(verifications):
        if verify["id"] == verification_id:
            return index

    return -1