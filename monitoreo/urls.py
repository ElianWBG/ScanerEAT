from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("mesas", views.MesaViewSet, basename="mesa")
router.register("personal", views.PersonalViewSet, basename="personal")
router.register("ocupaciones", views.EventoOcupacionViewSet, basename="ocupacion")
router.register("entregas", views.EventoEntregaViewSet, basename="entrega")

urlpatterns = [
    path("", include(router.urls)),
    path("metricas/tiempo-espera/", views.metrica_tiempo_espera, name="metrica-tiempo-espera"),
    path("metricas/empleados/", views.metrica_empleados, name="metrica-empleados"),
    path("metricas/uso-mesas/", views.metrica_uso_mesas, name="metrica-uso-mesas"),
]
