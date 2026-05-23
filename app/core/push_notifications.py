import firebase_admin
from firebase_admin import credentials, messaging
import logging
import os
from app.core.config import settings

logger = logging.getLogger(__name__)

class PushNotificationService:
    _initialized = False

    @classmethod
    def initialize(cls):
        if cls._initialized:
            return

        try:
            cert_path = settings.FIREBASE_SERVICE_ACCOUNT_PATH
            if not cert_path:
                logger.warning("FIREBASE_SERVICE_ACCOUNT_PATH no está configurado.")
                return

            if not os.path.exists(cert_path):
                logger.error(f"El archivo de credenciales de Firebase no existe en: {cert_path}")
                return

            cred = credentials.Certificate(cert_path)
            firebase_admin.initialize_app(cred)
            cls._initialized = True
            logger.info("Firebase Admin SDK inicializado correctamente.")
        except Exception as e:
            logger.error(f"Error al inicializar Firebase Admin SDK: {e}")

    @staticmethod
    async def send_push_notification(token: str, title: str, body: str, data: dict = None):
        """Envía una notificación push a un token específico."""
        if not PushNotificationService._initialized:
            PushNotificationService.initialize()

        try:
            message = messaging.Message(
                notification=messaging.Notification(
                    title=title,
                    body=body,
                ),
                android=messaging.AndroidConfig(
                    priority="high",
                    notification=messaging.AndroidNotification(
                        channel_id="high_importance_channel",
                        click_action="FLUTTER_NOTIFICATION_CLICK",
                    ),
                ),
                webpush=messaging.WebpushConfig(
                    notification=messaging.WebpushNotification(
                        icon="/favicon.ico",
                        badge="/favicon.ico",
                    ),
                    fcm_options=messaging.WebpushFcmOptions(
                        link=settings.FRONTEND_URL if hasattr(settings, 'FRONTEND_URL') else "https://smart-mechanic-frontend.vercel.app"
                    )
                ),
                data=data or {},
                token=token,
            )
            response = messaging.send(message)
            logger.info(f"✅ PUSH: Notificación enviada con éxito. ID: {response}")
            return response
        except Exception as e:
            logger.error(f"❌ PUSH: Error al enviar notificación a Firebase: {e}")
            return None

# Instancia global
push_service = PushNotificationService()
