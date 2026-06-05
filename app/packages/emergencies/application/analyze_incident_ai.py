import uuid
import logging
from app.packages.emergencies.infrastructure.repositories import IncidentRepository
from app.packages.emergencies.application.services.vision_service import VisionService
from app.packages.emergencies.application.services.nlp_service import NLPService
from app.packages.emergencies.domain.models import HistorialIncidente

logger = logging.getLogger(__name__)

class AnalyzeIncidentAIUseCase:
    """
    Caso de Uso (CU): Consolidar análisis de IA.
    Toma las evidencias (imágenes/audio) de un incidente y genera un resumen inteligente.
    """
    
    def __init__(self, repo: IncidentRepository):
        self.repo = repo
        self.vision_service = VisionService()
        self.nlp_service = NLPService()

    async def execute(self, id_incidente: uuid.UUID):
        # 1. Obtener el incidente y sus evidencias
        incidente = await self.repo.get_by_id(id_incidente)
        if not incidente:
            return None
            
        estado_original = incidente.estado_incidente
        
        # IDEMPOTENCIA: No re-analizar si ya está en proceso, analizado o asignado.
        if incidente.estado_incidente in ["ANALIZANDO", "ANALIZADO", "ASIGNADO", "TALLER_ASIGNADO", "FINALIZADO"]:
            logger.info(f"Incidente {id_incidente} ya procesado o en curso ({incidente.estado_incidente}). Omitiendo.")
            return incidente

        # BLOQUEO: Marcamos como ANALIZANDO inmediatamente para evitar duplicidad
        logger.info(f"Bloqueando incidente {id_incidente} para análisis inteligente...")
        incidente.estado_incidente = "ANALIZANDO"
        await self.repo.session.commit()
        await self.repo.session.refresh(incidente)

        logger.info(f"Iniciando análisis inteligente para incidente {id_incidente}")
        
        # 2. Procesar evidencias
        # Buscamos la última foto y el último audio subido (si existen) - Case insensitive
        logger.info(f"Buscando evidencias para {id_incidente}. Total: {len(incidente.evidencias)}")
        for e in incidente.evidencias:
            logger.info(f" - Evidencia: {e.evidencia_tipo} | URL: {e.archivo_url}")

        last_photo = next((e for e in reversed(incidente.evidencias) if e.evidencia_tipo.upper() == "FOTO"), None)
        last_audio = next((e for e in reversed(incidente.evidencias) if e.evidencia_tipo.upper() == "AUDIO"), None)
        
        # Si no hay foto ni descripción, saltamos el análisis de IA para continuar con la asignación
        if not last_photo and not incidente.descripcion:
            logger.info(f"Omitiendo análisis de IA para {id_incidente} (sin fotos ni descripción).")
            incidente.resumen_ia = "Emergencia reportada sin evidencias adicionales."
            incidente.analisis_consolidado = "Revisión manual requerida | Sin evidencias"
            incidente.estado_incidente = "ANALIZADO"
            
            historial = HistorialIncidente(
                id_incidente=id_incidente,
                incidente_estado_anterior=estado_original,
                incidente_estado_nuevo="ANALIZADO",
                historial_actor="SYSTEM",
                fecha=None
            )
            incidente.historial.append(historial)
            await self.repo.session.commit()
            await self.repo.session.refresh(incidente)
            return incidente

        logger.info(f"Seleccionados -> Foto: {last_photo.archivo_url if last_photo else 'None'}, Audio: {last_audio.archivo_url if last_audio else 'None'}")

        vision_results = {}
        nlp_results = {}
        
        if last_photo:
            logger.info(f"Analizando imagen con Roboflow: {last_photo.archivo_url}")
            vision_results = await self.vision_service.analyze_image(last_photo.archivo_url)
            # Actualizar la evidencia con el análisis
            last_photo.analisis_imagen = f"Detectado: {vision_results.get('top_class')}"
            last_photo.confianza_deteccion = vision_results.get("confidence")

        # Siempre analizamos con Gemini, pasando datos de visión y audio si existen
        logger.info("Enviando reporte a NLPService (Gemini Multimodal)...")
        nlp_results = await self.nlp_service.process_report(
            transcription_text=incidente.descripcion or "", 
            vision_data=vision_results,
            audio_url=last_audio.archivo_url if last_audio else None,
            image_url=last_photo.archivo_url if last_photo else None
        )
        logger.info(f"Resultado NLP: {nlp_results}")
        
        if last_audio and nlp_results:
            # Guardamos la transcripción REAL del audio
            last_audio.transcripcion = nlp_results.get("transcription")
        
        # 3. Consolidar resultados
        estado_completado = nlp_results.get("estado_completado", True)
        
        if not estado_completado:
            # Slot Filling: El análisis no está completado porque falta información
            mensaje = nlp_results.get("mensaje_respuesta", "Información incompleta. Se requieren más detalles de la falla.")
            incidente.resumen_ia = mensaje
            incidente.analisis_consolidado = "Estado: Slot Filling en curso. Datos incompletos."
            incidente.estado_incidente = "DATOS_INCOMPLETOS"
            
            historial = HistorialIncidente(
                id_incidente=id_incidente,
                incidente_estado_anterior=estado_original,
                incidente_estado_nuevo="DATOS_INCOMPLETOS",
                historial_actor="AI_BOT",
                fecha=None
            )
            incidente.historial.append(historial)
        else:
            # Generamos el resumen inteligente final usando el texto de Gemini
            resumen_ia = nlp_results.get('summary', 'Estamos analizando tu caso. Un taller se pondrá en contacto pronto.')
            falla = nlp_results.get('falla', 'Desconocida')
            gravedad = nlp_results.get('gravedad', 'Media')
            incidente.analisis_consolidado = f"Falla: {falla} | Gravedad: {gravedad}"
            incidente.resumen_ia = resumen_ia
            incidente.estado_incidente = "ANALIZADO"
            
            historial = HistorialIncidente(
                id_incidente=id_incidente,
                incidente_estado_anterior=estado_original,
                incidente_estado_nuevo="ANALIZADO",
                historial_actor="AI_BOT",
                fecha=None
            )
            incidente.historial.append(historial)
        
        await self.repo.session.commit()
        await self.repo.session.refresh(incidente)
        
        logger.info(f"Incidente {id_incidente} analizado correctamente por IA")
        return incidente

        return incidente
