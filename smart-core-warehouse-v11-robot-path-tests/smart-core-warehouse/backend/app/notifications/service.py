from sqlalchemy.orm import Session
from app.core.models import Alert
from app.core.enums import AlertSeverity
from app.events.service import emit

class NotificationService:
    """POC in-app notification channel backed by Alerts; external email/SMS providers can replace it."""
    def notify(self, db:Session, code:str, message:str, severity:str=AlertSeverity.INFO.value) -> Alert:
        alert=Alert(code=code,severity=severity,message=message,active=True)
        db.add(alert);db.flush();emit(db,'ALERT_RAISED','alert',alert.id,{'code':code,'severity':severity})
        return alert

notifications=NotificationService()
