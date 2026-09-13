"""
Modelo de datos del sistema de monitoreo de mesas.

Entidades principales:
    Mesa             -> mesas físicas del restaurante, con su zona fija en el video.
    Personal          -> personas del staff identificadas por comportamiento (tracking),
                         no por apariencia ni nombre real.
    EventoOcupacion   -> ciclo de vida de una mesa ocupada (inicio, fin, fusión, personas).
    EventoEntrega     -> cada entrega individual dentro de una ocupación (no todo el
                         pedido llega junto, ni siempre hay aperitivo previo).

Estas entidades alimentan las 3 métricas obligatorias del profesor:
    1) Tiempo de espera por mesa (por entrega y promedio por ocupación).
    2) Empleado que atiende más mesas (conteo de EventoEntrega por Personal).
    3) Mesas más y menos usadas (conteo/duración de EventoOcupacion por Mesa).
"""

from django.conf import settings
from django.db import models
from django.core.validators import MinValueValidator
from django.utils import timezone


class Mesa(models.Model):
    """Mesa física del restaurante, mapeada a una zona fija dentro del feed de video."""

    numero = models.PositiveIntegerField(
        unique=True,
        help_text="Número/identificador visible de la mesa (ej. Mesa 5).",
    )
    camara_id = models.CharField(
        max_length=50,
        help_text="Identificador de la cámara de seguridad que cubre esta mesa.",
    )
    zona_poligono = models.JSONField(
        help_text=(
            "Lista de puntos [[x1,y1],[x2,y2],...] que definen el polígono fijo "
            "de la mesa en el frame de video, usado para el análisis de solapamiento "
            "geométrico (overlap) contra las detecciones de YOLOv8."
        ),
    )
    capacidad = models.PositiveSmallIntegerField(default=4)
    activa = models.BooleanField(
        default=True,
        help_text="Si está en False, el sistema ignora esta mesa (ej. en mantenimiento).",
    )
    mesas_adyacentes = models.ManyToManyField(
        "self",
        blank=True,
        symmetrical=True,
        help_text=(
            "Mesas físicamente contiguas, usadas por la heurística de fusión de mesas "
            "(ocupación simultánea de adyacentes + exceso de personas detectadas)."
        ),
    )

    class Meta:
        ordering = ["numero"]
        verbose_name = "Mesa"
        verbose_name_plural = "Mesas"

    def __str__(self):
        return f"Mesa {self.numero}"


class Personal(models.Model):
    """
    Miembro del staff identificado por comportamiento vía tracking (SORT/DeepSORT):
    visita varias mesas brevemente sin sentarse. No hay uniforme distintivo ni
    reconocimiento facial/nombre real; el sistema solo conoce un ID de tracking
    persistente entre sesiones (re-identificación por apariencia/embeddings).
    """

    codigo_tracking = models.CharField(
        max_length=64,
        unique=True,
        help_text="ID interno persistente asignado por el microservicio de visión.",
    )
    alias = models.CharField(
        max_length=100,
        blank=True,
        help_text="Alias opcional asignado manualmente (ej. 'Mesero turno tarde').",
    )
    primera_deteccion = models.DateTimeField(default=timezone.now)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["-primera_deteccion"]
        verbose_name = "Personal"
        verbose_name_plural = "Personal"

    def __str__(self):
        return self.alias or self.codigo_tracking


class EventoOcupacion(models.Model):
    """
    Ciclo de vida de una mesa ocupada. Se abre cuando la detección de personas/objetos
    dentro de la zona supera el umbral de forma sostenida (pasado el período de gracia)
    y se cierra cuando la zona queda vacía más allá de ese mismo período de gracia
    (para no confundir una ausencia temporal —ir al baño, a la caja— con mesa libre).
    """

    class Estado(models.TextChoices):
        EN_GRACIA = "en_gracia", "En período de gracia"
        OCUPADA = "ocupada", "Ocupada"
        LIBERADA = "liberada", "Liberada"
        FUSIONADA = "fusionada", "Fusionada con otra mesa"

    mesa = models.ForeignKey(
        Mesa, on_delete=models.CASCADE, related_name="eventos_ocupacion"
    )
    inicio = models.DateTimeField()
    fin = models.DateTimeField(null=True, blank=True)
    estado = models.CharField(
        max_length=20, choices=Estado.choices, default=Estado.EN_GRACIA
    )
    num_personas_detectadas = models.PositiveSmallIntegerField(default=1)
    confianza_deteccion = models.FloatField(
        default=0.0,
        validators=[MinValueValidator(0.0)],
        help_text="Confianza promedio de YOLOv8 para las detecciones de esta ocupación.",
    )
    fusionada_con = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fusiones_hijas",
        help_text=(
            "Otro EventoOcupacion con el que se detectó fusión heurística "
            "(mesas adyacentes ocupadas a la vez + exceso de personas)."
        ),
    )
    clip_s3_key = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text=(
            "Key del clip de video subido a S3 como evidencia de esta ocupación "
            "(ej. evidencia/cam-1/mesa-3/2026/09/11/ocupacion-20260911T123000.mp4). "
            "Lo sube el microservicio de visión al cerrarse la ocupación; vacío si "
            "no hay bucket configurado o la subida falló."
        ),
    )

    class Meta:
        ordering = ["-inicio"]
        verbose_name = "Evento de ocupación"
        verbose_name_plural = "Eventos de ocupación"
        indexes = [
            models.Index(fields=["mesa", "inicio"]),
            models.Index(fields=["estado"]),
        ]

    def __str__(self):
        return f"{self.mesa} · {self.inicio:%Y-%m-%d %H:%M} · {self.estado}"

    @property
    def duracion_segundos(self):
        fin = self.fin or timezone.now()
        return max((fin - self.inicio).total_seconds(), 0)

    @property
    def tiempo_espera_promedio_segundos(self):
        """Promedio de tiempo de espera calculado sobre TODAS las entregas de esta ocupación."""
        entregas = self.entregas.all()
        if not entregas:
            return None
        return sum(e.tiempo_espera_segundos for e in entregas) / entregas.count()

    @property
    def clip_s3_url(self):
        """URL https del clip de evidencia en S3 (None si no hay clip o bucket configurado)."""
        bucket = getattr(settings, "AWS_STORAGE_BUCKET_NAME", "")
        if not self.clip_s3_key or not bucket:
            return None
        region = getattr(settings, "AWS_S3_REGION_NAME", "us-east-1")
        return f"https://{bucket}.s3.{region}.amazonaws.com/{self.clip_s3_key}"


class EventoEntrega(models.Model):
    """
    Entrega individual dentro de una ocupación. El pedido no siempre llega completo
    de una vez (puede haber aperitivo, bebidas y plato principal por separado), así
    que cada entrega se modela y cronometra de forma independiente.
    """

    class Tipo(models.TextChoices):
        APERITIVO = "aperitivo", "Aperitivo"
        BEBIDA = "bebida", "Bebida"
        PLATO_PRINCIPAL = "plato_principal", "Plato principal"
        CUENTA = "cuenta", "Cuenta"
        OTRO = "otro", "Otro"

    evento_ocupacion = models.ForeignKey(
        EventoOcupacion, on_delete=models.CASCADE, related_name="entregas"
    )
    personal = models.ForeignKey(
        Personal,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entregas",
        help_text="Puede ser null si el sistema no logró asociar a ningún miembro del staff.",
    )
    tipo = models.CharField(max_length=20, choices=Tipo.choices, default=Tipo.OTRO)
    timestamp = models.DateTimeField()
    tiempo_espera_segundos = models.PositiveIntegerField(
        help_text="Segundos entre el inicio de la ocupación y esta entrega."
    )
    confianza_deteccion = models.FloatField(default=0.0)

    class Meta:
        ordering = ["timestamp"]
        verbose_name = "Evento de entrega"
        verbose_name_plural = "Eventos de entrega"
        indexes = [
            models.Index(fields=["evento_ocupacion", "timestamp"]),
            models.Index(fields=["personal"]),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} · {self.evento_ocupacion.mesa} · {self.timestamp:%H:%M:%S}"
