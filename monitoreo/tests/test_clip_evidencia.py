from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from monitoreo.models import EventoOcupacion, Mesa


class ClipEvidenciaTestCase(TestCase):
    """Integración API: referencia al clip de evidencia en S3 por EventoOcupacion."""

    def setUp(self):
        self.mesa = Mesa.objects.create(
            numero=1, camara_id="cam-1", zona_poligono=[[0, 0], [1, 0], [1, 1], [0, 1]]
        )
        self.ocupacion = EventoOcupacion.objects.create(
            mesa=self.mesa,
            inicio=timezone.now() - timedelta(minutes=20),
            estado=EventoOcupacion.Estado.OCUPADA,
        )

    def test_campo_vacio_por_defecto(self):
        self.assertEqual(self.ocupacion.clip_s3_key, "")
        self.assertIsNone(self.ocupacion.clip_s3_url)

    def test_patch_adjunta_clip_al_cerrar(self):
        """Flujo del microservicio de visión: cierra la ocupación y adjunta la key del clip."""
        url = reverse("ocupacion-detail", args=[self.ocupacion.id])
        fin = timezone.now()
        key = "evidencia/cam-1/mesa-1/2026/09/11/ocupacion-20260911T120000.mp4"
        resp = self.client.patch(
            url,
            {"fin": fin.isoformat(), "estado": "liberada", "clip_s3_key": key},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.ocupacion.refresh_from_db()
        self.assertEqual(self.ocupacion.clip_s3_key, key)
        self.assertEqual(self.ocupacion.estado, EventoOcupacion.Estado.LIBERADA)

    @override_settings(AWS_STORAGE_BUCKET_NAME="mi-bucket", AWS_S3_REGION_NAME="us-east-2")
    def test_get_incluye_key_y_url_publica(self):
        key = "evidencia/cam-1/mesa-1/2026/09/11/ocupacion-20260911T120000.mp4"
        self.ocupacion.clip_s3_key = key
        self.ocupacion.save()
        resp = self.client.get(reverse("ocupacion-detail", args=[self.ocupacion.id]))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["clip_s3_key"], key)
        self.assertEqual(
            data["clip_s3_url"], f"https://mi-bucket.s3.us-east-2.amazonaws.com/{key}"
        )

    @override_settings(AWS_STORAGE_BUCKET_NAME="")
    def test_url_none_sin_bucket_configurado(self):
        self.ocupacion.clip_s3_key = "evidencia/x.mp4"
        self.assertIsNone(self.ocupacion.clip_s3_url)
