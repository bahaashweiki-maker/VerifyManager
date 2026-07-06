# services/page_service.py

pages = {
    "HOME": {
        "text": (
            "👋 <b>ברוכים הבאים ל-VerifyManager</b>\n\n"
            "🔐 מערכת אימות זהות מאובטחת.\n\n"
            "באמצעות המערכת ניתן לבצע אימות זהות בצורה "
            "מהירה, פשוטה ובטוחה.\n\n"
            "👇 בחר את הפעולה הרצויה:"
        ),
        "buttons": [
            {"title": "🪪 שלח אימות", "target_page": "VERIFY"},
            {"title": "ℹ️ אודות", "target_page": "ABOUT"},
            {"title": "📞 צור קשר", "target_page": "CONTACT"},
        ]
    },

    "ABOUT": {
        "text": (
            "ℹ️ <b>אודות המערכת</b>\n\n"
            "VerifyManager היא מערכת לניהול ואימות משתמשים.\n\n"
            "✔️ אימות זהות\n"
            "✔️ בדיקה ידנית ע״י מנהל\n"
            "✔️ שמירה מאובטחת של הנתונים\n"
            "✔️ הודעה אוטומטית לאחר סיום הבדיקה"
        ),
        "buttons": [
            {"title": "🏠 חזרה לדף הבית", "target_page": "HOME"}
        ]
    },

    "CONTACT": {
        "text": (
            "📞 <b>יצירת קשר</b>\n\n"
            "לכל שאלה או בעיה ניתן ליצור קשר עם הנהלת המערכת.\n\n"
            "💬 מענה יינתן בהקדם האפשרי."
        ),
        "buttons": [
            {"title": "🏠 חזרה לדף הבית", "target_page": "HOME"}
        ]
    },

    "VERIFY": {
        "text": (
            "🔐 <b>מערכת אימות זהות</b>\n\n"
            "לחץ על הכפתור למטה כדי להתחיל את תהליך האימות."
        ),
        "buttons": [
            {"title": "▶️ התחל אימות", "target_page": "START_VERIFY"},
            {"title": "🏠 חזרה לדף הבית", "target_page": "HOME"}
        ]
    }
}


def load_page(page_key: str):
    return pages.get(page_key)