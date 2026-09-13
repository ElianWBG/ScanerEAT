from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from monitoreo.models import EventoEntrega, EventoOcupacion, Mesa, Personal


class MetricasTestCase(TestCase):
    def setUp(self):
        self.mesa1 = Mesa.objects.create(numero=1, camara_id="cam-1", zona_poligono=[[0, 0], [1, 0], [1, 1], [0, 1]])
        self.mesa2 = Mesa.objects.create(numero=2, camara_id="cam-1", zona_poligono=[[1, 0], [2, 0], [2, 1], [1, 1]])
        self.mesero = Personal.objects.create(codigo_tracking="track-001", alias="Mesero A")

        inicio = timezone.now() - timedelta(minutes=30)
        self.ocupacion1 = EventoOcupacion.objects.create(
            mesa=self.mesa1, inicio=inicio, estado=EventoOcupacion.Estado.OCUPADA
        )
        self.ocupacion2 = EventoOcupacion.objects.create(
            mesa=self.mesa2, inicio=inicio, estado=EventoOcupacion.Estado.OCUPADA
        )

        EventoEntrega.objects.create(
            evento_ocupacion=self.ocupacion1,
            personal=self.mesero,
            tipo=EventoEntrega.Tipo.APERITIVO,
            timestamp=inicio + timedelta(minutes=5),
            tiempo_espera_segundos=300,
        )
        EventoEntrega.objects.create(
            evento_ocupacion=self.ocupacion1,
            personal=self.mesero,
            tipo=EventoEntrega.Tipo.PLATO_PRINCIPAL,
            timestamp=inicio + timedelta(minutes=15),
            tiempo_espera_segundos=900,
        )
        EventoEntrega.objects.create(
            evento_ocupacion=self.ocupacion2,
            personal=self.mesero,
            tipo=EventoEntrega.Tipo.PLATO_PRINCIPAL,
            timestamp=inicio + timedelta(minutes=10),
            tiempo_espera_segundos=600,
        )

    def test_tiempo_espera_promedio_por_ocupacion(self):
        self.assertEqual(self.ocupacion1.tiempo_espera_promedio_segundos, 600)

    def test_metrica_tiempo_espera_endpoint(self):
        resp = self.client.get(reverse("metrica-tiempo-espera"))
        self.assertEqual(resp.status_code, 200)
        por_mesa = {r["mesa_numero"]: r for r in resp.json()}
        self.assertEqual(por_mesa[1]["total_entregas"], 2)
        self.assertEqual(por_mesa[1]["tiempo_espera_promedio_segundos"], 600)

    def test_metrica_empleados_endpoint(self):
        resp = self.client.get(reverse("metrica-empleados"))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data[0]["mesas_distintas_atendidas"], 2)
        self.assertEqual(data[0]["total_entregas"], 3)

    def test_metrica_uso_mesas_endpoint(self):
        resp = self.client.get(reverse("metrica-uso-mesas"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 2)
