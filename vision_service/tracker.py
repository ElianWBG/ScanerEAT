"""
Wrapper sobre un tracker multi-objeto (SORT o DeepSORT) para mantener un ID
persistente por persona entre frames. DeepSORT (con embeddings de apariencia)
es el elegido para producción porque permite re-identificar personal cuando
sale y vuelve a entrar en cuadro; SORT (solo IoU+Kalman) sirve como fallback
liviano para pruebas o hardware sin GPU.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Track:
    track_id: int
    bbox: tuple[float, float, float, float]
    clase: str


class TrackerPersonas:
    """
    Uso esperado (una instancia persistente por cámara, alimentada frame a frame):

        tracker = TrackerPersonas(backend="deepsort")
        tracks = tracker.actualizar(detecciones_personas, frame)

    Igual que en detector.py, el backend real (deep_sort_realtime o filterpy
    para SORT) se importa de forma perezosa para no forzar esas dependencias
    pesadas en este entorno de reconstrucción.
    """

    def __init__(self, backend: str = "deepsort"):
        self.backend = backend
        self._impl = None

    def _cargar_backend(self):
        if self._impl is not None:
            return self._impl
        if self.backend == "deepsort":
            from deep_sort_realtime.deepsort_tracker import DeepSort

            self._impl = DeepSort(max_age=30)
        elif self.backend == "sort":
            from sort import Sort  # implementación clásica de SORT (Bewley et al.)

            self._impl = Sort()
        else:
            raise ValueError(f"Backend de tracking desconocido: {self.backend}")
        return self._impl

    def actualizar(self, detecciones, frame=None) -> list[Track]:
        impl = self._cargar_backend()
        if self.backend == "deepsort":
            entradas = [
                ([d.bbox[0], d.bbox[1], d.bbox[2] - d.bbox[0], d.bbox[3] - d.bbox[1]], d.confianza, d.clase)
                for d in detecciones
            ]
            resultados = impl.update_tracks(entradas, frame=frame)
            tracks = []
            for t in resultados:
                if not t.is_confirmed():
                    continue
                x1, y1, x2, y2 = t.to_ltrb()
                tracks.append(Track(track_id=t.track_id, bbox=(x1, y1, x2, y2), clase="person"))
            return tracks
        else:  # sort
            import numpy as np

            dets_np = np.array(
                [[d.bbox[0], d.bbox[1], d.bbox[2], d.bbox[3], d.confianza] for d in detecciones]
            ) if detecciones else np.empty((0, 5))
            resultados = impl.update(dets_np)
            return [
                Track(track_id=int(r[4]), bbox=(r[0], r[1], r[2], r[3]), clase="person")
                for r in resultados
            ]
