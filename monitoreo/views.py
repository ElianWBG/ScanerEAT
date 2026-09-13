"""
Views de la API.

Incluye:
    - CRUD estándar (ViewSets) para Mesa, Personal, EventoOcupacion, EventoEntrega.
      El microservicio de visión usa estos endpoints para reportar lo que detecta.
    - 3 endpoints de métricas obligatorias, cada uno devuelve datos agregados
      listos para graficar en un dashboard:
        GET /api/metricas/tiempo-espera/      -> tiempo de espera por mesa
        GET /api/metricas/empleados/          -> qué empleado atiende más mesas
        GET /api/metricas/uso-mesas/          -> mesas más y menos usadas
"""

from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Max, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import EventoEntrega, EventoOcupacion, Mesa, Personal
from .serializers import (
    EventoEntregaCreateSerializer,
    EventoEntregaSerializer,
    EventoOcupacionCreateSerializer,
    EventoOcupacionSerializer,
    MesaSerializer,
    MetricaEmpleadoSerializer,
    MetricaTiempoEsperaMesaSerializer,
    MetricaUsoMesaSerializer,
    PersonalSerializer,
)


class MesaViewSet(viewsets.ModelViewSet):
    queryset = Mesa.objects.all()
    serializer_class = MesaSerializer


class PersonalViewSet(viewsets.ModelViewSet):
    queryset = Personal.objects.all()
    serializer_class = PersonalSerializer


class EventoOcupacionViewSet(viewsets.ModelViewSet):
    queryset = EventoOcupacion.objects.select_related("mesa").prefetch_related("entregas")

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return EventoOcupacionCreateSerializer
        return EventoOcupacionSerializer


class EventoEntregaViewSet(viewsets.ModelViewSet):
    queryset = EventoEntrega.objects.select_related("evento_ocupacion", "personal")

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return EventoEntregaCreateSerializer
        return EventoEntregaSerializer


# --- Métrica 1: tiempo de espera por mesa ---------------------------------------


@api_view(["GET"])
def metrica_tiempo_espera(request):
    """
    Tiempo de espera por mesa, calculado sobre EventoEntrega (cada entrega ya trae
    su propio tiempo_espera_segundos respecto al inicio de la ocupación). Se agrega
    el promedio y el máximo por mesa, más el conteo de ocupaciones/entregas.
    """
    qs = (
        Mesa.objects.filter(activa=True)
        .annotate(
            total_ocupaciones=Count("eventos_ocupacion", distinct=True),
            total_entregas=Count("eventos_ocupacion__entregas", distinct=True),
            tiempo_espera_promedio_segundos=Avg("eventos_ocupacion__entregas__tiempo_espera_segundos"),
            tiempo_espera_maximo_segundos=Max("eventos_ocupacion__entregas__tiempo_espera_segundos"),
        )
        .order_by("-tiempo_espera_promedio_segundos")
    )
    data = [
        {
            "mesa_id": m.id,
            "mesa_numero": m.numero,
            "total_ocupaciones": m.total_ocupaciones,
            "total_entregas": m.total_entregas,
            "tiempo_espera_promedio_segundos": m.tiempo_espera_promedio_segundos,
            "tiempo_espera_maximo_segundos": m.tiempo_espera_maximo_segundos,
        }
        for m in qs
    ]
    return Response(MetricaTiempoEsperaMesaSerializer(data, many=True).data)


# --- Métrica 2: empleado que atiende más mesas ----------------------------------


@api_view(["GET"])
def metrica_empleados(request):
    """
    Ranking de Personal por cantidad de mesas distintas atendidas y total de
    entregas realizadas. Se identifica por codigo_tracking/alias, nunca por
    nombre real ni apariencia (ver Personal en models.py).
    """
    qs = (
        Personal.objects.filter(activo=True)
        .annotate(
            mesas_distintas_atendidas=Count("entregas__evento_ocupacion__mesa", distinct=True),
            total_entregas=Count("entregas", distinct=True),
        )
        .order_by("-mesas_distintas_atendidas", "-total_entregas")
    )
    data = [
        {
            "personal_id": p.id,
            "codigo_tracking": p.codigo_tracking,
            "alias": p.alias,
            "mesas_distintas_atendidas": p.mesas_distintas_atendidas,
            "total_entregas": p.total_entregas,
        }
        for p in qs
    ]
    return Response(MetricaEmpleadoSerializer(data, many=True).data)


# --- Métrica 3: mesas más y menos usadas -----------------------------------------


@api_view(["GET"])
def metrica_uso_mesas(request):
    """
    Uso por mesa: cantidad de ocupaciones y tiempo total ocupada. El tiempo de
    ocupaciones aún abiertas (fin=None) se calcula contra "ahora" para no perder
    esas mesas del ranking mientras el turno sigue en curso.
    """
    ahora = timezone.now()
    resultados = []
    for mesa in Mesa.objects.filter(activa=True):
        ocupaciones = mesa.eventos_ocupacion.exclude(estado=EventoOcupacion.Estado.FUSIONADA)
        total_ocupaciones = ocupaciones.count()
        tiempo_total = sum(
            ((o.fin or ahora) - o.inicio).total_seconds() for o in ocupaciones
        )
        resultados.append(
            {
                "mesa_id": mesa.id,
                "mesa_numero": mesa.numero,
                "total_ocupaciones": total_ocupaciones,
                "tiempo_total_ocupada_segundos": tiempo_total,
                "tiempo_promedio_por_ocupacion_segundos": (
                    tiempo_total / total_ocupaciones if total_ocupaciones else None
                ),
            }
        )
    resultados.sort(key=lambda r: r["total_ocupaciones"], reverse=True)
    return Response(MetricaUsoMesaSerializer(resultados, many=True).data)
