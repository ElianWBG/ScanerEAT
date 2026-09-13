from rest_framework import serializers

from .models import EventoEntrega, EventoOcupacion, Mesa, Personal


class MesaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Mesa
        fields = [
            "id",
            "numero",
            "camara_id",
            "zona_poligono",
            "capacidad",
            "activa",
            "mesas_adyacentes",
        ]


class PersonalSerializer(serializers.ModelSerializer):
    class Meta:
        model = Personal
        fields = ["id", "codigo_tracking", "alias", "primera_deteccion", "activo"]


class EventoEntregaSerializer(serializers.ModelSerializer):
    class Meta:
        model = EventoEntrega
        fields = [
            "id",
            "evento_ocupacion",
            "personal",
            "tipo",
            "timestamp",
            "tiempo_espera_segundos",
            "confianza_deteccion",
        ]


class EventoEntregaCreateSerializer(serializers.ModelSerializer):
    """
    Serializer usado por el microservicio de visión al reportar una entrega.
    Calcula tiempo_espera_segundos automáticamente si no se envía explícito.
    """

    class Meta:
        model = EventoEntrega
        fields = [
            "id",
            "evento_ocupacion",
            "personal",
            "tipo",
            "timestamp",
            "tiempo_espera_segundos",
            "confianza_deteccion",
        ]
        extra_kwargs = {"tiempo_espera_segundos": {"required": False}}

    def validate(self, attrs):
        if "tiempo_espera_segundos" not in attrs or attrs.get("tiempo_espera_segundos") is None:
            ocupacion = attrs["evento_ocupacion"]
            delta = attrs["timestamp"] - ocupacion.inicio
            attrs["tiempo_espera_segundos"] = max(int(delta.total_seconds()), 0)
        return attrs


class EventoOcupacionSerializer(serializers.ModelSerializer):
    entregas = EventoEntregaSerializer(many=True, read_only=True)
    duracion_segundos = serializers.ReadOnlyField()
    tiempo_espera_promedio_segundos = serializers.ReadOnlyField()
    clip_s3_url = serializers.ReadOnlyField()

    class Meta:
        model = EventoOcupacion
        fields = [
            "id",
            "mesa",
            "inicio",
            "fin",
            "estado",
            "num_personas_detectadas",
            "confianza_deteccion",
            "fusionada_con",
            "clip_s3_key",
            "clip_s3_url",
            "duracion_segundos",
            "tiempo_espera_promedio_segundos",
            "entregas",
        ]


class EventoOcupacionCreateSerializer(serializers.ModelSerializer):
    """
    Serializer minimal usado por el microservicio de visión al abrir/cerrar
    ocupaciones y para adjuntar (PATCH) el clip de evidencia subido a S3.
    """

    class Meta:
        model = EventoOcupacion
        fields = [
            "id",
            "mesa",
            "inicio",
            "fin",
            "estado",
            "num_personas_detectadas",
            "confianza_deteccion",
            "fusionada_con",
            "clip_s3_key",
        ]


# --- Serializers de solo-lectura para las métricas obligatorias -----------------


class MetricaTiempoEsperaMesaSerializer(serializers.Serializer):
    mesa_id = serializers.IntegerField()
    mesa_numero = serializers.IntegerField()
    total_ocupaciones = serializers.IntegerField()
    total_entregas = serializers.IntegerField()
    tiempo_espera_promedio_segundos = serializers.FloatField(allow_null=True)
    tiempo_espera_maximo_segundos = serializers.IntegerField(allow_null=True)


class MetricaEmpleadoSerializer(serializers.Serializer):
    personal_id = serializers.IntegerField(allow_null=True)
    codigo_tracking = serializers.CharField(allow_null=True)
    alias = serializers.CharField(allow_blank=True)
    mesas_distintas_atendidas = serializers.IntegerField()
    total_entregas = serializers.IntegerField()


class MetricaUsoMesaSerializer(serializers.Serializer):
    mesa_id = serializers.IntegerField()
    mesa_numero = serializers.IntegerField()
    total_ocupaciones = serializers.IntegerField()
    tiempo_total_ocupada_segundos = serializers.FloatField()
    tiempo_promedio_por_ocupacion_segundos = serializers.FloatField(allow_null=True)
